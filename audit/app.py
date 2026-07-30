"""Central Audit & Compliance service (Phase B, unit U12; persistence +
authentication, unit U4).

An append-only, queryable log of all significant ecosystem activities.
Services (Registry, Vault, apps, Agent Marketplace) emit entries here as a
best-effort, fire-and-forget side channel via ``libs.audit_client``; the
audit service being down must never break a caller.

Persistence (U4): entries are stored in the partitioned, append-only
Postgres table ``audit.audit_log`` (``audit/repository.py``,
``migrations/0004_audit.sql``) instead of an in-memory list -- a restart no
longer loses the trail, and ``UPDATE``/``DELETE`` are rejected by the
database itself, not just this HTTP layer's 405s.

Authentication (U4, closing a security-review finding): unlike every other
rewired service (Registry, Vault), this service previously had NO request
authentication at all -- anyone who could reach it could POST an entry under
an arbitrary ``principal_id``, which becomes a real forgery risk once this is
the *sole* canonical trail (the Vault's separate local log is folded in
here, KTD3). Both ``POST /audit`` and ``GET /audit`` now run the same shared
``libs.request_auth.RequestAuthenticator`` middleware every other rewired
service uses. Like those services, this is OPT-IN backward compatible:
``require_signatures=False`` (the default) is a pure no-op pass-through, so
existing unsigned callers/tests are unaffected until a deployment turns the
flag on.

API endpoints:
- POST   /audit    - append an entry {principal_id, activity_type, status,
                     resource_type?, resource_id?, details?} -> {"entry": {...}}
                     with a server-assigned entry_id (ULID) and RFC 3339 UTC
                     timestamp. 422 when principal_id/activity_type/status
                     are missing or empty. 401 when signatures are required
                     and the request doesn't carry a valid one.
- GET    /audit    - query with any combination of principal_id,
                     activity_type, resource_type, resource_id, start_time,
                     end_time (inclusive RFC 3339 bounds) and limit (default
                     100) -> {"entries": [... newest first ...],
                     "total_matched"}. 400 for an invalid limit or timestamp;
                     401 when signatures are required and the request
                     doesn't carry a valid one.
- PUT    /audit*   - 405 (the log is append-only; immutability is part of
- DELETE /audit*     the contract, enforced again at the database level)
- GET    /healthz  - health check (never authenticated)

``activity_type`` is an OPEN vocabulary — any dotted string is accepted so
new services can join without an audit-service release. The standard set:

    credential.access, credential.grant, credential.revoke, keyring.rotate,
    principal.register, agent.register, reputation.update, permission.check,
    work.bid, work.submit, work.complete, agent.hire, agent.rate,
    agent.revoke, app.register, service.register

Run: python -m audit.app [--port 8005]
"""

import argparse
import json

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional, Tuple
from urllib.parse import parse_qs, unquote, urlsplit

from audit.repository import AuditRepository
from libs.db import Database, bind_organization_id
from libs.request_auth import RequestAuthenticator

# Documented standard vocabulary (open set — never enforced on writes).
STANDARD_ACTIVITY_TYPES = (
    "credential.access",
    "credential.grant",
    "credential.revoke",
    "keyring.rotate",
    "principal.register",
    "agent.register",
    "reputation.update",
    "permission.check",
    "work.bid",
    "work.submit",
    "work.complete",
    "agent.hire",
    "agent.rate",
    "agent.revoke",
    "app.register",
    "service.register",
)


def _public_entry(row):
    # type: (dict) -> dict
    """Map a repository row (``created_at``, etc.) to the external HTTP
    shape. Keeps the pre-existing field name ``timestamp`` (not
    ``created_at``) so every caller written against the old in-memory
    ``AuditStore`` contract keeps working unmodified (R10) -- ``resource_type``
    and ``organization_id`` are additive fields new to U4, not removals."""
    return {
        "entry_id": row["entry_id"],
        "timestamp": row["created_at"],
        "principal_id": row["principal_id"],
        "activity_type": row["activity_type"],
        "status": row["status"],
        "resource_type": row.get("resource_type"),
        "resource_id": row.get("resource_id"),
        "organization_id": row.get("organization_id"),
        "details": row.get("details") or {},
    }


