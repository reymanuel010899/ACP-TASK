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
- GET    /audit?principal_id=<id>                     - audit entries (proxied
                                                         to the central audit
                                                         service, see below)
- GET    /healthz                                     - health check

Audit (unit U4): the Vault's own local, in-memory audit log
(``vault/audit_log.py``) has been removed. Every audit-worthy action already
went through ``self.audit_client`` to the central Audit & Compliance service
(``audit/app.py``) as of U12/U3 -- that central emission is now the ONLY
audit trail (KTD3: two unsynchronized logs served no one). ``GET /audit``
therefore proxies to the central service instead of reading a local list,
and returns THAT service's entry shape directly: ``activity_type`` instead
of ``action``, ``resource_type``/``resource_id`` instead of
``credential_id``, and newest-first ordering instead of oldest-first. This
is a deliberate, documented R10 exception (see this unit's report) -- Vault
callers reading ``GET /audit`` must adapt to the new shape; this handler
does NOT transform the central response back into the old shape, since
doing so would silently keep the two-shapes problem this unit exists to
close.

Run: python -m vault.app [--port 8003]
"""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional, Tuple
from urllib.parse import parse_qs, unquote, urlsplit

from libs.audit_client import make_audit_client
from libs.db import Database, bind_organization_id
from libs.request_auth import RequestAuthenticator
from vault.crypto import UnsupportedKDFError, validate_kdf
from vault.managed_oauth_crypto import (
    ManagedOAuthAccessDenied,
    ManagedOAuthAuthError,
    validate_managed_oauth_envelope,
)
from vault.repository import VaultRepository

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
    """Core vault logic; persists wrapped blobs to Postgres (unit U3, the
    ``vault`` schema -- see ``vault/repository.py``). Storage is pure
    ciphertext-in/ciphertext-out; this service never decrypts anything and
    survives a process restart with every keyring, credential, and grant
    intact."""

    def __init__(self, audit_url=None, registry_url=None,
                 require_signatures=False, public_key_resolver=None,
                 db=None, repository=None, managed_oauth_crypto=None):
        # type: (Optional[str], Optional[str], bool, Optional[object], Optional[Database], Optional[VaultRepository], Optional[object]) -> None
        self.repository = repository or VaultRepository(db or Database())
        self.managed_oauth_crypto = managed_oauth_crypto
        # Central audit client (U12): best-effort, fire-and-forget emission
        # to the ecosystem-wide Audit & Compliance service. As of U4 this is
        # the vault's ONLY audit trail -- the local in-memory
        # ``vault/audit_log.py`` has been removed (KTD3): it was an
        # unsynchronized, incomplete duplicate of exactly this stream, not
        # an intentional fast-path/durable-path split. A NullAuditClient
        # (no-op) is used when no audit_url is configured, matching every
        # other rewired service.
        self.audit_client = make_audit_client(audit_url)
        # Shared request-authentication middleware (U15). A pure no-op
        # pass-through while ``require_signatures`` is off, so the default
        # deployment keeps today's behavior byte-for-byte. When on, every
        # mutating route authenticates and the verified signer is bound to the
        # credential owner/agent by the handlers below. Tests inject
        # ``public_key_resolver`` so no live Registry is needed.
        self.require_signatures = require_signatures
        self.authenticator = RequestAuthenticator(
            registry_url,
            require_signatures=require_signatures,
            public_key_resolver=public_key_resolver,
        )

    # -- keyring -----------------------------------------------------------

    def store_keyring(self, body, signer=None):
        # type: (dict, Optional[str]) -> Tuple[int, dict]
        user_principal_id = body.get("user_principal_id")
        if not isinstance(user_principal_id, str) or not user_principal_id:
            return 422, {"error": "missing or invalid 'user_principal_id'"}
        # Identity binding (only when authenticated, i.e. flag on): the signer
        # may only store a keyring under its OWN principal id.
        if signer is not None and signer != user_principal_id:
            return 403, {"error": "signer does not match keyring owner"}
        for field in _KEYRING_FIELDS:
            if field not in body:
                return 422, {"error": "missing '%s'" % field}
        try:
            validate_kdf(body["kdf"], body["kdf_params"])
        except UnsupportedKDFError as exc:
            return 422, {"error": str(exc)}

        fields = {field: body[field] for field in _KEYRING_FIELDS}
        record = self.repository.store_keyring(user_principal_id, fields)

        return 200, {
            "user_principal_id": record["user_principal_id"],
            "created_at": record["created_at"],
        }

    def get_keyring(self, user_principal_id):
        # type: (str) -> Tuple[int, dict]
        record = self.repository.get_keyring(user_principal_id)
        if record is None:
            return 404, {"error": "keyring not found"}
        return 200, dict(record)

    def rotate_keyring(self, user_principal_id, body, signer=None):
        # type: (str, dict, Optional[str]) -> Tuple[int, dict]
        """Re-wrap the DEK (password change / event-based rotation).

        Only the wrapping changes — stored credential ciphertexts are never
        re-encrypted because the DEK itself is unchanged.
        """
        # Identity binding (flag on): only the keyring owner may rotate it.
        if signer is not None and signer != user_principal_id:
            return 403, {"error": "signer does not match keyring owner"}
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

        fields = {field: body[field] for field in _ROTATION_FIELDS}
        if "encrypted_private_key" in body:
            fields["encrypted_private_key"] = body["encrypted_private_key"]
        record = self.repository.rotate_keyring(user_principal_id, fields)
        if record is None:
            return 404, {"error": "keyring not found"}

        self.audit_client.log(
            user_principal_id, "keyring.rotate",
            details={"reason": rotation_reason.strip()},
        )
        return 200, {
            "user_principal_id": user_principal_id,
            "updated_at": record["updated_at"],
        }

    # -- credentials -------------------------------------------------------

    def store_credential(self, body, signer=None):
        # type: (dict, Optional[str]) -> Tuple[int, dict]
        for field in _CREDENTIAL_FIELDS:
            value = body.get(field)
            if not isinstance(value, str) or not value:
                return 422, {"error": "missing or invalid '%s'" % field}

        # Identity binding (flag on): the signer may only store credentials
        # under its OWN principal id.
        if signer is not None and signer != body["user_principal_id"]:
            return 403, {"error": "signer does not match credential owner"}

        record = self.repository.store_credential(
            body["user_principal_id"], body["name"], body["credential_type"],
            body["encrypted_data"], body["nonce"],
        )

        return 200, {
            "credential_id": record["credential_id"],
            "created_at": record["created_at"],
        }

    def store_managed_oauth(self, body, signer=None):
        # type: (dict, Optional[str]) -> Tuple[int, dict]
        """Store an already-sealed managed OAuth envelope.

        OAuth ingestion performs KMS ``GenerateDataKey`` + token encryption
        before this boundary.  Consequently neither this method nor its HTTP
        response receives or returns plaintext token material.
        """
        user_principal_id = body.get("user_principal_id")
        provider = body.get("provider")
        granted_scopes = body.get("granted_scopes")
        envelope = body.get("envelope")
        if not isinstance(user_principal_id, str) or not user_principal_id:
            return 422, {"error": "missing or invalid 'user_principal_id'"}
        if signer is None:
            return 401, {
                "error": "authenticated OAuth ingestion identity is required"
            }
        if signer != user_principal_id:
            return 403, {"error": "signer does not match credential owner"}
        if not isinstance(provider, str) or not provider:
            return 422, {"error": "missing or invalid 'provider'"}
        if (
            not isinstance(granted_scopes, list)
            or any(not isinstance(scope, str) for scope in granted_scopes)
        ):
            return 422, {"error": "invalid 'granted_scopes'"}
        if not isinstance(envelope, dict):
            return 422, {"error": "missing or invalid 'envelope'"}
        try:
            validate_managed_oauth_envelope(envelope)
        except ManagedOAuthAuthError:
            return 422, {"error": "invalid managed OAuth envelope"}

        record = self.repository.store_managed_oauth_credential(
            user_principal_id, provider, granted_scopes, envelope
        )
        self.audit_client.log(
            user_principal_id,
            "credential.managed_oauth.store",
            resource_id=record["credential_id"],
            details={"provider": provider},
        )
        return 200, {
            "credential_id": record["credential_id"],
            "custody_mode": "managed_oauth",
            "provider": provider,
            "granted_scopes": sorted(set(granted_scopes)),
            "created_at": record["created_at"],
        }

    def use_managed_oauth(
        self, credential_id, service_identity, operation
    ):
        """Run ``operation(token_bytes)`` inside the broker boundary.

        There is intentionally no HTTP handler that returns the token.  The
        only usable API accepts a callback and returns that callback's filtered
        data/receipt.
        """
        if self.managed_oauth_crypto is None:
            raise ManagedOAuthAccessDenied(
                "managed OAuth decryption is not configured"
            )
        record = self.repository.get_managed_oauth_credential(credential_id)
        if record is None:
            raise KeyError("managed OAuth credential not found")
        if record.get("status", "active") != "active":
            raise PermissionError("managed OAuth credential is blocked")
        envelope = record["envelope"]
        token = self.managed_oauth_crypto.open(
            envelope,
            envelope["encryption_context"],
            caller_identity=service_identity,
        )
        try:
            result = operation(token)
        finally:
            del token
        self.audit_client.log(
            service_identity,
            "credential.managed_oauth.use",
            resource_id=credential_id,
            details={"provider": record["provider"]},
        )
        return result

    def read_rotation_document(self, credential_id, service_identity):
        if self.managed_oauth_crypto is None:
            raise ManagedOAuthAccessDenied("managed OAuth decryption is not configured")
        record = self.repository.get_managed_oauth_credential(credential_id)
        if record is None:
            raise KeyError("managed OAuth credential not found")
        envelope = record["envelope"]
        plaintext = self.managed_oauth_crypto.open(
            envelope,
            envelope["encryption_context"],
            caller_identity=service_identity,
        )
        try:
            document = json.loads(plaintext.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise ManagedOAuthAuthError("rotation document is invalid") from exc
        finally:
            del plaintext
        if not isinstance(document, dict):
            raise ManagedOAuthAuthError("rotation document is invalid")
        return (
            int(record.get("credential_version", 1)),
            record.get("status", "active"),
            document,
        )

    def compare_and_swap_rotation_document(
        self,
        credential_id,
        expected_version,
        document,
        service_identity,
    ):
        if self.managed_oauth_crypto is None:
            raise ManagedOAuthAccessDenied("managed OAuth encryption is not configured")
        current = self.repository.get_managed_oauth_credential(credential_id)
        if current is None or current.get("status") != "active":
            return False
        context = dict(current["envelope"]["encryption_context"])
        context["credential_version"] = str(int(expected_version) + 1)
        envelope = self.managed_oauth_crypto.seal_rotation_document(
            document, context, caller_identity=service_identity
        )
        updated = self.repository.compare_and_swap_managed_oauth_envelope(
            credential_id,
            expected_version,
            envelope,
            document.get("granted_scopes", current.get("granted_scopes", [])),
        )
        return updated is not None

    def begin_managed_oauth_revocation(
        self, credential_id, user_principal_id
    ):
        record = self.repository.get_managed_oauth_credential(credential_id)
        if record is None:
            return 404, {"error": "managed OAuth credential not found"}
        if record["user_principal_id"] != user_principal_id:
            return 403, {"error": "only the credential owner can disconnect"}
        pending = self.repository.mark_managed_oauth_pending_revocation(
            credential_id, user_principal_id
        )
        if pending is None:
            return 409, {"error": "could not block credential"}
        self.audit_client.log(
            user_principal_id,
            "credential.managed_oauth.pending_revocation",
            resource_id=credential_id,
            details={"provider": pending["provider"]},
        )
        return 200, {
            "credential_id": credential_id,
            "status": "pending_revocation",
        }

    def revoke_managed_oauth(
        self, credential_id, service_identity, operation
    ):
        if self.managed_oauth_crypto is None:
            raise ManagedOAuthAccessDenied(
                "managed OAuth decryption is not configured"
            )
        record = self.repository.get_managed_oauth_credential(credential_id)
        if record is None:
            raise KeyError("managed OAuth credential not found")
        if record.get("status") != "pending_revocation":
            raise PermissionError("credential is not pending revocation")
        envelope = record["envelope"]
        token = self.managed_oauth_crypto.open(
            envelope,
            envelope["encryption_context"],
            caller_identity=service_identity,
        )
        try:
            return operation(token)
        finally:
            del token

    def delete_managed_oauth_credential(
        self, credential_id, user_principal_id
    ):
        deleted = self.repository.delete_managed_oauth_credential(
            credential_id, user_principal_id
        )
        if not deleted:
            return 403
        self.audit_client.log(
            user_principal_id,
            "credential.managed_oauth.delete",
            resource_id=credential_id,
        )
        return 200

    def rewrap_managed_oauth(
        self, credential_id, destination_key_id, service_identity
    ):
        if self.managed_oauth_crypto is None:
            raise ManagedOAuthAccessDenied(
                "managed OAuth decryption is not configured"
            )
        record = self.repository.get_managed_oauth_credential(credential_id)
        if record is None:
            raise KeyError("managed OAuth credential not found")
        envelope = record["envelope"]
        updated = self.managed_oauth_crypto.rewrap(
            envelope,
            destination_key_id,
            envelope["encryption_context"],
            caller_identity=service_identity,
        )
        self.repository.update_managed_oauth_envelope(credential_id, updated)
        self.audit_client.log(
            service_identity,
            "credential.managed_oauth.rewrap",
            resource_id=credential_id,
            details={"provider": record["provider"],
                     "kms_key_id": updated["kms_key_id"]},
        )
        return {
            "credential_id": credential_id,
            "kms_key_id": updated["kms_key_id"],
            "kms_key_version": updated["kms_key_version"],
        }

    def list_credentials(self, user_principal_id):
        # type: (Optional[str]) -> Tuple[int, dict]
        if not user_principal_id:
            return 422, {"error": "missing 'user_principal_id' query param"}
        records = self.repository.list_credentials(user_principal_id)
        # Metadata only — never leak ciphertext or nonces in listings.
        credentials = [
            self._credential_metadata(c)
            for c in records
        ]
        return 200, {"credentials": credentials}

    @staticmethod
    def _credential_metadata(record):
        metadata = {
            "credential_id": record["credential_id"],
            "name": record["name"],
            "credential_type": record["credential_type"],
            "user_principal_id": record["user_principal_id"],
            "created_at": record["created_at"],
        }
        if record.get("credential_type") == "managed_oauth":
            try:
                payload = json.loads(record["encrypted_data"])
            except (TypeError, ValueError):
                payload = {}
            metadata.update(
                {
                    "custody_mode": "managed_oauth",
                    "provider": payload.get("provider"),
                    "granted_scopes": payload.get("granted_scopes", []),
                }
            )
        return metadata

    # -- grants + access ---------------------------------------------------

    def grant_access(self, credential_id, body, signer=None):
        # type: (str, dict, Optional[str]) -> Tuple[int, dict]
        agent_principal_id = body.get("agent_principal_id")
        scope = body.get("scope")
        granted_by = body.get("granted_by")
        if not isinstance(agent_principal_id, str) or not agent_principal_id:
            return 422, {"error": "missing or invalid 'agent_principal_id'"}
        if not isinstance(scope, str) or not scope:
            return 422, {"error": "missing or invalid 'scope'"}
        if not isinstance(granted_by, str) or not granted_by:
            return 422, {"error": "missing or invalid 'granted_by'"}

        # Identity binding (flag on): the signer must be the party it claims to
        # grant as; combined with the owner check below this means only the
        # owner, acting as themselves, can grant.
        if signer is not None and signer != granted_by:
            return 403, {"error": "signer does not match 'granted_by'"}

        credential = self.repository.get_credential(credential_id)
        if credential is None:
            return 404, {"error": "credential not found"}
        # Ownership check enforced at the repository layer (SQL WHERE
        # clause, not a Python dict-field comparison): get_owned_credential
        # returns None if credential_id belongs to anyone other than
        # granted_by, so a slip here can't leak a grant onto someone else's
        # credential even if this comparison were ever removed by mistake.
        if self.repository.get_owned_credential(
            credential_id, granted_by
        ) is None:
            return 403, {
                "error": "only the credential owner can grant access"
            }
        grant = self.repository.add_grant(
            credential_id, agent_principal_id, scope, granted_by
        )

        self.audit_client.log(
            granted_by, "credential.grant",
            resource_id=credential_id,
            details={"agent_principal_id": agent_principal_id,
                     "scope": scope},
        )
        return 200, {"grant_id": grant["grant_id"]}

    def request_access(self, credential_id, body, signer=None):
        # type: (str, dict, Optional[str]) -> Tuple[int, dict]
        agent_principal_id = body.get("agent_principal_id")
        if not isinstance(agent_principal_id, str) or not agent_principal_id:
            return 422, {"error": "missing or invalid 'agent_principal_id'"}

        # Identity binding (flag on): an agent may only request access AS
        # itself — it cannot fetch a credential granted to a different agent.
        if signer is not None and signer != agent_principal_id:
            return 403, {
                "access_granted": False,
                "error": "signer does not match 'agent_principal_id'",
            }

        credential = self.repository.get_credential(credential_id)
        if credential is None:
            return 404, {"error": "credential not found"}
        if credential.get("credential_type") == "managed_oauth":
            self.audit_client.log(
                agent_principal_id,
                "credential.access",
                resource_id=credential_id,
                status="denied",
                details={"custody_mode": "managed_oauth"},
            )
            return 403, {"access_granted": False}
        grant = self.repository.get_active_grant(
            credential_id, agent_principal_id
        )
        encrypted_data = credential["encrypted_data"]
        nonce = credential["nonce"]

        if grant is None:
            self.audit_client.log(
                agent_principal_id, "credential.access",
                resource_id=credential_id, status="denied",
            )
            return 403, {"access_granted": False}

        self.audit_client.log(
            agent_principal_id, "credential.access",
            resource_id=credential_id, status="granted",
            details={"scope": grant["scope"]},
        )
        return 200, {
            "access_granted": True,
            "encrypted_data": encrypted_data,
            "nonce": nonce,
            "scope": grant["scope"],
        }

    def revoke_access(self, credential_id, agent_principal_id, signer=None):
        # type: (str, str, Optional[str]) -> Tuple[int, dict]
        credential = self.repository.get_credential(credential_id)
        if credential is None:
            return 404, {"error": "credential not found"}
        # Identity binding (flag on): ONLY the credential owner may revoke.
        # This closes the historical asymmetry with grant_access — flag OFF
        # (signer is None) preserves the original permissive revoke.
        if signer is not None and signer != credential["user_principal_id"]:
            return 403, {
                "error": "only the credential owner can revoke access"
            }
        grant = self.repository.revoke_grant(credential_id, agent_principal_id)
        if grant is None:
            return 404, {"error": "grant not found"}
        self.audit_client.log(
            agent_principal_id, "credential.revoke",
            resource_id=credential_id,
            details={"granted_by": grant.get("granted_by")},
        )
        return 200, {
            "revoked": True,
            "credential_id": credential_id,
            "agent_principal_id": agent_principal_id,
        }

    # -- audit -------------------------------------------------------------

    def query_audit(self, principal_id):
        # type: (Optional[str]) -> Tuple[int, dict]
        """Proxy to the central Audit & Compliance service (unit U4) --
        there is no local audit list anymore (KTD3). Returns the CENTRAL
        store's entry shape directly (``activity_type``,
        ``resource_type``/``resource_id``, newest first) -- see the module
        docstring for why this handler deliberately does not translate that
        back into the old local shape.

        Without an ``audit_url`` configured, ``self.audit_client`` is a
        ``NullAuditClient`` and this always returns an empty result --
        there is nowhere to read from, matching that client's contract
        everywhere else in the codebase.
        """
        if not principal_id:
            return 422, {"error": "missing 'principal_id' query param"}
        try:
            body = self.audit_client.query(principal_id=principal_id)
        except Exception:
            # The central service is a real dependency for reads (unlike the
            # best-effort write path) but a caller of THIS vault endpoint
            # should still get a clean error, not a crashed connection.
            return 502, {"error": "central audit service unavailable"}
        return 200, body


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

    def _authenticate(self, raw_body):
        # type: (bytes) -> Tuple[Optional[str], bool]
        """Authenticate the current request via the shared middleware (U15).

        Returns ``(principal_id, handled)``. When signatures are off this is a
        no-op returning ``(None, False)`` — every downstream identity-binding
        check is skipped, so behavior is byte-for-byte the pre-U17 vault. On an
        AuthError the 401 response is sent here and ``handled`` is True.
        """
        principal_id, error = self.service.authenticator.authenticate(
            self.command, self.path, raw_body, self.headers
        )
        if error is not None:
            self._send_json(error.status, {"error": error.message})
            return None, True
        return principal_id, False

    def _bind_org_context(self):
        # type: () -> None
        """Bind this request's RLS org-context (U9) before any repository
        call runs, via an optional ``X-Organization-Id`` header (vault
        requests carry no organization concept in their existing body/query
        shape, R10). Unconditional -- even when the header is absent -- so a
        keep-alive connection reusing this thread never inherits a prior
        request's value.

        NOTE: ``vault.keyrings``/``vault.credentials``/``vault.
        credential_grants`` themselves have NO RLS policy as of this unit
        (see migrations/0009_rls_policies.sql's header -- no
        organization_id column exists, an open decision carried forward
        unchanged from U3's own report). This call is still made, for
        consistency with every other service and so the plumbing is already
        in place the day vault tables DO grow tenant scoping.
        """
        bind_organization_id(self.headers.get("X-Organization-Id"))

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
        self._bind_org_context()
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
        self._bind_org_context()
        parts = urlsplit(self.path)
        segments = [unquote(s) for s in parts.path.split("/") if s]
        raw, body, error = self._read_json_body()
        if error:
            self._send_json(400, {"error": error})
            return
        signer, handled = self._authenticate(raw)
        if handled:
            return

        if segments == ["keyring"]:
            # POST /keyring
            status, response = self.service.store_keyring(body, signer=signer)
            self._send_json(status, response)
        elif segments == ["credentials", "managed-oauth"]:
            # Ciphertext envelope ingestion only; plaintext tokens are never
            # accepted by or returned from this handler.
            status, response = self.service.store_managed_oauth(
                body, signer=signer
            )
            self._send_json(status, response)
        elif segments == ["credentials"]:
            # POST /credentials
            status, response = self.service.store_credential(
                body, signer=signer
            )
            self._send_json(status, response)
        elif (
            len(segments) == 3
            and segments[0] == "credentials"
            and segments[2] == "grants"
        ):
            # POST /credentials/{credential_id}/grants
            status, response = self.service.grant_access(
                segments[1], body, signer=signer
            )
            self._send_json(status, response)
        elif (
            len(segments) == 3
            and segments[0] == "credentials"
            and segments[2] == "access"
        ):
            # POST /credentials/{credential_id}/access
            status, response = self.service.request_access(
                segments[1], body, signer=signer
            )
            self._send_json(status, response)
        else:
            self._send_json(404, {"error": "not found"})

    def do_PUT(self):
        self._bind_org_context()
        parts = urlsplit(self.path)
        segments = [unquote(s) for s in parts.path.split("/") if s]
        raw, body, error = self._read_json_body()
        if error:
            self._send_json(400, {"error": error})
            return
        signer, handled = self._authenticate(raw)
        if handled:
            return

        if len(segments) == 2 and segments[0] == "keyring":
            # PUT /keyring/{user_principal_id}
            status, response = self.service.rotate_keyring(
                segments[1], body, signer=signer
            )
            self._send_json(status, response)
        else:
            self._send_json(404, {"error": "not found"})

    def do_DELETE(self):
        self._bind_org_context()
        parts = urlsplit(self.path)
        segments = [unquote(s) for s in parts.path.split("/") if s]
        signer, handled = self._authenticate(b"")
        if handled:
            return

        if (
            len(segments) == 4
            and segments[0] == "credentials"
            and segments[2] == "grants"
        ):
            # DELETE /credentials/{credential_id}/grants/{agent_principal_id}
            status, response = self.service.revoke_access(
                segments[1], segments[3], signer=signer
            )
            self._send_json(status, response)
        else:
            self._send_json(404, {"error": "not found"})


def make_server(port=8003, host="127.0.0.1", audit_url=None,
                registry_url=None, require_signatures=False,
                public_key_resolver=None, db=None, repository=None,
                managed_oauth_crypto=None):
    # type: (int, str, Optional[str], Optional[str], bool, Optional[object], Optional[Database], Optional[VaultRepository], Optional[object]) -> VaultHTTPServer
    """Build the vault server.

    ``require_signatures`` opts the vault into signed-request enforcement
    (U15/U17); when off (default) the vault behaves exactly as before. The
    optional ``public_key_resolver`` lets tests supply principal public keys
    without a live Registry. ``db``/``repository`` (unit U3) let a caller
    point the vault's Postgres-backed storage at a specific
    ``libs.db.Database``/``vault.repository.VaultRepository`` -- e.g. tests
    simulating a process restart by building two independent servers against
    the same underlying database. Both default to ``None``, which reads
    ``DATABASE_URL`` exactly like every other service (no change for
    existing callers).
    """
    service = VaultService(
        audit_url=audit_url,
        registry_url=registry_url,
        require_signatures=require_signatures,
        public_key_resolver=public_key_resolver,
        db=db,
        repository=repository,
        managed_oauth_crypto=managed_oauth_crypto,
    )
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
    parser.add_argument(
        "--audit-url",
        default=None,
        help="Base URL of the central Audit service (U12). Emission is "
        "best-effort: a down audit service is never fatal.",
    )
    parser.add_argument(
        "--require-signatures",
        action="store_true",
        help="Enforce signed requests (U15/U17): every mutating endpoint "
        "authenticates against the Registry and the verified signer is bound "
        "to the credential owner/agent. Off by default (backward-compatible). "
        "Requires --registry-url to resolve principal public keys.",
    )
    args = parser.parse_args(argv)

    server = make_server(
        port=args.port, host=args.host, audit_url=args.audit_url,
        registry_url=args.registry_url,
        require_signatures=args.require_signatures,
    )
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
