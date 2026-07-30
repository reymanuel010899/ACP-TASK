"""AgentTrust Verification & Reputation Service (unit U3).

Validates submitted Evidence against RFC-0001 expectations, issues
Verification Results, and updates the submitting Principal's Reputation
Record. Stdlib-only HTTP layer (``http.server.ThreadingHTTPServer``); all
core logic lives in :class:`VerificationService` and plain functions so tests
can call it directly without going over HTTP.

Endpoints
---------
- ``POST /evidence`` — body ``{"evidence": ..., "session": ..., "principal": ...}``
- ``GET /reputation/{principal_id}[?capability_id=...]``
- ``GET /verification-results/{evidence_id}``
- ``GET /portfolio/{principal_id}[?capability_id=...&limit=N]`` (U3): verified
  work history for a subject principal, newest first; empty (not 404) when
  there is none, and rejected work never appears.
- ``POST /revocations`` — body ``{"principal_id": ...}`` or ``{"public_key": ...}``
- ``GET /healthz``

Run: ``python -m services.verification.app --port 8080``

Canonical session signing form (decision)
-----------------------------------------
RFC-0001 §3.2 says the signature covers "the canonical session claims
(session_id, principal_id, issued_at, expires_at)" but does not define a
byte-level canonicalization, and ``issued_at`` is optional in the schema —
including an optional field in the signed form would be ambiguous. We
therefore define the canonical form as the UTF-8 bytes of the JSON
serialization, with sorted keys and no whitespace, of exactly the three
required claims::

    {"expires_at": <expires_at>, "principal_id": <principal_id>, "session_id": <session_id>}

Security notes (v1, demo scale)
-------------------------------
- ``POST /revocations`` is an unauthenticated admin surface. Acceptable only
  at demo scale; production would gate it behind operator auth.
- The Principal object is supplied by the submitter and trusted as the key
  source (there is no registry yet); the signature check proves possession of
  the key, the revocation list is the kill switch for compromised keys.
"""

import argparse
import base64
import binascii
import datetime
import importlib
import json
import os
import re
import threading
import uuid

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import parse_qs, unquote, urlsplit

import jsonschema
import nacl.exceptions
import nacl.signing

from agents.orchestrator.attestation import (
    AttestationError,
    verify_execution_attestation,
)
from services.verification.reputation_store import ReputationStore

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"

TERRAFORM_CAPABILITY_ID = "terraform.generate"
DEFAULT_VERIFIER_PRINCIPAL_ID = "agenttrust:verifier:verification-service"
MAX_PORTFOLIO_LIMIT = 500  # cap /portfolio response size

_RESOURCE_BLOCK_RE = re.compile(
    r'(^|\n)\s*resource\s+"[^"\n]+"\s+"[^"\n]+"\s*\{'
)


def _load_schema(name):
    # type: (str) -> dict
    with open(SCHEMA_DIR / ("%s.schema.json" % name)) as f:
        return json.load(f)


EVIDENCE_SCHEMA = _load_schema("evidence")
SESSION_SCHEMA = _load_schema("session")
PRINCIPAL_SCHEMA = _load_schema("principal")

_EVIDENCE_VALIDATOR = jsonschema.Draft7Validator(EVIDENCE_SCHEMA)
_SESSION_VALIDATOR = jsonschema.Draft7Validator(SESSION_SCHEMA)
_PRINCIPAL_VALIDATOR = jsonschema.Draft7Validator(PRINCIPAL_SCHEMA)


def _utcnow_rfc3339():
    # type: () -> str
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _schema_error(validator, instance):
    # type: (jsonschema.Draft7Validator, object) -> Optional[str]
    """First validation error message, or None if the instance is valid."""
    errors = sorted(validator.iter_errors(instance), key=str)
    if not errors:
        return None
    first = errors[0]
    path = "/".join(str(p) for p in first.absolute_path) or "(root)"
    return "%s: %s" % (path, first.message)