class AuditService:
    """Core audit logic; callable directly from tests (no HTTP). Persists to
    Postgres via :class:`audit.repository.AuditRepository` (unit U4)."""

    def __init__(self, repository=None, db=None, registry_url=None,
                 require_signatures=False, public_key_resolver=None):
        # type: (Optional[AuditRepository], Optional[Database], Optional[str], bool, Optional[object]) -> None
        self.repository = (
            repository if repository is not None
            else AuditRepository(db or Database())
        )
        # Shared request-authentication middleware (U15/U4). A pure no-op
        # pass-through while require_signatures is off, so the default
        # deployment keeps today's (unauthenticated) behavior byte-for-byte;
        # every caller of this class that wants the security fix turns the
        # flag on explicitly. Tests inject public_key_resolver so no live
        # Registry is needed.
        self.require_signatures = require_signatures
        self.authenticator = RequestAuthenticator(
            registry_url,
            require_signatures=require_signatures,
            public_key_resolver=public_key_resolver,
        )

    def log_activity(self, payload):
        # type: (dict) -> Tuple[int, dict]
        """Validate and append an entry; (http_status, response_body)."""
        if not isinstance(payload, dict):
            return 422, {"error": "request body must be a JSON object"}

        for field in ("principal_id", "activity_type", "status"):
            value = payload.get(field)
            if not isinstance(value, str) or not value:
                return 422, {
                    "error": "missing or non-empty-string '%s'" % field
                }

        resource_type = payload.get("resource_type")
        if resource_type is not None and not isinstance(resource_type, str):
            return 422, {"error": "'resource_type' must be a string if provided"}

        resource_id = payload.get("resource_id")
        if resource_id is not None and not isinstance(resource_id, str):
            return 422, {"error": "'resource_id' must be a string if provided"}

        organization_id = payload.get("organization_id")
        if organization_id is not None and not isinstance(organization_id, str):
            return 422, {"error": "'organization_id' must be a string if provided"}

        details = payload.get("details")
        if details is not None and not isinstance(details, dict):
            return 422, {"error": "'details' must be an object if provided"}

        row = self.repository.append(
            principal_id=payload["principal_id"],
            activity_type=payload["activity_type"],
            status=payload["status"],
            resource_type=resource_type,
            resource_id=resource_id,
            organization_id=organization_id,
            details=details if details is not None else {},
        )
        return 200, {"entry": _public_entry(row)}

    def query(self, principal_id=None, activity_type=None, resource_type=None,
              resource_id=None, organization_id=None, start_time=None,
              end_time=None, limit=100):
        # type: (Optional[str], Optional[str], Optional[str], Optional[str], Optional[str], Optional[str], Optional[str], int) -> Tuple[int, dict]
        """Filtered entries newest first plus the FULL match count."""
        try:
            entries, total = self.repository.query(
                principal_id=principal_id,
                activity_type=activity_type,
                resource_type=resource_type,
                resource_id=resource_id,
                organization_id=organization_id,
                start_time=start_time,
                end_time=end_time,
                limit=limit,
            )
        except ValueError:
            return 400, {
                "error": "start_time/end_time must be RFC 3339 timestamps"
            }
        return 200, {
            "entries": [_public_entry(row) for row in entries],
            "total_matched": total,
        }


class AuditHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, service):
        # type: (tuple, AuditService) -> None
        self.service = service
        ThreadingHTTPServer.__init__(self, address, _RequestHandler)


