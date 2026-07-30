"""Postgres-backed storage for the Vault service (unit U3, ``vault`` schema
-- migrations/0003_vault.sql).

Pure ciphertext-in, ciphertext-out: every method here accepts and returns
exactly the wrapped/encrypted blobs ``vault/app.py`` already received or
built (base64 strings, JSON-safe KDF metadata) and never decrypts, wraps, or
otherwise touches key material. That keeps the zero-knowledge property (R4)
intact -- ``vault/crypto.py`` is not imported here and needs no changes at
all; only where these bytes live changed, not what they mean.

Principal-FK wrinkle
---------------------
``migrations/0003_vault.sql``'s DDL (verbatim from
``docs/architecture/database-design.md`` Section 8) has
``user_principal_id`` / ``agent_principal_id`` / ``granted_by`` as foreign
keys into ``identity.principals``. But ``vault/app.py`` has never required a
caller to register a principal before storing a keyring/credential/grant
against its principal_id -- it just accepts whatever string shows up in the
request body, and every existing ``tests/vault/*`` test exercises exactly
that (no separate "register this principal" call anywhere). R10 forbids
editing those pre-existing tests to add one.

This module resolves the conflict with :meth:`_ensure_principal`: every
write path that introduces a *new* principal_id into a vault table calls it
first. It is an idempotent "insert a minimal ``identity.principals`` row if
one doesn't already exist" step built on top of
``libs.identity_repository.IdentityRepository.register_principal`` (U2) --
reusing U2's repository rather than hand-rolling a second insert path. This
keeps the foreign key a real constraint (a stray typo'd principal_id still
cannot sneak into ``vault.credential_grants``) while asking nothing new of
any existing caller. The ``principal_type`` guess (``"user"`` for
``user_principal_id`` fields, ``"agent"`` for ``agent_principal_id``/
``granted_by``) is a best-effort default, not an authoritative identity
claim -- real principal registration (with a verified key, a real type) is
owned by whichever service actually onboards that principal; this is purely
"make the FK constraint satisfiable for a principal_id the vault has never
been told to expect in advance."

Uses ``libs.db.Database`` for every connection -- no hand-rolled psycopg
connection handling here (KTD1).
"""

import json
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from psycopg.rows import dict_row

from libs.db import Database
from libs.identity_repository import IdentityRepository
from libs.ulid import generate_ulid

_KEYRING_FIELDS = (
    "encrypted_dek", "salt", "nonce", "kdf", "kdf_params",
    "encrypted_private_key",
)
_ROTATION_FIELDS = ("encrypted_dek", "salt", "nonce", "kdf", "kdf_params")


