"""AgentTrust demo Provider Agent (unit U6).

An independently-buildable A2A server exposing the ``terraform.generate``
skill. It publishes its Agent Card at ``/.well-known/agent-card.json``,
answers ``message/send`` JSON-RPC calls with a single-offer negotiation
(``task.request`` -> ``task.offer`` -> ``task.accept`` -> ``task.result``,
KTD6), and — when the client opts in via the ``A2A-Extensions`` header —
attaches AgentTrust Evidence and the independent Verification Result as
extension metadata on the result message (RFC-0002).

Hard constraint (R6): this package is written from the published spec and
schemas alone. It MUST NOT import from ``services`` or ``registry`` — it
talks to the Verification Service and the Registry only over their HTTP
contracts. There is a guard test enforcing this.

Session signing follows the canonical form fixed by RFC-0001 §3.2 as
interpreted by the Verification Service: the UTF-8 bytes of the compact,
key-sorted JSON serialization of exactly the three required claims
(``expires_at``, ``principal_id``, ``session_id``).

Run: ``python -m agents.provider.agent --port 8100
--verification-url URL [--registry-url URL --api-key KEY] [--keys-dir DIR]``
"""

import argparse
import base64
import datetime
import hashlib
import json
import os
import threading
import uuid

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional, Tuple

import nacl.signing
import requests

from agents.provider.terraform_generate import (
    SUPPORTED_LOAD_BALANCERS,
    generate_terraform,
    validate_own_output,
)

TRUST_EXTENSION_URI = "https://agenttrust.example/extensions/trust/v1"

CAPABILITY_ID = "terraform.generate"

DEFAULT_HTTP_TIMEOUT = 3.0
SESSION_TTL_SECONDS = 900

_KEY_FILENAME = "provider-signing.key"


def _utcnow():
    # type: () -> datetime.datetime
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)


def _rfc3339(moment):
    # type: (datetime.datetime) -> str
    return moment.isoformat().replace("+00:00", "Z")