class _RequestHandler(BaseHTTPRequestHandler):
    server_version = "AgentTrustAudit/0.1"
    protocol_version = "HTTP/1.1"

    @property
    def service(self):
        # type: () -> AuditService
        return self.server.service

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        pass  # keep test output quiet

    def _send_json(self, status, body):
        # type: (int, dict) -> None
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(data)

    def _read_json_body(self):
        # type: () -> Tuple[bytes, Optional[dict], Optional[str]]
        """Read the request body ONCE, returning ``(raw, parsed, error)``.

        The raw bytes are returned alongside the parsed JSON because the
        request signature (U15) is computed over the exact body bytes, and
        ``rfile`` can only be consumed a single time.
        """
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return b"", None, "invalid Content-Length"
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return raw, {}, None
        try:
            body = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return raw, None, "request body is not valid JSON"
        if not isinstance(body, dict):
            return raw, None, "request body must be a JSON object"
        return raw, body, None

    def _segments(self):
        # type: () -> list
        parts = urlsplit(self.path)
        return [unquote(s) for s in parts.path.split("/") if s]

    def _authenticate(self, method, raw_body):
        # type: (str, bytes) -> Tuple[Optional[str], bool]
        """Authenticate the current request via the shared middleware (U15).

        Returns ``(principal_id, handled)``. When signatures are off this is
        a no-op returning ``(None, False)`` -- byte-for-byte the pre-U4
        (unauthenticated) audit service. On an AuthError the 401 response is
        sent here and ``handled`` is True, so callers just ``return`` when
        ``handled``.
        """
        principal_id, error = self.service.authenticator.authenticate(
            method, self.path, raw_body, self.headers
        )
        if error is not None:
            self._send_json(error.status, {"error": error.message})
            return None, True
        return principal_id, False

    def _bind_org_context(self):
        # type: () -> None
        """Bind this request's RLS org-context (U9) before any repository
        call runs, via an optional ``X-Organization-Id`` header (the audit
        HTTP contract carries no organization concept today, R10).
        Unconditional -- even when the header is absent -- so a keep-alive
        connection reusing this thread never inherits a prior request's
        value. ``audit.audit_log.organization_id`` IS RLS-protected as of
        this unit (migrations/0009_rls_policies.sql, NULL-permissive), so
        this is the one service where the binding actually changes what a
        query can see today, once a caller starts sending the header.
        """
        bind_organization_id(self.headers.get("X-Organization-Id"))

    def do_OPTIONS(self):
        # type: () -> None
        """Handle CORS preflight requests."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        self._bind_org_context()
        parts = urlsplit(self.path)
        segments = self._segments()

        if segments == ["healthz"]:
            self._send_json(200, {"status": "ok"})
            return

        if segments == ["audit"]:
            # Signature enforcement (U4): a no-op when the flag is OFF. When
            # ON, reading the trail requires the same authenticated identity
            # every mutating route does elsewhere in this codebase -- once
            # this is the sole canonical log, an unauthenticated reader
            # should not be able to browse it either.
            _principal, handled = self._authenticate("GET", b"")
            if handled:
                return

            query = parse_qs(parts.query)

            def param(name):
                return query.get(name, [None])[0]

            raw_limit = param("limit")
            limit = 100
            if raw_limit is not None:
                try:
                    limit = int(raw_limit)
                except ValueError:
                    self._send_json(
                        400, {"error": "'limit' must be an integer"}
                    )
                    return
                if limit < 1:
                    self._send_json(
                        400, {"error": "'limit' must be a positive integer"}
                    )
                    return
            status, body = self.service.query(
                principal_id=param("principal_id"),
                activity_type=param("activity_type"),
                resource_type=param("resource_type"),
                resource_id=param("resource_id"),
                organization_id=param("organization_id"),
                start_time=param("start_time"),
                end_time=param("end_time"),
                limit=limit,
            )
            self._send_json(status, body)
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        self._bind_org_context()
        segments = self._segments()
        raw, body, error = self._read_json_body()
        if error:
            self._send_json(400, {"error": error})
            return

        if segments == ["audit"]:
            # Signature enforcement (U4): see module docstring -- this is
            # the actual security fix. A no-op pass-through when the flag is
            # off.
            _principal, handled = self._authenticate("POST", raw)
            if handled:
                return
            status, response = self.service.log_activity(body)
            self._send_json(status, response)
        else:
            self._send_json(404, {"error": "not found"})

    def _reject_mutation(self):
        # type: () -> None
        """The audit log is append-only: PUT/DELETE on /audit* are 405.
        Rejected unconditionally (no auth check needed) -- there is no
        identity that could make a mutation succeed."""
        segments = self._segments()
        if segments and segments[0] == "audit":
            data = json.dumps(
                {"error": "audit log is append-only (immutable)"}
            ).encode("utf-8")
            self.send_response(405)
            self.send_header("Allow", "GET, POST, OPTIONS")
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self._send_json(404, {"error": "not found"})

    def do_PUT(self):
        # Drain any body so keep-alive connections stay in sync.
        self._read_json_body()
        self._reject_mutation()

    def do_DELETE(self):
        self._read_json_body()
        self._reject_mutation()


def make_server(port=8005, host="127.0.0.1", service=None, db=None,
                repository=None, registry_url=None, require_signatures=False,
                public_key_resolver=None):
    # type: (int, str, Optional[AuditService], Optional[Database], Optional[AuditRepository], Optional[str], bool, Optional[object]) -> AuditHTTPServer
    """Build the audit server; ``port=0`` picks a free port.

    ``db``/``repository`` (unit U4) let a caller point the audit service's
    Postgres-backed storage at a specific ``libs.db.Database`` /
    ``audit.repository.AuditRepository`` -- e.g. tests simulating a process
    restart. ``require_signatures`` opts the service into signed-request
    enforcement (U4/U15); off by default so existing unsigned callers are
    unaffected. ``registry_url``/``public_key_resolver`` resolve principal
    public keys the same way ``vault/app.py`` does -- tests inject a resolver
    so no live Registry is needed.
    """
    if service is None:
        service = AuditService(
            repository=repository,
            db=db,
            registry_url=registry_url,
            require_signatures=require_signatures,
            public_key_resolver=public_key_resolver,
        )
    return AuditHTTPServer((host, port), service)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="AgentTrust Central Audit & Compliance service"
    )
    parser.add_argument("--port", type=int, default=8005)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--registry-url",
        default=None,
        help="Registry URL used to resolve principal public keys when "
        "--require-signatures is set. Required for signature verification "
        "to succeed against real callers (tests may inject a resolver "
        "instead).",
    )
    parser.add_argument(
        "--require-signatures",
        action="store_true",
        help="Enforce signed requests (U4/U15) on both POST /audit and "
        "GET /audit: closes the gap where any caller could forge an entry "
        "under an arbitrary principal_id. Off by default "
        "(backward-compatible).",
    )
    args = parser.parse_args(argv)

    server = make_server(
        port=args.port, host=args.host, registry_url=args.registry_url,
        require_signatures=args.require_signatures,
    )
    print(
        "AgentTrust Audit service listening on http://%s:%d"
        % server.server_address[:2]
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()