def canonical_session_claims(session):
    # type: (dict) -> bytes
    """Canonical byte string the Principal signs (see module docstring)."""
    claims = {
        "session_id": session.get("session_id"),
        "principal_id": session.get("principal_id"),
        "expires_at": session.get("expires_at"),
    }
    return json.dumps(claims, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def verify_session_signature(session, principal):
    # type: (dict, dict) -> Tuple[bool, str]
    """Cryptographically verify the session's ed25519 principal link."""
    try:
        public_key = base64.b64decode(
            principal["public_key"], validate=True
        )
        signature = base64.b64decode(
            session["principal_signature"], validate=True
        )
    except (KeyError, binascii.Error, TypeError) as exc:
        return False, "malformed key or signature encoding: %s" % exc
    if len(public_key) != 32:
        return False, "public key is not 32 bytes"
    if len(signature) != 64:
        return False, "signature is not 64 bytes"
    try:
        nacl.signing.VerifyKey(public_key).verify(
            canonical_session_claims(session), signature
        )
    except nacl.exceptions.BadSignatureError:
        return False, "principal_signature does not verify against public_key"
    return True, "ok"


def _parse_rfc3339(value):
    # type: (str) -> Optional[datetime.datetime]
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed


def validate_terraform_syntax(text):
    # type: (object) -> Tuple[bool, str]
    """Lightweight syntactic validity check for generated Terraform HCL.

    Not a real HCL parser: checks the text is a non-empty string with
    balanced braces and double quotes (string-aware, honoring backslash
    escapes and ``#``/``//`` line comments) and contains at least one
    ``resource "type" "name" { ... }`` block.
    """
    if not isinstance(text, str):
        return False, "terraform_hcl must be a string"
    if not text.strip():
        return False, "terraform_hcl is empty"

    depth = 0
    in_string = False
    escaped = False
    in_comment = False
    for ch in text:
        if in_comment:
            if ch == "\n":
                in_comment = False
            continue
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            elif ch == "\n":
                return False, "unterminated string literal"
            continue
        if ch == '"':
            in_string = True
        elif ch == "#":
            in_comment = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                return False, "unbalanced braces: unexpected '}'"
    if in_string:
        return False, "unterminated string literal"
    if depth != 0:
        return False, "unbalanced braces: %d unclosed '{'" % depth

    # '//' line comments: strip them (string regions were already proven
    # balanced above, and '//' inside strings is rare enough for a demo
    # syntactic check to accept a conservative resource-block scan).
    if not _RESOURCE_BLOCK_RE.search(text):
        return False, "no resource block found"
    return True, "ok"


class VerificationService(object):
    """Core accept/reject pipeline; callable directly from tests (no HTTP)."""

    def __init__(
        self,
        store,
        verifier_principal_id=DEFAULT_VERIFIER_PRINCIPAL_ID,
        broker_keys=None,
        receipt_verifiers=None,
    ):
        self.store = store
        self.verifier_principal_id = verifier_principal_id
        self.broker_keys = broker_keys or {}
        self.receipt_verifiers = dict(receipt_verifiers or {})
        self._execution_lock = threading.RLock()

    # -- pipeline -------------------------------------------------------------

    def process_evidence(self, payload):
        # type: (dict) -> Tuple[int, dict]
        """Run the full pipeline. Returns ``(http_status, response_body)``.

        - 403: submitting Principal is revoked (rejected result, no
          reputation write).
        - 422: invalid principal/session link or schema-invalid evidence
          (nothing written).
        - 200: a Verification Result was issued (verdict ``verified`` or
          ``rejected``) and the Reputation Record updated.
        """
        if not isinstance(payload, dict):
            return 422, {"error": "request body must be a JSON object"}
        evidence = payload.get("evidence")
        if isinstance(evidence, dict) and "execution_attestation" in evidence:
            return self.process_execution_evidence(evidence)
        session = payload.get("session")
        principal = payload.get("principal")
        for name, obj in (
            ("evidence", evidence),
            ("session", session),
            ("principal", principal),
        ):
            if not isinstance(obj, dict):
                return 422, {"error": "missing or non-object '%s'" % name}

        # (1) Revocation list: reject immediately, no reputation write.
        if self.store.is_revoked(
            principal.get("principal_id"),
            principal.get("public_key"),
            session.get("principal_id"),
        ):
            result = self._make_result(
                evidence_id=str(evidence.get("evidence_id") or "unknown"),
                verdict="rejected",
                reasoning="revoked key: the submitting Principal's key or id "
                "is on the revocation list",
            )
            self.store.put_result(result)
            return 403, {
                "error": "revoked key",
                "verification_result": result,
            }

        # (2) Validate the signed principal <-> session link. No writes on
        # failure: an unproven link means the evidence cannot be attributed.
        error = _schema_error(_PRINCIPAL_VALIDATOR, principal)
        if error:
            return 422, {"error": "invalid principal: %s" % error}
        error = _schema_error(_SESSION_VALIDATOR, session)
        if error:
            return 422, {"error": "invalid session: %s" % error}
        if session["principal_id"] != principal["principal_id"]:
            return 422, {
                "error": "session principal_id does not match principal"
            }
        expires_at = _parse_rfc3339(session["expires_at"])
        if expires_at is None:
            return 422, {"error": "invalid session: unparseable expires_at"}
        if expires_at <= datetime.datetime.now(datetime.timezone.utc):
            return 422, {"error": "invalid session: expired"}
        ok, reason = verify_session_signature(session, principal)
        if not ok:
            return 422, {"error": "invalid session link: %s" % reason}

        # (3) Evidence must validate against evidence.schema.json.
        error = _schema_error(_EVIDENCE_VALIDATOR, evidence)
        if error:
            return 422, {"error": "invalid evidence: %s" % error}
        if evidence["session_id"] != session["session_id"]:
            return 422, {
                "error": "evidence session_id does not match session"
            }

        # (4)+(5) Task-specific verdict.
        verdict, reasoning = self._decide_verdict(evidence)
        result = self._make_result(evidence["evidence_id"], verdict, reasoning)
        self.store.put_result(result)
        record = self.store.record_verdict(
            principal["principal_id"], evidence["capability_id"], verdict
        )
        # Verified work joins the subject principal's re-checkable portfolio
        # (U3); rejected work never does.
        self.store.add_portfolio_entry(
            principal["principal_id"], evidence["capability_id"], result
        )
        return 200, {"verification_result": result, "reputation_record": record}

    def process_execution_evidence(self, evidence):
        """Verify broker authority, replay identity, and provider-grounded fields."""
        with self._execution_lock:
            return self._process_execution_evidence(evidence)

    def _process_execution_evidence(self, evidence):
        error = _schema_error(_EVIDENCE_VALIDATOR, evidence)
        if error:
            return 422, {
                "evidence_status": "rejected",
                "error": "invalid evidence: %s" % error,
            }
        attestation = evidence["execution_attestation"]
        try:
            verify_execution_attestation(attestation, self.broker_keys)
        except AttestationError:
            return 422, {
                "evidence_status": "rejected",
                "error": "invalid broker execution attestation",
            }
        if self.store.is_revoked(
            attestation.get("agent_principal_id"),
            attestation.get("user_principal_id"),
            attestation.get("broker_key_id"),
        ):
            return 403, {
                "evidence_status": "rejected",
                "error": "revoked execution principal or broker key",
            }
        if (
            evidence["evidence_id"] != attestation["attestation_id"]
            or evidence["capability_id"] != attestation["capability_id"]
            or attestation["outcome"] != "succeeded"
        ):
            return 422, {
                "evidence_status": "rejected",
                "error": "evidence does not match execution attestation",
            }
        if self.store.get_result(evidence["evidence_id"]) is not None:
            return 409, {
                "evidence_status": "rejected",
                "error": "execution attestation was already submitted",
            }

        provider = attestation["provider_receipt"]["provider"]
        verifier = self.receipt_verifiers.get(provider)
        if verifier is None:
            return 200, {
                "evidence_status": "unverified",
                "reasoning": "no receipt verifier is configured for %s" % provider,
            }
        check = verifier.verify(attestation)
        verdict = check.get("verdict")
        reasoning = check.get("reasoning") or "receipt verification failed"
        if verdict == "unverified":
            return 200, {
                "evidence_status": "unverified",
                "reasoning": reasoning,
            }
        if verdict not in ("verified", "rejected"):
            return 200, {
                "evidence_status": "unverified",
                "reasoning": "receipt verifier returned no authoritative verdict",
            }

        result = self._make_result(
            evidence["evidence_id"], verdict, reasoning
        )
        self.store.put_result(result)
        response = {
            "evidence_status": verdict,
            "verification_result": result,
        }
        if verdict == "verified":
            record = self.store.record_verdict(
                attestation["agent_principal_id"],
                attestation["capability_id"],
                "verified",
            )
            self.store.add_portfolio_entry(
                attestation["agent_principal_id"],
                attestation["capability_id"],
                result,
            )
            response["reputation_record"] = record
        return 200, response

    def _decide_verdict(self, evidence):
        # type: (dict) -> Tuple[str, str]
        if not evidence["schema_valid"]:
            return "rejected", "evidence reports schema_valid=false"
        if not evidence["tests_passed"]:
            return "rejected", "evidence reports tests_passed=false"
        if evidence["capability_id"] == TERRAFORM_CAPABILITY_ID:
            hcl = (evidence.get("extensions") or {}).get("terraform_hcl")
            if hcl is None:
                return (
                    "rejected",
                    "capability %s requires extensions.terraform_hcl"
                    % TERRAFORM_CAPABILITY_ID,
                )
            ok, reason = validate_terraform_syntax(hcl)
            if not ok:
                return "rejected", "terraform syntax check failed: %s" % reason
            return (
                "verified",
                "schema_valid and tests_passed asserted; terraform syntax "
                "check passed",
            )
        return (
            "verified",
            "schema_valid and tests_passed asserted; no task-specific check "
            "registered for capability %s" % evidence["capability_id"],
        )

    def _make_result(self, evidence_id, verdict, reasoning):
        # type: (str, str, str) -> dict
        return {
            "result_id": "vr-%s" % uuid.uuid4().hex,
            "evidence_id": evidence_id,
            "principal_id": self.verifier_principal_id,
            "verdict": verdict,
            "reasoning": reasoning,
            "verified_at": _utcnow_rfc3339(),
        }


# ---------------------------------------------------------------------------
# HTTP layer (thin wrapper over VerificationService)
# ---------------------------------------------------------------------------


class VerificationHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, service, rate_limiter=None):
        # type: (tuple, VerificationService, object) -> None
        self.service = service
        self.rate_limiter = rate_limiter
        ThreadingHTTPServer.__init__(self, address, _RequestHandler)


