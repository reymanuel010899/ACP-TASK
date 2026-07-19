"""Encrypted Credential Vault service (unit U7, Decision 8).

Zero-knowledge vault: stores only wrapped blobs. Users store encrypted
credentials AND their wrapped principal private key (so multi-device login
works); agents get scoped, revocable, audited access. All KEK derivation and
encryption happens client-side (see vault/crypto.py, libs/vault_client.py) —
this service never sees passwords, KEKs, plaintext DEKs, or plaintext data.

API endpoints:
- POST   /keyring                                     - store wrapped keyring
- GET    /keyring/{user_principal_id}                 - fetch wrapped keyring
- PUT    /keyring/{user_principal_id}                 - re-wrap DEK (rotation)
- POST   /credentials                                 - store encrypted credential
- GET    /credentials?user_principal_id=<id>          - list metadata (no ciphertext)
- POST   /credentials/{credential_id}/grants          - grant agent access
- POST   /credentials/{credential_id}/access          - agent access request
- DELETE /credentials/{credential_id}/grants/{agent}  - revoke grant
- GET    /audit?principal_id=<id>                     - audit entries
- GET    /healthz                                     - health check

Run: python -m vault.app [--port 8003]
"""

import argparse
import json
import threading
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlsplit

from vault.audit_log import AuditLog
from vault.crypto import UnsupportedKDFError, validate_kdf

_KEYRING_FIELDS = (
    "encrypted_dek", "salt", "nonce", "kdf", "kdf_params",
    "encrypted_private_key",
)
_ROTATION_FIELDS = (
    "encrypted_dek", "salt", "nonce", "kdf", "kdf_params",
)
_CREDENTIAL_FIELDS = (
    "name", "credential_type", "encrypted_data", "nonce",
    "user_principal_id",
)