class VaultRepository(object):
    """Repository for ``vault.*`` tables: keyrings, credentials, grants."""

    def __init__(self, db=None):
        # type: (Optional[Database]) -> None
        self._db = db or Database()
        # Composition, not inheritance: reuses U2's insert/lookup logic for
        # the "ensure principal exists" step instead of a second hand-rolled
        # INSERT INTO identity.principals path.
        self._identity = IdentityRepository(self._db)

    def _ensure_principal(self, principal_id, principal_type):
        # type: (str, str) -> None
        """Idempotently make sure ``principal_id`` exists in
        ``identity.principals`` so a vault-table foreign key referencing it
        can succeed. See the module docstring for why this exists at all.

        Checks existence first (the common case after the first call for any
        given principal_id) and only inserts on a miss; a concurrent insert
        losing the race is swallowed (``IdentityRepository.register_principal``
        raises ``ValueError`` on a duplicate) since the end state -- the row
        exists -- is exactly what was wanted either way.
        """
        if self._identity.principal_exists(principal_id):
            return
        try:
            self._identity.register_principal(principal_id, principal_type)
        except ValueError:
            pass  # lost a race with a concurrent ensure/registration -- fine

    # -- keyring -------------------------------------------------------------

    def store_keyring(self, user_principal_id, fields):
        # type: (str, dict) -> dict
        """Insert or replace (POST /keyring is upsert-by-owner, matching the
        prior in-memory ``self.keyrings[user_principal_id] = record``
        unconditional-overwrite behavior) the wrapped keyring for
        ``user_principal_id``. Returns the stored row."""
        self._ensure_principal(user_principal_id, "user")
        with self._db.transaction() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    INSERT INTO vault.keyrings
                        (user_principal_id, encrypted_dek, salt, nonce, kdf,
                         kdf_params, encrypted_private_key)
                    VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
                    ON CONFLICT (user_principal_id) DO UPDATE SET
                        encrypted_dek = excluded.encrypted_dek,
                        salt = excluded.salt,
                        nonce = excluded.nonce,
                        kdf = excluded.kdf,
                        kdf_params = excluded.kdf_params,
                        encrypted_private_key = excluded.encrypted_private_key,
                        updated_at = now()
                    RETURNING *
                    """,
                    (
                        user_principal_id,
                        fields["encrypted_dek"],
                        fields["salt"],
                        fields["nonce"],
                        fields["kdf"],
                        _dumps(fields["kdf_params"]),
                        fields["encrypted_private_key"],
                    ),
                )
                return _normalize(cur.fetchone())

    def get_keyring(self, user_principal_id):
        # type: (str) -> Optional[dict]
        """Fetch the wrapped keyring row, or ``None`` if unknown."""
        with self._db.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM vault.keyrings WHERE user_principal_id = %s",
                    (user_principal_id,),
                )
                return _normalize(cur.fetchone())

    def rotate_keyring(self, user_principal_id, fields):
        # type: (str, dict) -> Optional[dict]
        """Re-wrap the DEK: update the rotation fields (and
        ``encrypted_private_key`` if present in ``fields``); returns the
        updated row, or ``None`` if ``user_principal_id`` has no keyring."""
        set_clauses = [
            "encrypted_dek = %s", "salt = %s", "nonce = %s", "kdf = %s",
            "kdf_params = %s::jsonb", "updated_at = now()",
        ]
        params = [
            fields["encrypted_dek"], fields["salt"], fields["nonce"],
            fields["kdf"], _dumps(fields["kdf_params"]),
        ]
        if "encrypted_private_key" in fields:
            set_clauses.append("encrypted_private_key = %s")
            params.append(fields["encrypted_private_key"])
        params.append(user_principal_id)

        with self._db.transaction() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "UPDATE vault.keyrings SET %s WHERE user_principal_id = %%s "
                    "RETURNING *" % ", ".join(set_clauses),
                    params,
                )
                return _normalize(cur.fetchone())

    # -- credentials -----------------------------------------------------------

    def store_credential(self, user_principal_id, name, credential_type,
                         encrypted_data, nonce):
        # type: (str, str, str, str, str) -> dict
        """Insert a new encrypted credential owned by ``user_principal_id``.

        ``credential_id`` keeps the pre-existing ``uuid4`` string convention
        (``vault/app.py`` already minted ids this way; U3 does not change the
        id format callers might depend on) rather than switching to a ULID.
        """
        self._ensure_principal(user_principal_id, "user")
        credential_id = str(uuid.uuid4())
        with self._db.transaction() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    INSERT INTO vault.credentials
                        (credential_id, user_principal_id, name,
                         credential_type, encrypted_data, nonce)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        credential_id, user_principal_id, name,
                        credential_type, encrypted_data, nonce,
                    ),
                )
                return _normalize(cur.fetchone())

    def store_managed_oauth_credential(
        self, user_principal_id, provider, granted_scopes, envelope
    ):
        # type: (str, str, list, dict) -> dict
        """Persist a managed envelope without changing the legacy schema.

        The existing ``encrypted_data`` column already stores opaque
        ciphertext.  Managed custody stores a versioned JSON envelope there
        and marks the row with ``credential_type=managed_oauth``; legacy
        zero-knowledge rows retain their byte-for-byte representation.
        """
        payload = self._managed_oauth_payload(
            provider, granted_scopes, "active", envelope, credential_version=1
        )
        return self.store_credential(
            user_principal_id,
            provider,
            "managed_oauth",
            _dumps(payload),
            "managed_oauth:v1",
        )

    def get_credential(self, credential_id):
        # type: (str) -> Optional[dict]
        """Fetch a credential row (any owner), or ``None`` if unknown."""
        with self._db.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM vault.credentials WHERE credential_id = %s",
                    (credential_id,),
                )
                return _normalize(cur.fetchone())

    def get_managed_oauth_credential(self, credential_id):
        # type: (str) -> Optional[dict]
        record = self.get_credential(credential_id)
        if record is None or record.get("credential_type") != "managed_oauth":
            return None
        try:
            payload = json.loads(record["encrypted_data"])
        except (TypeError, ValueError):
            return None
        if (
            not isinstance(payload, dict)
            or payload.get("custody_mode") != "managed_oauth"
            or not isinstance(payload.get("envelope"), dict)
        ):
            return None
        result = dict(record)
        result.update(payload)
        return result

    def mark_managed_oauth_pending_revocation(
        self, credential_id, user_principal_id
    ):
        current = self.get_managed_oauth_credential(credential_id)
        if (
            current is None
            or current.get("user_principal_id") != user_principal_id
        ):
            return None
        payload = self._managed_oauth_payload(
            current["provider"],
            current.get("granted_scopes", []),
            "pending_revocation",
            current["envelope"],
            credential_version=current.get("credential_version", 1),
        )
        with self._db.transaction() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    UPDATE vault.credentials
                    SET encrypted_data = %s
                    WHERE credential_id = %s
                      AND user_principal_id = %s
                      AND credential_type = 'managed_oauth'
                    RETURNING *
                    """,
                    (_dumps(payload), credential_id, user_principal_id),
                )
                record = _normalize(cur.fetchone())
        if record is None:
            return None
        record.update(payload)
        return record

    def delete_managed_oauth_credential(
        self, credential_id, user_principal_id
    ):
        with self._db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM vault.credentials
                    WHERE credential_id = %s
                      AND user_principal_id = %s
                      AND credential_type = 'managed_oauth'
                    """,
                    (credential_id, user_principal_id),
                )
                return cur.rowcount == 1

    def update_managed_oauth_envelope(self, credential_id, envelope):
        # type: (str, dict) -> Optional[dict]
        current = self.get_managed_oauth_credential(credential_id)
        if current is None:
            return None
        payload = self._managed_oauth_payload(
            current["provider"],
            current.get("granted_scopes", []),
            current.get("status", "active"),
            envelope,
            credential_version=current.get("credential_version", 1),
        )
        with self._db.transaction() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    UPDATE vault.credentials
                    SET encrypted_data = %s
                    WHERE credential_id = %s
                      AND credential_type = 'managed_oauth'
                    RETURNING *
                    """,
                    (_dumps(payload), credential_id),
                )
                record = _normalize(cur.fetchone())
        if record is None:
            return None
        record.update(payload)
        return record

    def compare_and_swap_managed_oauth_envelope(
        self, credential_id, expected_version, envelope, granted_scopes
    ):
        with self._db.transaction() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT * FROM vault.credentials
                    WHERE credential_id = %s AND credential_type = 'managed_oauth'
                    FOR UPDATE
                    """,
                    (credential_id,),
                )
                record = _normalize(cur.fetchone())
                if record is None:
                    return None
                try:
                    current = json.loads(record["encrypted_data"])
                except (TypeError, ValueError):
                    return None
                if (
                    current.get("status") != "active"
                    or int(current.get("credential_version", 1)) != int(expected_version)
                ):
                    return None
                payload = self._managed_oauth_payload(
                    current["provider"],
                    granted_scopes,
                    "active",
                    envelope,
                    credential_version=int(expected_version) + 1,
                )
                cur.execute(
                    """
                    UPDATE vault.credentials SET encrypted_data = %s
                    WHERE credential_id = %s
                    RETURNING *
                    """,
                    (_dumps(payload), credential_id),
                )
                updated = _normalize(cur.fetchone())
        updated.update(payload)
        return updated

    @staticmethod
    def _managed_oauth_payload(
        provider, granted_scopes, status, envelope, credential_version=1
    ):
        return {
            "custody_mode": "managed_oauth",
            "provider": provider,
            "granted_scopes": sorted(set(granted_scopes)),
            "status": status,
            "credential_version": int(credential_version),
            "envelope": envelope,
        }

    def get_owned_credential(self, credential_id, user_principal_id):
        # type: (str, str) -> Optional[dict]
        """Fetch a credential row scoped to its owner: returns ``None`` both
        when the credential doesn't exist AND when it exists but belongs to
        a different ``user_principal_id`` -- the ownership check happens in
        the SQL ``WHERE`` clause itself (not by fetching the row and
        comparing in Python), so a caller using this method can never be
        handed another user's row by a slip in application-layer logic."""
        with self._db.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM vault.credentials "
                    "WHERE credential_id = %s AND user_principal_id = %s",
                    (credential_id, user_principal_id),
                )
                return _normalize(cur.fetchone())

    def list_credentials(self, user_principal_id):
        # type: (str) -> List[dict]
        """All credential rows owned by ``user_principal_id``, oldest first."""
        with self._db.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM vault.credentials "
                    "WHERE user_principal_id = %s ORDER BY created_at",
                    (user_principal_id,),
                )
                return [_normalize(row) for row in cur.fetchall()]

    # -- grants ------------------------------------------------------------

    def add_grant(self, credential_id, agent_principal_id, scope, granted_by):
        # type: (str, str, str, str) -> dict
        """Grant ``agent_principal_id`` ``scope`` access to ``credential_id``.

        A re-grant to an agent that already has an active grant on this
        credential first revokes the prior active grant, then inserts a
        fresh one -- mirroring the previous in-memory
        ``credential["grants"][agent_principal_id] = {...}`` unconditional
        overwrite (new ``grant_id`` each time), while leaving the superseded
        grant's history in the table instead of destroying it.
        """
        self._ensure_principal(agent_principal_id, "agent")
        self._ensure_principal(granted_by, "user")
        grant_id = generate_ulid()
        with self._db.transaction() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    UPDATE vault.credential_grants
                    SET revoked_at = now()
                    WHERE credential_id = %s AND agent_principal_id = %s
                      AND revoked_at IS NULL
                    """,
                    (credential_id, agent_principal_id),
                )
                cur.execute(
                    """
                    INSERT INTO vault.credential_grants
                        (grant_id, credential_id, agent_principal_id, scope,
                         granted_by)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (grant_id, credential_id, agent_principal_id, scope,
                     granted_by),
                )
                return _normalize(cur.fetchone())

    def get_active_grant(self, credential_id, agent_principal_id):
        # type: (str, str) -> Optional[dict]
        """The current active (unrevoked) grant for this
        (credential, agent) pair, or ``None``."""
        with self._db.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM vault.credential_grants "
                    "WHERE credential_id = %s AND agent_principal_id = %s "
                    "AND revoked_at IS NULL",
                    (credential_id, agent_principal_id),
                )
                return _normalize(cur.fetchone())

    def revoke_grant(self, credential_id, agent_principal_id):
        # type: (str, str) -> Optional[dict]
        """Revoke the active grant for this (credential, agent) pair;
        returns the now-revoked row, or ``None`` if there was no active
        grant to revoke."""
        with self._db.transaction() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    UPDATE vault.credential_grants
                    SET revoked_at = now()
                    WHERE credential_id = %s AND agent_principal_id = %s
                      AND revoked_at IS NULL
                    RETURNING *
                    """,
                    (credential_id, agent_principal_id),
                )
                return _normalize(cur.fetchone())


def _dumps(value):
    # type: (dict) -> str
    """JSON-encode a dict for a ``jsonb`` column parameter."""
    return json.dumps(value)


def _normalize(row):
    # type: (Optional[dict]) -> Optional[dict]
    """Convert a fetched row's ``timestamptz`` values (psycopg hands back
    timezone-aware ``datetime`` objects) to ISO-8601 strings, so repository
    return values are JSON-serializable exactly like the record dicts the
    prior in-memory implementation built by hand with
    ``datetime.utcnow().isoformat()``."""
    if row is None:
        return None
    return {
        key: (value.isoformat() if isinstance(value, datetime) else value)
        for key, value in row.items()
    }
