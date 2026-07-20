"""Client for the AgentTrust Encrypted Credential Vault (unit U7).

The Vault is zero-knowledge: all PBKDF2 derivation and envelope encryption
happens here on the client (via vault/crypto.py). Only wrapped blobs and
ciphertexts ever travel over the wire.
"""

import json
from typing import Optional, Tuple

import requests

from vault import crypto


class VaultClient:
    """HTTP client for the Vault service, plus client-side envelope helpers.

    When constructed with a ``session`` (a :class:`libs.session.SessionContext`)
    every request is signed automatically with the ``X-AT-*`` headers the Vault
    verifies under ``require_signatures``. Without a session the client behaves
    EXACTLY as before — no headers, byte-for-byte the pre-U20 requests — so it
    keeps working against unsigned Vaults during a gradual migration.
    """

    def __init__(self, base_url, timeout=5.0, session=None):
        # type: (str, float, Optional[object]) -> None
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session

    # -- raw HTTP helpers --------------------------------------------------

    def _request(self, method, path, json_body=None, params=None):
        # type: (str, str, Optional[dict], Optional[dict]) -> dict
        resp = self._send(method, path, json_body=json_body, params=params)
        resp.raise_for_status()
        return resp.json()

    def _send(self, method, path, json_body=None, params=None):
        # type: (str, str, Optional[dict], Optional[dict]) -> requests.Response
        """Issue one HTTP request, signing it when a session is configured.

        The signed body bytes are the EXACT bytes placed on the wire (``data=``
        of the serialized JSON), so the Vault reconstructs identical canonical
        bytes. Signatures cover the path only; the gated (mutating) routes carry
        no query string.
        """
        if self.session is None:
            return requests.request(
                method,
                self.base_url + path,
                json=json_body,
                params=params,
                timeout=self.timeout,
            )
        body_bytes = (
            json.dumps(json_body).encode("utf-8")
            if json_body is not None else b""
        )
        headers = self.session.auth_headers(method, path, body_bytes)
        headers["Content-Type"] = "application/json"
        return requests.request(
            method,
            self.base_url + path,
            data=body_bytes,
            params=params,
            headers=headers,
            timeout=self.timeout,
        )

    # -- keyring endpoints -------------------------------------------------

    def store_keyring(self, user_principal_id, blob):
        # type: (str, dict) -> dict
        """POST /keyring — store a wrapped keyring blob."""
        body = dict(blob)
        body["user_principal_id"] = user_principal_id
        return self._request("POST", "/keyring", json_body=body)

    def fetch_keyring(self, user_principal_id):
        # type: (str) -> dict
        """GET /keyring/{id} — fetch the wrapped keyring (any device)."""
        return self._request("GET", "/keyring/%s" % user_principal_id)

    def rotate_keyring(self, user_principal_id, blob, rotation_reason):
        # type: (str, dict, str) -> dict
        """PUT /keyring/{id} — replace the DEK wrapping (rotation)."""
        body = dict(blob)
        body["rotation_reason"] = rotation_reason
        return self._request(
            "PUT", "/keyring/%s" % user_principal_id, json_body=body
        )

    # -- credential endpoints ----------------------------------------------

    def store_credential(self, user_principal_id, name, credential_type,
                         encrypted_data, nonce):
        # type: (str, str, str, bytes, bytes) -> dict
        """POST /credentials — store a DEK-encrypted credential."""
        return self._request(
            "POST",
            "/credentials",
            json_body={
                "name": name,
                "credential_type": credential_type,
                "encrypted_data": crypto.b64encode(encrypted_data),
                "nonce": crypto.b64encode(nonce),
                "user_principal_id": user_principal_id,
            },
        )

    def list_credentials(self, user_principal_id):
        # type: (str) -> list
        """GET /credentials — metadata-only listing for a user."""
        body = self._request(
            "GET",
            "/credentials",
            params={"user_principal_id": user_principal_id},
        )
        return body["credentials"]

    def grant_access(self, credential_id, agent_principal_id, scope,
                     granted_by):
        # type: (str, str, str, str) -> dict
        """POST /credentials/{id}/grants — owner grants an agent access."""
        return self._request(
            "POST",
            "/credentials/%s/grants" % credential_id,
            json_body={
                "agent_principal_id": agent_principal_id,
                "scope": scope,
                "granted_by": granted_by,
            },
        )

    def request_access(self, credential_id, agent_principal_id):
        # type: (str, str) -> dict
        """POST /credentials/{id}/access — agent requests the ciphertext.

        Does not raise on denial: a 403 returns the response body
        (access_granted: False) augmented with 'status_code' so callers can
        branch on the outcome.
        """
        resp = self._send(
            "POST",
            "/credentials/%s/access" % credential_id,
            json_body={"agent_principal_id": agent_principal_id},
        )
        if resp.status_code not in (200, 403):
            resp.raise_for_status()
        body = resp.json()
        body["status_code"] = resp.status_code
        return body

    def revoke_access(self, credential_id, agent_principal_id):
        # type: (str, str) -> dict
        """DELETE /credentials/{id}/grants/{agent} — revoke a grant."""
        return self._request(
            "DELETE",
            "/credentials/%s/grants/%s"
            % (credential_id, agent_principal_id),
        )

    def get_audit(self, principal_id):
        # type: (str) -> list
        """GET /audit — audit entries for a principal, oldest first."""
        body = self._request(
            "GET", "/audit", params={"principal_id": principal_id}
        )
        return body["entries"]

    # -- client-side envelope helpers (PBKDF2 + wrapping happen HERE) ------

    def register_user_keyring(self, password, user_principal_id, private_key,
                              iterations=crypto.DEFAULT_ITERATIONS):
        # type: (str, str, bytes, int) -> Tuple[bytes, dict]
        """Create and store a new wrapped keyring for a user.

        Derives the KEK from the password, generates a fresh DEK, wraps it,
        encrypts the principal private key under the DEK, and uploads only
        the wrapped blob. Returns (dek, server_response); keep the DEK in
        memory only.
        """
        blob, dek = crypto.build_keyring_blob(
            password, private_key, iterations=iterations
        )
        resp = self.store_keyring(user_principal_id, blob)
        return dek, resp

    def unlock_keyring(self, password, blob):
        # type: (str, dict) -> Tuple[bytes, bytes]
        """Unlock a fetched keyring blob locally.

        Returns (dek, private_key). Raises crypto.VaultAuthError on a wrong
        password — authenticated encryption guarantees no partial data.
        """
        return crypto.unlock_keyring_blob(password, blob)

    def change_password(self, user_principal_id, old_password, new_password,
                        rotation_reason="password change",
                        iterations=crypto.DEFAULT_ITERATIONS):
        # type: (str, str, str, str, int) -> dict
        """Full password-change flow: fetch, unlock, re-wrap, upload.

        The DEK is unchanged, so stored credential ciphertexts (and the
        encrypted private key) are never re-encrypted.
        """
        blob = self.fetch_keyring(user_principal_id)
        dek, _private_key = crypto.unlock_keyring_blob(old_password, blob)
        new_blob = crypto.rewrap_keyring_blob(
            dek,
            new_password,
            blob["encrypted_private_key"],
            iterations=iterations,
        )
        return self.rotate_keyring(
            user_principal_id, new_blob, rotation_reason
        )