class VaultService:
    """Core vault logic; in-memory storage of wrapped blobs only."""

    def __init__(self):
        # type: () -> None
        self.keyrings = {}  # type: Dict[str, dict]
        self.credentials = {}  # type: Dict[str, dict]
        self.audit = AuditLog()
        self.lock = threading.Lock()

    # -- keyring -----------------------------------------------------------

    def store_keyring(self, body):
        # type: (dict) -> Tuple[int, dict]
        user_principal_id = body.get("user_principal_id")
        if not isinstance(user_principal_id, str) or not user_principal_id:
            return 422, {"error": "missing or invalid 'user_principal_id'"}
        for field in _KEYRING_FIELDS:
            if field not in body:
                return 422, {"error": "missing '%s'" % field}
        try:
            validate_kdf(body["kdf"], body["kdf_params"])
        except UnsupportedKDFError as exc:
            return 422, {"error": str(exc)}

        created_at = datetime.utcnow().isoformat()
        record = {field: body[field] for field in _KEYRING_FIELDS}
        record["user_principal_id"] = user_principal_id
        record["created_at"] = created_at
        record["updated_at"] = created_at

        with self.lock:
            self.keyrings[user_principal_id] = record

        return 200, {
            "user_principal_id": user_principal_id,
            "created_at": created_at,
        }

    def get_keyring(self, user_principal_id):
        # type: (str) -> Tuple[int, dict]
        with self.lock:
            record = self.keyrings.get(user_principal_id)
        if record is None:
            return 404, {"error": "keyring not found"}
        return 200, dict(record)

    def rotate_keyring(self, user_principal_id, body):
        # type: (str, dict) -> Tuple[int, dict]
        """Re-wrap the DEK (password change / event-based rotation).

        Only the wrapping changes — stored credential ciphertexts are never
        re-encrypted because the DEK itself is unchanged.
        """
        for field in _ROTATION_FIELDS:
            if field not in body:
                return 422, {"error": "missing '%s'" % field}
        rotation_reason = body.get("rotation_reason")
        if not isinstance(rotation_reason, str) or not rotation_reason.strip():
            return 422, {"error": "missing or invalid 'rotation_reason'"}
        try:
            validate_kdf(body["kdf"], body["kdf_params"])
        except UnsupportedKDFError as exc:
            return 422, {"error": str(exc)}

        with self.lock:
            record = self.keyrings.get(user_principal_id)
            if record is None:
                return 404, {"error": "keyring not found"}
            for field in _ROTATION_FIELDS:
                record[field] = body[field]
            if "encrypted_private_key" in body:
                record["encrypted_private_key"] = body[
                    "encrypted_private_key"
                ]
            record["updated_at"] = datetime.utcnow().isoformat()

        self.audit.append(
            principal_id=user_principal_id,
            action="keyring_rotated",
            status="ok",
            reason=rotation_reason.strip(),
        )
        return 200, {
            "user_principal_id": user_principal_id,
            "updated_at": record["updated_at"],
        }

    # -- credentials -------------------------------------------------------

    def store_credential(self, body):
        # type: (dict) -> Tuple[int, dict]
        for field in _CREDENTIAL_FIELDS:
            value = body.get(field)
            if not isinstance(value, str) or not value:
                return 422, {"error": "missing or invalid '%s'" % field}

        credential_id = str(uuid.uuid4())
        created_at = datetime.utcnow().isoformat()
        record = {
            "credential_id": credential_id,
            "name": body["name"],
            "credential_type": body["credential_type"],
            "encrypted_data": body["encrypted_data"],
            "nonce": body["nonce"],
            "user_principal_id": body["user_principal_id"],
            "created_at": created_at,
            "grants": {},  # agent_principal_id -> grant record
        }
        with self.lock:
            self.credentials[credential_id] = record

        return 200, {
            "credential_id": credential_id,
            "created_at": created_at,
        }

    def list_credentials(self, user_principal_id):
        # type: (Optional[str]) -> Tuple[int, dict]
        if not user_principal_id:
            return 422, {"error": "missing 'user_principal_id' query param"}
        with self.lock:
            records = [
                c for c in self.credentials.values()
                if c["user_principal_id"] == user_principal_id
            ]
        records.sort(key=lambda c: c["created_at"])
        # Metadata only — never leak ciphertext or nonces in listings.
        credentials = [
            {
                "credential_id": c["credential_id"],
                "name": c["name"],
                "credential_type": c["credential_type"],
                "user_principal_id": c["user_principal_id"],
                "created_at": c["created_at"],
            }
            for c in records
        ]
        return 200, {"credentials": credentials}

    # -- grants + access ---------------------------------------------------

    def grant_access(self, credential_id, body):
        # type: (str, dict) -> Tuple[int, dict]
        agent_principal_id = body.get("agent_principal_id")
        scope = body.get("scope")
        granted_by = body.get("granted_by")
        if not isinstance(agent_principal_id, str) or not agent_principal_id:
            return 422, {"error": "missing or invalid 'agent_principal_id'"}
        if not isinstance(scope, str) or not scope:
            return 422, {"error": "missing or invalid 'scope'"}
        if not isinstance(granted_by, str) or not granted_by:
            return 422, {"error": "missing or invalid 'granted_by'"}

        with self.lock:
            credential = self.credentials.get(credential_id)
            if credential is None:
                return 404, {"error": "credential not found"}
            if credential["user_principal_id"] != granted_by:
                return 403, {
                    "error": "only the credential owner can grant access"
                }
            grant_id = str(uuid.uuid4())
            credential["grants"][agent_principal_id] = {
                "grant_id": grant_id,
                "agent_principal_id": agent_principal_id,
                "scope": scope,
                "granted_by": granted_by,
                "granted_at": datetime.utcnow().isoformat(),
            }

        return 200, {"grant_id": grant_id}

    def request_access(self, credential_id, body):
        # type: (str, dict) -> Tuple[int, dict]
        agent_principal_id = body.get("agent_principal_id")
        if not isinstance(agent_principal_id, str) or not agent_principal_id:
            return 422, {"error": "missing or invalid 'agent_principal_id'"}

        with self.lock:
            credential = self.credentials.get(credential_id)
            if credential is None:
                return 404, {"error": "credential not found"}
            grant = credential["grants"].get(agent_principal_id)
            encrypted_data = credential["encrypted_data"]
            nonce = credential["nonce"]

        if grant is None:
            self.audit.append(
                principal_id=agent_principal_id,
                credential_id=credential_id,
                action="access",
                status="denied",
            )
            return 403, {"access_granted": False}

        self.audit.append(
            principal_id=agent_principal_id,
            credential_id=credential_id,
            action="access",
            status="granted",
        )
        return 200, {
            "access_granted": True,
            "encrypted_data": encrypted_data,
            "nonce": nonce,
            "scope": grant["scope"],
        }

    def revoke_access(self, credential_id, agent_principal_id):
        # type: (str, str) -> Tuple[int, dict]
        with self.lock:
            credential = self.credentials.get(credential_id)
            if credential is None:
                return 404, {"error": "credential not found"}
            grant = credential["grants"].pop(agent_principal_id, None)
        if grant is None:
            return 404, {"error": "grant not found"}
        return 200, {
            "revoked": True,
            "credential_id": credential_id,
            "agent_principal_id": agent_principal_id,
        }

    # -- audit -------------------------------------------------------------

    def query_audit(self, principal_id):
        # type: (Optional[str]) -> Tuple[int, dict]
        if not principal_id:
            return 422, {"error": "missing 'principal_id' query param"}
        return 200, {"entries": self.audit.query(principal_id)}


class VaultHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, service):
        # type: (tuple, VaultService) -> None
        self.service = service
        ThreadingHTTPServer.__init__(self, address, _RequestHandler)