def load_or_create_keypair(keys_dir):
    # type: (str) -> nacl.signing.SigningKey
    """Load the Principal's ed25519 key from ``keys_dir``, creating it once.

    The key is generated locally and never transmitted (KTD8). The directory
    gets a ``.gitignore`` ignoring everything so the private key can never be
    committed, and the key file itself is chmod 0600.
    """
    os.makedirs(keys_dir, exist_ok=True)
    gitignore = os.path.join(keys_dir, ".gitignore")
    if not os.path.exists(gitignore):
        with open(gitignore, "w") as f:
            f.write("*\n")
    key_path = os.path.join(keys_dir, _KEY_FILENAME)
    if os.path.exists(key_path):
        with open(key_path, "rb") as f:
            seed = base64.b64decode(f.read())
        return nacl.signing.SigningKey(seed)
    signing_key = nacl.signing.SigningKey.generate()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(key_path, flags, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(base64.b64encode(bytes(signing_key)))
    return signing_key


def canonical_session_claims(session):
    # type: (dict) -> bytes
    """Canonical byte string the Principal signs (RFC-0001 §3.2)."""
    claims = {
        "session_id": session.get("session_id"),
        "principal_id": session.get("principal_id"),
        "expires_at": session.get("expires_at"),
    }
    return json.dumps(claims, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _validate_task_input(payload):
    # type: (dict) -> Optional[str]
    """Reason the ``task.request`` input is invalid, or None if acceptable.

    Mirrors :func:`generate_terraform`'s own input contract so a bad request
    is refused up front (JSON-RPC -32602) instead of failing at execution.
    """
    task_input = payload.get("input")
    if not isinstance(task_input, dict):
        return "'input' must be an object"
    containers = task_input.get("containers")
    if isinstance(containers, bool) or not isinstance(containers, int):
        return "input.containers must be an integer"
    if containers < 1:
        return "input.containers must be >= 1"
    load_balancer = task_input.get("load_balancer")
    if load_balancer not in SUPPORTED_LOAD_BALANCERS:
        return "input.load_balancer must be one of: %s" % ", ".join(
            SUPPORTED_LOAD_BALANCERS
        )
    return None


class RpcError(Exception):
    """A JSON-RPC error the HTTP layer turns into an error response."""

    def __init__(self, code, message):
        # type: (int, str) -> None
        Exception.__init__(self, message)
        self.code = code
        self.message = message


class ProviderAgent(object):
    """Core provider logic; the HTTP layer is a thin JSON-RPC wrapper."""

    def __init__(
        self,
        base_url,
        verification_url,
        registry_url=None,
        api_key=None,
        keys_dir=None,
        http_timeout=DEFAULT_HTTP_TIMEOUT,
    ):
        # type: (str, str, Optional[str], Optional[str], Optional[str], float) -> None
        self.base_url = base_url
        self.verification_url = verification_url
        self.registry_url = registry_url
        self.api_key = api_key
        self.http_timeout = http_timeout

        if keys_dir is None:
            keys_dir = os.path.join(os.path.dirname(__file__), "keys")
        self.signing_key = load_or_create_keypair(keys_dir)
        public_key = base64.b64encode(
            bytes(self.signing_key.verify_key)
        ).decode("ascii")
        self.principal = {
            "principal_id": "atp:principal:demo-provider:%s"
            % hashlib.sha256(public_key.encode("ascii")).hexdigest()[:16],
            "public_key": public_key,
            "key_algorithm": "ed25519",
            "display_name": "AgentTrust demo Terraform provider",
        }

        self._pending_tasks = {}
        self._lock = threading.Lock()

    @property
    def principal_id(self):
        # type: () -> str
        return self.principal["principal_id"]

    # -- identity ---------------------------------------------------------------

    def new_session(self):
        # type: () -> dict
        """A fresh Session, cryptographically bound to this Principal (KTD4)."""
        now = _utcnow()
        session = {
            "session_id": "sess-%s" % uuid.uuid4().hex,
            "principal_id": self.principal_id,
            "issued_at": _rfc3339(now),
            "expires_at": _rfc3339(
                now + datetime.timedelta(seconds=SESSION_TTL_SECONDS)
            ),
        }
        signature = self.signing_key.sign(
            canonical_session_claims(session)
        ).signature
        session["principal_signature"] = base64.b64encode(signature).decode(
            "ascii"
        )
        return session

    # -- Agent Card ---------------------------------------------------------------

    def agent_card(self):
        # type: () -> dict
        return {
            "name": "AgentTrust demo provider",
            "description": "Generates Terraform HCL modules: N container "
            "services behind an AWS Application Load Balancer.",
            "url": self.base_url,
            "version": "0.1.0",
            "protocolVersion": "0.3.0",
            "preferredTransport": "JSONRPC",
            "capabilities": {
                "streaming": False,
                "pushNotifications": False,
                "extensions": [
                    {
                        "uri": TRUST_EXTENSION_URI,
                        "description": "AgentTrust trust layer: signed "
                        "sessions, machine-checkable Evidence on task "
                        "results, independent verification, per-capability "
                        "reputation.",
                        "required": False,
                        "params": {
                            "principal_id": self.principal_id,
                            "verification_service_url": self.verification_url,
                        },
                    }
                ],
            },
            "defaultInputModes": ["application/json"],
            "defaultOutputModes": ["application/json"],
            "skills": [
                {
                    "id": CAPABILITY_ID,
                    "name": "Terraform module generation",
                    "description": "Generate a Terraform HCL module that "
                    "deploys N containers behind an AWS Application Load "
                    "Balancer.",
                    "tags": ["terraform", "iac", "codegen"],
                }
            ],
        }

    def register_with_registry(self):
        # type: () -> bool
        """Publish the Agent Card to the configured registry. False on any failure."""
        if not self.registry_url:
            return False
        try:
            resp = requests.post(
                self.registry_url.rstrip("/") + "/register",
                json={
                    "agent_card": self.agent_card(),
                    "principal_id": self.principal_id,
                    "api_key": self.api_key,
                },
                timeout=self.http_timeout,
            )
        except requests.RequestException:
            return False
        return resp.status_code == 200

    # -- task lifecycle -------------------------------------------------------------

    def handle_payload(self, payload):
        # type: (dict) -> dict
        """Dispatch one extension-level payload; raises :class:`RpcError`."""
        if not isinstance(payload, dict):
            raise RpcError(-32602, "data part must be a JSON object")
        payload_type = payload.get("type")
        if payload_type == "task.request":
            return self._handle_request(payload)
        if payload_type == "task.accept":
            return self._handle_accept(payload)
        raise RpcError(
            -32602, "unsupported payload type: %r" % (payload_type,)
        )

    def _handle_request(self, payload):
        # type: (dict) -> dict
        reason = _validate_task_input(payload)
        if reason:
            raise RpcError(-32602, "invalid task.request: %s" % reason)
        task_id = "task-%s" % uuid.uuid4().hex
        with self._lock:
            self._pending_tasks[task_id] = dict(payload["input"])
        return {
            "type": "task.offer",
            "task_id": task_id,
            "capability_id": CAPABILITY_ID,
            "terms": {
                "price": "0",
                "currency": "USD",
                "delivery": "immediate",
                "verification": "evidence submitted to an independent "
                "verification service before completion",
            },
        }

    def _handle_accept(self, payload):
        # type: (dict) -> dict
        task_id = payload.get("task_id")
        with self._lock:
            task_input = self._pending_tasks.pop(task_id, None)
        if task_input is None:
            raise RpcError(
                -32602, "unknown or already-completed task_id: %r" % (task_id,)
            )
        hcl = generate_terraform(
            task_input["containers"], task_input["load_balancer"]
        )
        evidence = self._make_evidence(hcl)
        result = {
            "type": "task.result",
            "task_id": task_id,
            "task_state": "completed",
            "artifacts": {"main.tf": hcl},
        }
        return {"result": result, "trust": self._submit_evidence(evidence)}

    def _make_evidence(self, hcl):
        # type: (str) -> dict
        session = self.new_session()
        evidence = {
            "evidence_id": "ev-%s" % uuid.uuid4().hex,
            "session_id": session["session_id"],
            "capability_id": CAPABILITY_ID,
            "schema_valid": validate_own_output(hcl),
            "tests_passed": validate_own_output(hcl),
            "artifact_hashes": {
                "main.tf": hashlib.sha256(hcl.encode("utf-8")).hexdigest()
            },
            "created_at": _rfc3339(_utcnow()),
            "extensions": {"terraform_hcl": hcl},
        }
        return {
            "evidence": evidence,
            "session": session,
            "principal": self.principal,
        }

    def _submit_evidence(self, submission):
        # type: (dict) -> dict
        """Submit to the Verification Service; unreachable = ``pending``."""
        trust = {
            "evidence_status": "pending",
            "evidence": submission["evidence"],
        }
        try:
            resp = requests.post(
                self.verification_url.rstrip("/") + "/evidence",
                json=submission,
                timeout=self.http_timeout,
            )
            body = resp.json()
        except (requests.RequestException, ValueError):
            return trust
        verification_result = body.get("verification_result")
        if not isinstance(verification_result, dict):
            return trust
        trust["verification_result"] = verification_result
        trust["evidence_status"] = verification_result.get(
            "verdict", "pending"
        )
        return trust


# ---------------------------------------------------------------------------
# HTTP layer (A2A JSON-RPC + Agent Card well-known path)
# ---------------------------------------------------------------------------


class ProviderHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address,
        verification_url,
        registry_url=None,
        api_key=None,
        keys_dir=None,
        http_timeout=DEFAULT_HTTP_TIMEOUT,
    ):
        # type: (tuple, str, Optional[str], Optional[str], Optional[str], float) -> None
        ThreadingHTTPServer.__init__(self, address, _RequestHandler)
        self.agent = ProviderAgent(
            base_url="http://%s:%d" % self.server_address[:2],
            verification_url=verification_url,
            registry_url=registry_url,
            api_key=api_key,
            keys_dir=keys_dir,
            http_timeout=http_timeout,
        )


class _RequestHandler(BaseHTTPRequestHandler):
    server_version = "AgentTrustProvider/0.1"
    protocol_version = "HTTP/1.1"

    @property
    def agent(self):
        # type: () -> ProviderAgent
        return self.server.agent

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        pass  # keep test output quiet; demo-scale agent

    def _send_json(self, status, body, opted_in=False):
        # type: (int, dict, bool) -> None
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        if opted_in:
            self.send_header("A2A-Extensions", TRUST_EXTENSION_URI)
        self.end_headers()
        self.wfile.write(data)

    def _client_opted_in(self):
        # type: () -> bool
        header = self.headers.get("A2A-Extensions", "")
        return TRUST_EXTENSION_URI in [
            uri.strip() for uri in header.split(",")
        ]

    def do_GET(self):
        if self.path == "/.well-known/agent-card.json":
            self._send_json(200, self.agent.agent_card())
        elif self.path == "/healthz":
            self._send_json(200, {"status": "ok"})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(400, {"error": "invalid Content-Length"})
            return
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            body = None
        if not isinstance(body, dict):
            self._send_json(
                200,
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": "parse error"},
                },
            )
            return

        request_id = body.get("id")
        opted_in = self._client_opted_in()
        try:
            message = self._dispatch(body, opted_in)
        except RpcError as exc:
            self._send_json(
                200,
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": exc.code, "message": exc.message},
                },
            )
            return
        self._send_json(
            200,
            {"jsonrpc": "2.0", "id": request_id, "result": message},
            opted_in=opted_in,
        )

    def _dispatch(self, body, opted_in):
        # type: (dict, bool) -> dict
        if body.get("method") != "message/send":
            raise RpcError(
                -32601, "method not found: %r" % (body.get("method"),)
            )
        params = body.get("params")
        if not isinstance(params, dict):
            raise RpcError(-32602, "missing 'params'")
        message = params.get("message")
        if not isinstance(message, dict):
            raise RpcError(-32602, "missing 'params.message'")
        payload = None
        for part in message.get("parts") or []:
            if isinstance(part, dict) and part.get("kind") == "data":
                payload = part.get("data")
                break
        if payload is None:
            raise RpcError(-32602, "message has no data part")

        outcome = self.agent.handle_payload(payload)
        if "result" in outcome and "trust" in outcome:
            data, trust = outcome["result"], outcome["trust"]
        else:
            data, trust = outcome, None

        reply = {
            "kind": "message",
            "messageId": "msg-%s" % uuid.uuid4().hex,
            "role": "agent",
            "parts": [{"kind": "data", "data": data}],
        }
        if opted_in and trust is not None:
            reply["extensions"] = [TRUST_EXTENSION_URI]
            reply["metadata"] = {TRUST_EXTENSION_URI: trust}
        return reply