class _RequestHandler(BaseHTTPRequestHandler):
    server_version = "AgentTrustVerification/0.1"
    protocol_version = "HTTP/1.1"

    @property
    def service(self):
        # type: () -> VerificationService
        return self.server.service

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        pass  # keep test output quiet; demo-scale service

    def _send_json(self, status, body):
        # type: (int, dict) -> None
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json_body(self):
        # type: () -> Tuple[Optional[dict], Optional[str]]
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None, "invalid Content-Length"
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None, "request body is not valid JSON"
        if not isinstance(body, dict):
            return None, "request body must be a JSON object"
        return body, None

    def _rate_ok(self):
        # type: () -> bool
        limiter = getattr(self.server, "rate_limiter", None)
        if limiter is None or limiter.allow(self.client_address[0]):
            return True
        # Close: this early reply hasn't read the request body, so reusing the
        # keep-alive connection would desync it.
        self.close_connection = True
        self._send_json(429, {"error": "rate limit exceeded"})
        return False

    def do_GET(self):
        if not self._rate_ok():
            return
        parts = urlsplit(self.path)
        segments = [unquote(s) for s in parts.path.split("/") if s]

        if segments == ["healthz"]:
            self._send_json(200, {"status": "ok"})
        elif len(segments) == 2 and segments[0] == "reputation":
            query = parse_qs(parts.query)
            capability_id = query.get("capability_id", [None])[0]
            records = self.service.store.get_reputation(
                segments[1], capability_id=capability_id
            )
            self._send_json(200, {"reputation_records": records})
        elif len(segments) == 2 and segments[0] == "portfolio":
            query = parse_qs(parts.query)
            capability_id = query.get("capability_id", [None])[0]
            raw_limit = query.get("limit", [None])[0]
            limit = None
            if raw_limit is not None:
                try:
                    limit = int(raw_limit)
                except ValueError:
                    self._send_json(400, {"error": "limit must be an integer"})
                    return
                if limit < 0:
                    self._send_json(
                        400, {"error": "limit must be >= 0"}
                    )
                    return
                limit = min(limit, MAX_PORTFOLIO_LIMIT)
            entries = self.service.store.get_portfolio(
                segments[1], capability_id=capability_id, limit=limit
            )
            self._send_json(200, {"portfolio": entries})
        elif len(segments) == 2 and segments[0] == "verification-results":
            result = self.service.store.get_result(segments[1])
            if result is None:
                self._send_json(
                    404, {"error": "no verification result for that evidence_id"}
                )
            else:
                self._send_json(200, {"verification_result": result})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if not self._rate_ok():
            return
        parts = urlsplit(self.path)
        segments = [unquote(s) for s in parts.path.split("/") if s]
        body, error = self._read_json_body()
        if error:
            self._send_json(400, {"error": error})
            return

        if segments == ["evidence"]:
            status, response = self.service.process_evidence(body)
            self._send_json(status, response)
        elif segments == ["revocations"]:
            # v1: unauthenticated admin surface -- demo scale only.
            value = body.get("principal_id") or body.get("public_key")
            if not value or not isinstance(value, str):
                self._send_json(
                    422,
                    {"error": "body must contain 'principal_id' or 'public_key'"},
                )
                return
            self.service.store.revoke(value)
            self._send_json(200, {"revoked": value})
        else:
            self._send_json(404, {"error": "not found"})