class _RequestHandler(BaseHTTPRequestHandler):
    server_version = "AgentTrustVault/0.1"
    protocol_version = "HTTP/1.1"

    @property
    def service(self):
        # type: () -> VaultService
        return self.server.service

    def log_message(self, format, *args):  # noqa: A002
        pass  # Keep test output quiet

    def _send_json(self, status, body):
        # type: (int, dict) -> None
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header(
            "Access-Control-Allow-Methods",
            "GET, POST, PUT, DELETE, OPTIONS",
        )
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

    def do_OPTIONS(self):
        # type: () -> None
        """Handle CORS preflight requests."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header(
            "Access-Control-Allow-Methods",
            "GET, POST, PUT, DELETE, OPTIONS",
        )
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parts = urlsplit(self.path)
        segments = [unquote(s) for s in parts.path.split("/") if s]
        query = parse_qs(parts.query)

        if segments == ["healthz"]:
            self._send_json(200, {"status": "ok"})
        elif len(segments) == 2 and segments[0] == "keyring":
            # GET /keyring/{user_principal_id}
            status, body = self.service.get_keyring(segments[1])
            self._send_json(status, body)
        elif segments == ["credentials"]:
            # GET /credentials?user_principal_id=<id>
            user_principal_id = query.get("user_principal_id", [None])[0]
            status, body = self.service.list_credentials(user_principal_id)
            self._send_json(status, body)
        elif segments == ["audit"]:
            # GET /audit?principal_id=<id>
            principal_id = query.get("principal_id", [None])[0]
            status, body = self.service.query_audit(principal_id)
            self._send_json(status, body)
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        parts = urlsplit(self.path)
        segments = [unquote(s) for s in parts.path.split("/") if s]
        body, error = self._read_json_body()
        if error:
            self._send_json(400, {"error": error})
            return

        if segments == ["keyring"]:
            # POST /keyring
            status, response = self.service.store_keyring(body)
            self._send_json(status, response)
        elif segments == ["credentials"]:
            # POST /credentials
            status, response = self.service.store_credential(body)
            self._send_json(status, response)
        elif (
            len(segments) == 3
            and segments[0] == "credentials"
            and segments[2] == "grants"
        ):
            # POST /credentials/{credential_id}/grants
            status, response = self.service.grant_access(segments[1], body)
            self._send_json(status, response)
        elif (
            len(segments) == 3
            and segments[0] == "credentials"
            and segments[2] == "access"
        ):
            # POST /credentials/{credential_id}/access
            status, response = self.service.request_access(segments[1], body)
            self._send_json(status, response)
        else:
            self._send_json(404, {"error": "not found"})

    def do_PUT(self):
        parts = urlsplit(self.path)
        segments = [unquote(s) for s in parts.path.split("/") if s]
        body, error = self._read_json_body()
        if error:
            self._send_json(400, {"error": error})
            return

        if len(segments) == 2 and segments[0] == "keyring":
            # PUT /keyring/{user_principal_id}
            status, response = self.service.rotate_keyring(segments[1], body)
            self._send_json(status, response)
        else:
            self._send_json(404, {"error": "not found"})

    def do_DELETE(self):
        parts = urlsplit(self.path)
        segments = [unquote(s) for s in parts.path.split("/") if s]

        if (
            len(segments) == 4
            and segments[0] == "credentials"
            and segments[2] == "grants"
        ):
            # DELETE /credentials/{credential_id}/grants/{agent_principal_id}
            status, response = self.service.revoke_access(
                segments[1], segments[3]
            )
            self._send_json(status, response)
        else:
            self._send_json(404, {"error": "not found"})


def make_server(port=8003, host="127.0.0.1"):
    # type: (int, str) -> VaultHTTPServer
    """Build the vault server."""
    service = VaultService()
    return VaultHTTPServer((host, port), service)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="AgentTrust Encrypted Credential Vault"
    )
    parser.add_argument("--port", type=int, default=8003)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--registry-url",
        default=None,
        help="Registry URL; if set, the vault registers itself as a "
        "credential_vault service at startup (U9, RFC-0004). Non-fatal "
        "if the registry is down.",
    )
    args = parser.parse_args(argv)

    server = make_server(port=args.port, host=args.host)
    host, port = server.server_address[:2]
    print("AgentTrust Vault listening on http://%s:%d" % (host, port))
    if args.registry_url:
        # Service registration (U9): the vault is a shared service, not an
        # app with capabilities — it registers with capabilities=[] and the
        # credential_vault flag so apps can find it via GET /services.
        from libs.federation_client import FederationClient, FederationError

        vault_endpoint = "http://%s:%d" % (host, port)
        try:
            FederationClient(args.registry_url).register_app(
                "vault", vault_endpoint, vault_endpoint, [],
                credential_vault=True,
            )
            print("(registered as credential_vault service with registry)")
        except FederationError:
            print("(warning: could not register vault with registry)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()