def make_server(
    port=0,
    host="127.0.0.1",
    verification_url=None,
    registry_url=None,
    api_key=None,
    keys_dir=None,
    http_timeout=DEFAULT_HTTP_TIMEOUT,
):
    # type: (int, str, Optional[str], Optional[str], Optional[str], Optional[str], float) -> ProviderHTTPServer
    """Build a (threading) HTTP server; ``port=0`` picks a free port."""
    return ProviderHTTPServer(
        (host, port),
        verification_url=verification_url,
        registry_url=registry_url,
        api_key=api_key,
        keys_dir=keys_dir,
        http_timeout=http_timeout,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="AgentTrust demo Provider Agent"
    )
    parser.add_argument("--port", type=int, default=8100)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--verification-url",
        required=True,
        help="Base URL of the Verification Service Evidence is submitted to.",
    )
    parser.add_argument(
        "--registry-url",
        default=None,
        help="Optional registry to publish the Agent Card to on startup.",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Registry-issued invite key required by POST /register.",
    )
    parser.add_argument(
        "--keys-dir",
        default=None,
        help="Directory holding the Principal's local ed25519 key "
        "(default: agents/provider/keys, git-ignored).",
    )
    args = parser.parse_args(argv)

    server = make_server(
        port=args.port,
        host=args.host,
        verification_url=args.verification_url,
        registry_url=args.registry_url,
        api_key=args.api_key,
        keys_dir=args.keys_dir,
    )
    if args.registry_url:
        registered = server.agent.register_with_registry()
        print(
            "registry registration: %s"
            % ("ok" if registered else "FAILED (continuing unregistered)")
        )
    print(
        "AgentTrust provider agent listening on http://%s:%d"
        % server.server_address[:2]
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()
