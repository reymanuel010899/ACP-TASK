"""HTTP service that exchanges signed identity proofs for opaque web sessions."""

import argparse
import hashlib
import json
import os
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from libs import signing
from services.session.repository import SessionRepository


COOKIE_NAME = "tessera_session"


def _proof_fingerprint(assertion):
    canonical = json.dumps(
        assertion, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def session_cookie_value(header):
    cookie = SimpleCookie()
    cookie.load(header or "")
    morsel = cookie.get(COOKIE_NAME)
    return morsel.value if morsel else None


def _session_cookie(value, max_age=None):
    parts = [
        "%s=%s" % (COOKIE_NAME, value),
        "Path=/",
        "Secure",
        "HttpOnly",
        "SameSite=Lax",
    ]
    if max_age is not None:
        parts.append("Max-Age=%d" % int(max_age))
    return "; ".join(parts)


class SessionRequestHandler(BaseHTTPRequestHandler):
    server_version = "TesseraSession/1.0"

    def _json_body(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, TypeError, json.JSONDecodeError):
            return None

    def _respond(self, status, body=None, headers=None):
        payload = (
            json.dumps(body, separators=(",", ":")).encode("utf-8")
            if body is not None else b""
        )
        self.send_response(status)
        if body is not None:
            self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if payload:
            self.wfile.write(payload)

    def _session_id(self):
        return session_cookie_value(self.headers.get("Cookie"))

    def _current(self):
        return self.server.repository.resolve(
            self._session_id(), self.server.clock()
        )

    def do_POST(self):
        if urlsplit(self.path).path != "/sessions":
            self._respond(404, {"error": "not found"})
            return
        body = self._json_body()
        assertion = body.get("assertion") if isinstance(body, dict) else None
        if not isinstance(assertion, dict):
            self._respond(400, {"error": "signed assertion is required"})
            return
        principal_id = assertion.get("principal_id")
        try:
            signing.verify_session_assertion(
                assertion, principal_id, now_ts=self.server.clock()
            )
            created = self.server.repository.create(
                principal_id,
                _proof_fingerprint(assertion),
                self.server.clock(),
                previous_session_id=self._session_id(),
            )
        except (signing.SigningError, ValueError, TypeError):
            self._respond(401, {"error": "invalid or consumed identity proof"})
            return
        self._respond(
            201,
            {
                "principal_id": created["principal_id"],
                "csrf_token": created["csrf_token"],
                "expires_at": created["expires_at"],
            },
            {"Set-Cookie": _session_cookie(created["session_id"])},
        )

    def do_GET(self):
        if urlsplit(self.path).path != "/sessions/current":
            self._respond(404, {"error": "not found"})
            return
        current = self._current()
        if current is None:
            self._respond(
                401,
                {"error": "authentication required"},
                {"Set-Cookie": _session_cookie("", max_age=0)},
            )
            return
        self._respond(200, current)

    def do_DELETE(self):
        if urlsplit(self.path).path != "/sessions/current":
            self._respond(404, {"error": "not found"})
            return
        session_id = self._session_id()
        current = self._current()
        if current is None:
            self._respond(401, {"error": "authentication required"})
            return
        if not self.server.repository.csrf_matches(
            session_id, self.headers.get("X-CSRF-Token")
        ):
            self._respond(403, {"error": "invalid CSRF token"})
            return
        self.server.repository.revoke(session_id, self.server.clock())
        self._respond(
            204, headers={"Set-Cookie": _session_cookie("", max_age=0)}
        )

    def log_message(self, _format, *_args):
        return


def make_server(host="127.0.0.1", port=8120, repository=None, clock=None):
    server = ThreadingHTTPServer((host, port), SessionRequestHandler)
    server.repository = repository or SessionRepository(
        os.environ.get("SESSION_DATABASE", "tessera-sessions.db"),
        idle_ttl_seconds=int(os.environ.get("SESSION_IDLE_TTL_SECONDS", "1800")),
        absolute_ttl_seconds=int(
            os.environ.get("SESSION_ABSOLUTE_TTL_SECONDS", "43200")
        ),
    )
    server.clock = clock or time.time
    return server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8120, type=int)
    args = parser.parse_args()
    make_server(args.host, args.port).serve_forever()


if __name__ == "__main__":
    main()