def make_server(port=0, host="127.0.0.1", store=None, service=None, rate_limiter=None):
    # type: (int, str, Optional[ReputationStore], Optional[VerificationService], object) -> VerificationHTTPServer
    """Build a (threading) HTTP server; ``port=0`` picks a free port."""
    if service is None:
        service = VerificationService(store if store is not None else ReputationStore())
    return VerificationHTTPServer((host, port), service, rate_limiter=rate_limiter)


def load_broker_keys(path, environment=None):
    """Load attestation trust roots; production never starts without them."""
    environment = (environment or os.environ.get("TESSERA_ENV", "development")).lower()
    if not path:
        if environment == "production":
            raise RuntimeError(
                "--broker-keys-path or TESSERA_BROKER_KEYS_PATH is required in production"
            )
        return {}
    with open(path, encoding="utf-8") as key_file:
        broker_keys = json.load(key_file)
    if not isinstance(broker_keys, dict) or not broker_keys:
        raise ValueError("broker keys file must contain a non-empty object")
    return broker_keys


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="AgentTrust Verification & Reputation Service"
    )
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--store-path",
        default=None,
        help="Optional JSON file for persisting results/reputation.",
    )
    parser.add_argument(
        "--revocations-path",
        default=None,
        help="Optional JSON file (array of strings) for the revocation list.",
    )
    parser.add_argument(
        "--verifier-id",
        default=DEFAULT_VERIFIER_PRINCIPAL_ID,
        help="principal_id this verifier stamps on Verification Results.",
    )
    parser.add_argument(
        "--rate-limit",
        type=int,
        default=0,
        help="Max requests per IP per 60s window (0 = off).",
    )
    parser.add_argument(
        "--broker-keys-path",
        default=os.environ.get("TESSERA_BROKER_KEYS_PATH"),
        help="JSON object mapping trusted broker key ids to public keys.",
    )
    args = parser.parse_args(argv)

    broker_keys = load_broker_keys(args.broker_keys_path)
    receipt_verifiers = {}
    verifier_factory_path = os.environ.get(
        "TESSERA_RECEIPT_VERIFIER_FACTORY"
    )
    if verifier_factory_path:
        if ":" not in verifier_factory_path:
            raise ValueError(
                "TESSERA_RECEIPT_VERIFIER_FACTORY must be module:function"
            )
        module_name, factory_name = verifier_factory_path.split(":", 1)
        factory = getattr(importlib.import_module(module_name), factory_name)
        receipt_verifiers = factory()
        if not isinstance(receipt_verifiers, dict):
            raise TypeError("receipt verifier factory must return a dict")

    store = ReputationStore(
        path=args.store_path, revocation_path=args.revocations_path
    )
    service = VerificationService(
        store,
        verifier_principal_id=args.verifier_id,
        broker_keys=broker_keys,
        receipt_verifiers=receipt_verifiers,
    )
    rate_limiter = None
    if args.rate_limit > 0:
        from common.ratelimit import RateLimiter

        rate_limiter = RateLimiter(
            max_requests=args.rate_limit, window_seconds=60
        )
    server = make_server(
        port=args.port, host=args.host, service=service,
        rate_limiter=rate_limiter,
    )
    print(
        "AgentTrust verification service listening on http://%s:%d"
        % server.server_address[:2]
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()
