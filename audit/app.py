"""Central Audit & Compliance service (Phase B, unit U12).

An append-only, queryable log of all significant ecosystem activities.
Services (Registry, Vault, apps, Agent Marketplace) emit entries here as a
best-effort, fire-and-forget side channel via ``libs.audit_client``; the
audit service being down must never break a caller.

API endpoints:
- POST   /audit    - append an entry {principal_id, activity_type, status,
                     resource_id?, details?} -> {"entry": {...}} with a
                     server-assigned entry_id and RFC 3339 UTC timestamp.
                     422 when principal_id/activity_type/status are missing
                     or empty.
- GET    /audit    - query with any combination of principal_id,
                     activity_type, resource_id, start_time, end_time
                     (inclusive RFC 3339 bounds) and limit (default 100)
                     -> {"entries": [... newest first ...], "total_matched"}.
                     400 for an invalid limit or timestamp.
- PUT    /audit*   - 405 (the log is append-only; immutability is part of
- DELETE /audit*     the contract)
- GET    /healthz  - health check

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

from audit.audit_store import AuditStore

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


class AuditService:
    """Core audit logic; callable directly from tests (no HTTP)."""

    def __init__(self, store=None):
        # type: (Optional[AuditStore]) -> None
        self.store = store if store is not None else AuditStore()

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

        resource_id = payload.get("resource_id")
        if resource_id is not None and not isinstance(resource_id, str):
            return 422, {"error": "'resource_id' must be a string if provided"}

        details = payload.get("details")
        if details is not None and not isinstance(details, dict):
            return 422, {"error": "'details' must be an object if provided"}

        entry = {
            "principal_id": payload["principal_id"],
            "activity_type": payload["activity_type"],
            "status": payload["status"],
            "resource_id": resource_id,
            "details": details if details is not None else {},
        }
        return 200, {"entry": self.store.append(entry)}

    def query(self, principal_id=None, activity_type=None, resource_id=None,
              start_time=None, end_time=None, limit=100):
        # type: (Optional[str], Optional[str], Optional[str], Optional[str], Optional[str], int) -> Tuple[int, dict]
        """Filtered entries newest first plus the FULL match count."""
        try:
            matched = self.store.query_all(
                principal_id=principal_id,
                activity_type=activity_type,
                resource_id=resource_id,
                start_time=start_time,
                end_time=end_time,
            )
        except ValueError:
            return 400, {
                "error": "start_time/end_time must be RFC 3339 timestamps"
            }
        return 200, {
            "entries": matched[:limit],
            "total_matched": len(matched),
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
        # type: () -> Tuple[Optional[dict], Optional[str]]
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None, "invalid Content-Length"
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}, None
        try:
            body = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None, "request body is not valid JSON"
        if not isinstance(body, dict):
            return None, "request body must be a JSON object"
        return body, None

    def _segments(self):
        # type: () -> list
        parts = urlsplit(self.path)
        return [unquote(s) for s in parts.path.split("/") if s]

    def do_OPTIONS(self):
        # type: () -> None
        """Handle CORS preflight requests."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parts = urlsplit(self.path)
        segments = self._segments()

        if segments == ["healthz"]:
            self._send_json(200, {"status": "ok"})
        elif segments == ["audit"]:
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
                resource_id=param("resource_id"),
                start_time=param("start_time"),
                end_time=param("end_time"),
                limit=limit,
            )
            self._send_json(status, body)
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        segments = self._segments()
        body, error = self._read_json_body()
        if error:
            self._send_json(400, {"error": error})
            return

        if segments == ["audit"]:
            status, response = self.service.log_activity(body)
            self._send_json(status, response)
        else:
            self._send_json(404, {"error": "not found"})

    def _reject_mutation(self):
        # type: () -> None
        """The audit log is append-only: PUT/DELETE on /audit* are 405."""
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


def make_server(port=8005, host="127.0.0.1", service=None):
    # type: (int, str, Optional[AuditService]) -> AuditHTTPServer
    """Build the audit server; ``port=0`` picks a free port."""
    if service is None:
        service = AuditService()
    return AuditHTTPServer((host, port), service)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="AgentTrust Central Audit & Compliance service"
    )
    parser.add_argument("--port", type=int, default=8005)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args(argv)

    server = make_server(port=args.port, host=args.host)
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
