"""Persistence for one-use OAuth transactions and provider authority.

``OAuthRepository`` is the characterized SQLite implementation retained for
imports and contract tests. ``PostgresOAuthRepository`` is the shared runtime
authority used by horizontally scaled services.
"""

import base64
import hashlib
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone

import nacl.exceptions
import nacl.secret
import nacl.utils

from libs.db import current_organization_id
from services.integrations.repository import (
    IntegrationConnectionConflict,
    IntegrationConnectionRepository,
    ProviderControlPlaneRepository,
)


class ConnectionConflict(Exception):
    """A provider installation is already owned by another tenant."""


class PkceCipher(object):
    """Authenticated encryption for short-lived OAuth PKCE verifiers."""

    def __init__(self, key):
        if isinstance(key, str):
            try:
                key = base64.urlsafe_b64decode(key.encode("ascii"))
            except (ValueError, TypeError) as exc:
                raise ValueError("PKCE encryption key must be base64") from exc
        if len(key) != nacl.secret.SecretBox.KEY_SIZE:
            raise ValueError("PKCE encryption key must decode to 32 bytes")
        self._box = nacl.secret.SecretBox(key)

    def encrypt(self, value):
        nonce = nacl.utils.random(nacl.secret.SecretBox.NONCE_SIZE)
        encrypted = self._box.encrypt(value.encode("utf-8"), nonce)
        return base64.urlsafe_b64encode(bytes(encrypted)).decode("ascii")

    def decrypt(self, value):
        try:
            encrypted = base64.urlsafe_b64decode(value.encode("ascii"))
            return self._box.decrypt(encrypted).decode("utf-8")
        except (ValueError, TypeError, nacl.exceptions.CryptoError) as exc:
            raise ValueError("PKCE verifier ciphertext is invalid") from exc


class OAuthRepository(object):
    TRANSACTION_TTL_SECONDS = 600

    def __init__(self, database_path):
        self._connection = sqlite3.connect(
            database_path, check_same_thread=False, isolation_level=None
        )
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS oauth_transactions (
                transaction_id TEXT PRIMARY KEY,
                session_hash TEXT NOT NULL,
                principal_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                requested_scopes TEXT NOT NULL,
                requested_capabilities TEXT NOT NULL,
                state_hash TEXT NOT NULL UNIQUE,
                pkce_verifier TEXT NOT NULL,
                return_to TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                consumed_at INTEGER
            );
            CREATE INDEX IF NOT EXISTS oauth_transactions_expiry_idx
                ON oauth_transactions(expires_at);

            CREATE TABLE IF NOT EXISTS oauth_connections (
                principal_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                credential_id TEXT NOT NULL,
                granted_scopes TEXT NOT NULL,
                enabled_capabilities TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'connected',
                updated_at INTEGER NOT NULL,
                PRIMARY KEY (principal_id, provider)
            );

            CREATE TABLE IF NOT EXISTS integration_connections (
                connection_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                principal_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                app_id TEXT NOT NULL,
                team_id TEXT,
                team_name TEXT,
                enterprise_id TEXT,
                bot_user_id TEXT,
                credential_id TEXT,
                credential_version INTEGER NOT NULL DEFAULT 1,
                granted_scopes TEXT NOT NULL,
                enabled_capabilities TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'connected',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                disconnected_at INTEGER
            );
            CREATE UNIQUE INDEX IF NOT EXISTS integration_slack_installation_uq
                ON integration_connections(provider, app_id, team_id)
                WHERE provider = 'slack' AND team_id IS NOT NULL;
            CREATE UNIQUE INDEX IF NOT EXISTS integration_google_owner_uq
                ON integration_connections(tenant_id, principal_id, provider, app_id)
                WHERE provider = 'google';
            CREATE INDEX IF NOT EXISTS integration_connections_owner_idx
                ON integration_connections(tenant_id, principal_id, provider, status);

            CREATE TABLE IF NOT EXISTS slack_authority_profiles (
                authority_profile_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                connection_id TEXT NOT NULL,
                profile_kind TEXT NOT NULL,
                slack_subject_id TEXT,
                consent_owner_principal_id TEXT NOT NULL,
                credential_id TEXT NOT NULL,
                credential_version INTEGER NOT NULL,
                granted_scopes TEXT NOT NULL,
                status TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                revoked_at INTEGER,
                PRIMARY KEY(authority_profile_id, tenant_id),
                UNIQUE(tenant_id, connection_id, profile_kind,
                       consent_owner_principal_id)
            );
            CREATE TABLE IF NOT EXISTS slack_authority_delegations (
                delegation_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                authority_profile_id TEXT NOT NULL,
                audience_principal_id TEXT NOT NULL,
                operation_family TEXT NOT NULL,
                purpose TEXT NOT NULL,
                granted_by_principal_id TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                revoked_at INTEGER,
                PRIMARY KEY(delegation_id, tenant_id),
                UNIQUE(tenant_id, authority_profile_id, audience_principal_id,
                       operation_family)
            );

            CREATE TABLE IF NOT EXISTS integration_connection_legacy_map (
                legacy_key TEXT PRIMARY KEY,
                connection_id TEXT UNIQUE,
                migration_status TEXT NOT NULL,
                source_checksum TEXT NOT NULL,
                error_code TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );

            -- The account-wide emergency stop. One row per tenant, so a stop
            -- is a durable fact about that account rather than a property of
            -- whichever process happened to read an environment variable at
            -- boot. Every dispatch path reads this; none of them restart.
            CREATE TABLE IF NOT EXISTS integration_control_plane (
                tenant_id TEXT PRIMARY KEY,
                stopped INTEGER NOT NULL DEFAULT 0,
                stop_reason TEXT,
                stopped_at INTEGER,
                stopped_by_principal_id TEXT,
                resumed_at INTEGER,
                resumed_by_principal_id TEXT,
                updated_at INTEGER NOT NULL
            );

            -- Capability families, per tenant, independently switchable. The
            -- tenant is the primary key's first column so one account's
            -- administrator can never name another account's row.
            CREATE TABLE IF NOT EXISTS integration_capability_families (
                tenant_id TEXT NOT NULL,
                family TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL,
                updated_by_principal_id TEXT,
                PRIMARY KEY(tenant_id, family)
            );

            -- Sending identities, per tenant. Disabling one is the narrowest
            -- authority change the control plane supports.
            CREATE TABLE IF NOT EXISTS integration_control_plane_senders (
                tenant_id TEXT NOT NULL,
                sender_id TEXT NOT NULL,
                family TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL,
                updated_by_principal_id TEXT,
                PRIMARY KEY(tenant_id, sender_id)
            );
            """
        )
        self._connection.execute("""CREATE TABLE IF NOT EXISTS voice_transfer_routes (
            tenant_id TEXT NOT NULL, route_id TEXT NOT NULL, department TEXT NOT NULL,
            language TEXT NOT NULL, destination TEXT NOT NULL, timezone TEXT NOT NULL,
            start_hour INTEGER NOT NULL, end_hour INTEGER NOT NULL, ring_seconds INTEGER NOT NULL,
            total_budget_seconds INTEGER NOT NULL, priority INTEGER NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY(tenant_id, route_id))""")
        self._ensure_connection_column(
            "status", "TEXT NOT NULL DEFAULT 'connected'"
        )
        self._ensure_connection_column("team_name", "TEXT")
        for name, declaration in (
            ("tenant_id", "TEXT"),
            ("app_id", "TEXT"),
            ("intended_team_id", "TEXT"),
            ("target_connection_id", "TEXT"),
        ):
            self._ensure_transaction_column(name, declaration)

    def replace_voice_routes(self, tenant_id, routes):
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                self._connection.execute("DELETE FROM voice_transfer_routes WHERE tenant_id=?", (tenant_id,))
                for route in routes:
                    self._connection.execute(
                        "INSERT INTO voice_transfer_routes VALUES(?,?,?,?,?,?,?,?,?,?,?,1)",
                        (tenant_id, route["route_id"], route["department"], route["language"],
                         route["destination"], route["timezone"], route["start_hour"], route["end_hour"],
                         route["ring_seconds"], route["total_budget_seconds"], route["priority"]),
                    )
                self._connection.execute("COMMIT")
            except Exception:
                if self._connection.in_transaction: self._connection.execute("ROLLBACK")
                raise

    def voice_routes(self, tenant_id):
        rows = self._connection.execute(
            "SELECT route_id,department,language,destination,timezone,start_hour,end_hour,ring_seconds,total_budget_seconds,priority "
            "FROM voice_transfer_routes WHERE tenant_id=? AND enabled=1 ORDER BY priority,route_id", (tenant_id,)
        ).fetchall()
        keys = ("route_id", "department", "language", "destination", "timezone", "start_hour",
                "end_hour", "ring_seconds", "total_budget_seconds", "priority")
        return [dict(zip(keys, tuple(row))) for row in rows]

    @staticmethod
    def hash_value(value):
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def create_transaction(
        self,
        transaction_id,
        session_id,
        principal_id,
        provider,
        requested_scopes,
        requested_capabilities,
        state,
        pkce_verifier,
        return_to,
        now_ts,
        tenant_id=None,
        app_id=None,
        intended_team_id=None,
        target_connection_id=None,
    ):
        now = int(now_ts)
        with self._lock:
            self._connection.execute(
                "DELETE FROM oauth_transactions WHERE expires_at < ?",
                (now,),
            )
            self._connection.execute(
                """
                INSERT INTO oauth_transactions(
                    transaction_id, session_hash, principal_id, provider,
                    requested_scopes, requested_capabilities, state_hash,
                    pkce_verifier, return_to, created_at, expires_at,
                    consumed_at, tenant_id, app_id, intended_team_id,
                    target_connection_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)
                """,
                (
                    transaction_id,
                    self.hash_value(session_id),
                    principal_id,
                    provider,
                    _dumps(requested_scopes),
                    _dumps(requested_capabilities),
                    self.hash_value(state),
                    pkce_verifier,
                    return_to,
                    now,
                    now + self.TRANSACTION_TTL_SECONDS,
                    tenant_id,
                    app_id,
                    intended_team_id,
                    target_connection_id,
                ),
            )
        return self.find_by_state(state, now)

    def find_by_state(self, state, now_ts=None):
        if not state:
            return None
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM oauth_transactions WHERE state_hash = ?",
                (self.hash_value(state),),
            ).fetchone()
        return _transaction(row)

    def consume_transaction(
        self, state, session_id, principal_id, now_ts
    ):
        """Atomically validate and consume one transaction.

        Every predicate participates in the guarded update. Concurrent
        callbacks therefore have a single winner; all others observe no row.
        """
        if not state or not session_id or not principal_id:
            return None
        now = int(now_ts)
        state_hash = self.hash_value(state)
        session_hash = self.hash_value(session_id)
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                cursor = self._connection.execute(
                    """
                    UPDATE oauth_transactions
                    SET consumed_at = ?
                    WHERE state_hash = ?
                      AND session_hash = ?
                      AND principal_id = ?
                      AND consumed_at IS NULL
                      AND expires_at >= ?
                    RETURNING *
                    """,
                    (
                        now,
                        state_hash,
                        session_hash,
                        principal_id,
                        now,
                    ),
                )
                row = cursor.fetchone()
                if row is not None:
                    self._connection.execute(
                        """
                        UPDATE oauth_transactions
                        SET pkce_verifier = ''
                        WHERE transaction_id = ?
                        """,
                        (row["transaction_id"],),
                    )
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
        return _transaction(row)

    def upsert_connection(
        self,
        principal_id,
        provider,
        credential_id,
        granted_scopes,
        enabled_capabilities,
        now_ts,
    ):
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO oauth_connections(
                    principal_id, provider, credential_id, granted_scopes,
                    enabled_capabilities, status, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'connected', ?)
                ON CONFLICT(principal_id, provider) DO UPDATE SET
                    credential_id = excluded.credential_id,
                    granted_scopes = excluded.granted_scopes,
                    enabled_capabilities = excluded.enabled_capabilities,
                    status = 'connected',
                    updated_at = excluded.updated_at
                """,
                (
                    principal_id,
                    provider,
                    credential_id,
                    _dumps(granted_scopes),
                    _dumps(enabled_capabilities),
                    int(now_ts),
                ),
            )
        return self.get_connection(principal_id, provider)

    def upsert_installation(
        self,
        tenant_id,
        principal_id,
        provider,
        app_id,
        credential_id,
        granted_scopes,
        enabled_capabilities,
        now_ts,
        connection_id=None,
        team_id=None,
        team_name=None,
        enterprise_id=None,
        bot_user_id=None,
        credential_version=1,
    ):
        """Create or refresh a tenant-bound provider installation.

        Provider installation identity is immutable.  Slack uniqueness is
        global to ``app_id + team_id`` so a concurrent callback cannot attach
        the same workspace authority to a second Tessera tenant.
        """
        if not tenant_id:
            raise ValueError("tenant_id is required")
        if not principal_id or not provider or not app_id:
            raise ValueError("principal_id, provider and app_id are required")
        if provider == "slack" and not team_id:
            raise ValueError("team_id is required for Slack installations")
        now = int(now_ts)
        resolved_id = connection_id or _stable_connection_id(
            provider, app_id, team_id, principal_id
        )
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                existing = self._connection.execute(
                    """
                    SELECT connection_id, tenant_id, principal_id
                    FROM integration_connections
                    WHERE connection_id = ?
                       OR (provider = 'slack' AND provider = ? AND app_id = ? AND team_id = ?)
                    """,
                    (resolved_id, provider, app_id, team_id),
                ).fetchone()
                if existing is not None and existing["tenant_id"] != tenant_id:
                    raise ConnectionConflict(
                        "provider installation belongs to another tenant"
                    )
                if existing is not None:
                    resolved_id = existing["connection_id"]
                self._connection.execute(
                    """
                    INSERT INTO integration_connections(
                        connection_id, tenant_id, principal_id, provider, app_id,
                        team_id, team_name, enterprise_id, bot_user_id, credential_id,
                        credential_version, granted_scopes, enabled_capabilities,
                        status, created_at, updated_at, disconnected_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'connected', ?, ?, NULL)
                    ON CONFLICT(connection_id) DO UPDATE SET
                        principal_id = excluded.principal_id,
                        team_name = excluded.team_name,
                        credential_id = excluded.credential_id,
                        credential_version = excluded.credential_version,
                        granted_scopes = excluded.granted_scopes,
                        enabled_capabilities = excluded.enabled_capabilities,
                        enterprise_id = excluded.enterprise_id,
                        bot_user_id = excluded.bot_user_id,
                        status = 'connected',
                        updated_at = excluded.updated_at,
                        disconnected_at = NULL
                    """,
                    (
                        resolved_id,
                        tenant_id,
                        principal_id,
                        provider,
                        app_id,
                        team_id,
                        team_name,
                        enterprise_id,
                        bot_user_id,
                        credential_id,
                        int(credential_version),
                        _dumps(granted_scopes),
                        _dumps(enabled_capabilities),
                        now,
                        now,
                    ),
                )
                self._connection.execute("COMMIT")
            except sqlite3.IntegrityError as exc:
                self._connection.execute("ROLLBACK")
                raise ConnectionConflict(
                    "provider installation is already connected"
                ) from exc
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
        return self.get_installation(resolved_id, tenant_id)

    PROFILE_KINDS = frozenset({"bot", "user", "enterprise_admin"})

    def record_authority_profile(
        self, tenant_id, connection_id, profile_kind, consent_owner_principal_id,
        credential_id, granted_scopes, now_ts, slack_subject_id=None,
        credential_version=1, enabled=False,
    ):
        """Persist one authority grant, bound to the identity it acts as."""
        if profile_kind not in self.PROFILE_KINDS:
            raise ValueError("unsupported authority profile kind")
        if profile_kind != "bot" and not slack_subject_id:
            raise ValueError("a personal authority profile needs its subject")
        if not all((tenant_id, connection_id, consent_owner_principal_id,
                    credential_id)):
            raise ValueError("authority profile binding is required")
        profile_id = "authority:%s" % uuid.uuid4().hex
        now_ts = int(now_ts)
        with self._lock:
            self._connection.execute(
                """INSERT INTO slack_authority_profiles(
                       authority_profile_id, tenant_id, connection_id,
                       profile_kind, slack_subject_id,
                       consent_owner_principal_id, credential_id,
                       credential_version, granted_scopes, status, enabled,
                       created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
                   ON CONFLICT(tenant_id, connection_id, profile_kind,
                               consent_owner_principal_id)
                   DO UPDATE SET slack_subject_id = excluded.slack_subject_id,
                       credential_id = excluded.credential_id,
                       credential_version = excluded.credential_version,
                       granted_scopes = excluded.granted_scopes,
                       status = 'active', revoked_at = NULL,
                       updated_at = excluded.updated_at""",
                (
                    profile_id, tenant_id, connection_id, profile_kind,
                    slack_subject_id, consent_owner_principal_id, credential_id,
                    int(credential_version),
                    json.dumps(sorted(set(granted_scopes or ()))),
                    1 if enabled else 0, now_ts, now_ts,
                ),
            )
        return self.get_authority_profile(
            tenant_id, connection_id, profile_kind, consent_owner_principal_id
        )

    def list_personal_authority(self, tenant_id, connection_id, principal_id):
        """What this person has granted of their own, so they can withdraw it.

        Only their own grants: another member's personal consent is not this
        person's business, and showing it would leak who searches what.
        """
        with self._lock:
            rows = self._connection.execute(
                """SELECT * FROM slack_authority_profiles
                   WHERE tenant_id = ? AND connection_id = ?
                     AND consent_owner_principal_id = ?
                     AND profile_kind != 'bot' AND status = 'active'
                   ORDER BY profile_kind""",
                (tenant_id, connection_id, principal_id),
            ).fetchall()
        return [self._authority_profile(row) for row in rows]

    def revoke_authority_profile(self, tenant_id, connection_id, profile_kind,
                                 principal_id, now_ts):
        """Withdraw one's own consent. Only the consent owner may."""
        with self._lock:
            cursor = self._connection.execute(
                """UPDATE slack_authority_profiles
                   SET status = 'revoked', enabled = 0, revoked_at = ?,
                       updated_at = ?
                   WHERE tenant_id = ? AND connection_id = ?
                     AND profile_kind = ? AND consent_owner_principal_id = ?
                     AND status = 'active'""",
                (int(now_ts), int(now_ts), tenant_id, connection_id,
                 profile_kind, principal_id),
            )
        return cursor.rowcount == 1

    def set_authority_profile_enabled(self, tenant_id, connection_id,
                                      profile_kind, principal_id, enabled,
                                      now_ts):
        """Turn one's own granted authority on or off without re-consenting."""
        with self._lock:
            cursor = self._connection.execute(
                """UPDATE slack_authority_profiles
                   SET enabled = ?, updated_at = ?
                   WHERE tenant_id = ? AND connection_id = ?
                     AND profile_kind = ? AND consent_owner_principal_id = ?
                     AND status = 'active'""",
                (1 if enabled else 0, int(now_ts), tenant_id, connection_id,
                 profile_kind, principal_id),
            )
        return cursor.rowcount == 1

    def get_authority_profile(self, tenant_id, connection_id, profile_kind,
                              consent_owner_principal_id):
        with self._lock:
            row = self._connection.execute(
                """SELECT * FROM slack_authority_profiles
                   WHERE tenant_id = ? AND connection_id = ?
                     AND profile_kind = ? AND consent_owner_principal_id = ?""",
                (tenant_id, connection_id, profile_kind,
                 consent_owner_principal_id),
            ).fetchone()
        return self._authority_profile(row) if row else None

    def authorize_personal_authority(
        self, tenant_id, connection_id, profile_kind, requester_principal_id,
        operation_family, now_ts, consent_owner_principal_id=None,
    ):
        """Decide whether this requester may act through a personal profile.

        Personal authority belongs to its subject, not to the tenant. Sharing
        a connection is not sharing a person's token, so a requester who is
        not the consent owner needs a delegation naming them, the family, and
        an expiry. Everything unproven denies.
        """
        owner = consent_owner_principal_id or requester_principal_id
        profile = self.get_authority_profile(
            tenant_id, connection_id, profile_kind, owner
        )
        if profile is None:
            return {"allowed": False, "reason": "authority_profile_absent"}
        if profile["status"] != "active":
            return {"allowed": False, "reason": "authority_profile_%s"
                    % profile["status"]}
        if not profile["enabled"]:
            return {"allowed": False, "reason": "authority_profile_disabled"}
        if profile_kind == "bot":
            return {"allowed": True, "reason": "tenant_bot_authority",
                    "authority_profile_id": profile["authority_profile_id"]}
        if profile["consent_owner_principal_id"] == requester_principal_id:
            return {"allowed": True, "reason": "requester_is_subject",
                    "authority_profile_id": profile["authority_profile_id"]}
        delegation = self._live_delegation(
            tenant_id, profile["authority_profile_id"], requester_principal_id,
            operation_family, int(now_ts),
        )
        if delegation is None:
            return {"allowed": False, "reason": "delegation_absent"}
        return {
            "allowed": True, "reason": "delegated",
            "authority_profile_id": profile["authority_profile_id"],
            "delegation_id": delegation["delegation_id"],
        }

    def grant_authority_delegation(
        self, tenant_id, authority_profile_id, audience_principal_id,
        operation_family, purpose, granted_by_principal_id, expires_at, now_ts,
    ):
        if not purpose or not operation_family:
            raise ValueError("a delegation needs a purpose and a family")
        if int(expires_at) <= int(now_ts):
            raise ValueError("a delegation must expire in the future")
        delegation_id = "delegation:%s" % uuid.uuid4().hex
        with self._lock:
            self._connection.execute(
                """INSERT INTO slack_authority_delegations(
                       delegation_id, tenant_id, authority_profile_id,
                       audience_principal_id, operation_family, purpose,
                       granted_by_principal_id, expires_at, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(tenant_id, authority_profile_id,
                               audience_principal_id, operation_family)
                   DO UPDATE SET purpose = excluded.purpose,
                       granted_by_principal_id = excluded.granted_by_principal_id,
                       expires_at = excluded.expires_at, revoked_at = NULL""",
                (delegation_id, tenant_id, authority_profile_id,
                 audience_principal_id, operation_family, purpose,
                 granted_by_principal_id, int(expires_at), int(now_ts)),
            )
        return delegation_id

    def _live_delegation(self, tenant_id, authority_profile_id,
                         audience_principal_id, operation_family, now_ts):
        with self._lock:
            row = self._connection.execute(
                """SELECT * FROM slack_authority_delegations
                   WHERE tenant_id = ? AND authority_profile_id = ?
                     AND audience_principal_id = ? AND operation_family = ?
                     AND revoked_at IS NULL AND expires_at > ?""",
                (tenant_id, authority_profile_id, audience_principal_id,
                 operation_family, now_ts),
            ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _authority_profile(row):
        profile = dict(row)
        profile["granted_scopes"] = json.loads(profile["granted_scopes"] or "[]")
        profile["enabled"] = bool(profile["enabled"])
        return profile

    def get_installation(self, connection_id, tenant_id):
        if not tenant_id:
            return None
        with self._lock:
            row = self._connection.execute(
                """
                SELECT * FROM integration_connections
                WHERE connection_id = ? AND tenant_id = ?
                """,
                (connection_id, tenant_id),
            ).fetchone()
        return _installation(row)

    def list_installations(self, tenant_id, principal_id, provider=None):
        if not tenant_id or not principal_id:
            return []
        sql = """
            SELECT * FROM integration_connections
            WHERE tenant_id = ? AND principal_id = ?
        """
        params = [tenant_id, principal_id]
        if provider:
            sql += " AND provider = ?"
            params.append(provider)
        sql += " ORDER BY provider, COALESCE(team_id, ''), connection_id"
        with self._lock:
            rows = self._connection.execute(sql, params).fetchall()
        return [_installation(row) for row in rows]

    def list_tenant_installations(self, tenant_id, provider=None, usable_only=True):
        """List execution authority shared with verified tenant members.

        Lifecycle mutations remain owner-scoped through ``principal_id`` in
        callers; this projection is only for selecting a usable installation.
        """
        if not tenant_id:
            return []
        sql = "SELECT * FROM integration_connections WHERE tenant_id = ?"
        params = [tenant_id]
        if provider:
            sql += " AND provider = ?"
            params.append(provider)
        if usable_only:
            sql += " AND status = 'connected'"
        sql += " ORDER BY provider, COALESCE(team_id, ''), connection_id"
        with self._lock:
            rows = self._connection.execute(sql, params).fetchall()
        return [_installation(row) for row in rows]

    def tombstone_installation(self, connection_id, tenant_id, now_ts):
        with self._lock:
            cursor = self._connection.execute(
                """
                UPDATE integration_connections
                SET status = 'disconnected', credential_id = NULL,
                    granted_scopes = '[]', enabled_capabilities = '[]',
                    disconnected_at = ?, updated_at = ?
                WHERE connection_id = ? AND tenant_id = ?
                """,
                (int(now_ts), int(now_ts), connection_id, tenant_id),
            )
        return cursor.rowcount == 1

    def mark_installation_status(
        self, connection_id, tenant_id, status, now_ts, expected_status=None
    ):
        allowed = {
            "connected", "degraded", "refreshing", "rotation_uncertain",
            "disconnect_pending", "disconnected", "migration_blocked",
        }
        if status not in allowed:
            raise ValueError("unsupported connection status")
        sql = """
            UPDATE integration_connections
            SET status = ?, updated_at = ?
            WHERE connection_id = ? AND tenant_id = ?
        """
        params = [status, int(now_ts), connection_id, tenant_id]
        if expected_status:
            sql += " AND status = ?"
            params.append(expected_status)
        with self._lock:
            cursor = self._connection.execute(sql, params)
        return cursor.rowcount == 1

    def control_plane_state(self, tenant_id):
        """Every switch this tenant's administrators hold, in one read.

        The dispatch paths ask this on every tick, so it is deliberately one
        round trip and deliberately tenant-scoped: there is no argument that
        would widen it past the caller's own account.
        """
        if not tenant_id:
            raise ValueError("tenant_id is required")
        with self._lock:
            stop = self._connection.execute(
                "SELECT stopped, stop_reason, stopped_at, "
                "stopped_by_principal_id FROM integration_control_plane "
                "WHERE tenant_id = ?",
                (tenant_id,),
            ).fetchone()
            families = self._connection.execute(
                "SELECT family, enabled FROM integration_capability_families "
                "WHERE tenant_id = ? ORDER BY family",
                (tenant_id,),
            ).fetchall()
            senders = self._connection.execute(
                "SELECT sender_id, enabled "
                "FROM integration_control_plane_senders "
                "WHERE tenant_id = ? ORDER BY sender_id",
                (tenant_id,),
            ).fetchall()
        return {
            "tenant_id": tenant_id,
            "emergency_stop": bool(stop["stopped"]) if stop else False,
            "stop_reason": stop["stop_reason"] if stop else None,
            "stopped_at": stop["stopped_at"] if stop else None,
            "stopped_by_principal_id": (
                stop["stopped_by_principal_id"] if stop else None
            ),
            "families": {
                row["family"]: bool(row["enabled"]) for row in families
            },
            "senders": {
                row["sender_id"]: bool(row["enabled"]) for row in senders
            },
        }

    def set_emergency_stop(
        self, tenant_id, active, now_ts, reason=None, acting_principal_id=None,
    ):
        """Stop or resume one account, and record who did it and why.

        The row is kept after a resume rather than deleted: "this account was
        stopped for two hours last Tuesday" is the kind of thing an operator
        needs to be able to answer afterwards.
        """
        if not tenant_id:
            raise ValueError("tenant_id is required")
        active = bool(active)
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO integration_control_plane(
                    tenant_id, stopped, stop_reason, stopped_at,
                    stopped_by_principal_id, resumed_at,
                    resumed_by_principal_id, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id) DO UPDATE SET
                    stopped = excluded.stopped,
                    stop_reason = excluded.stop_reason,
                    stopped_at = CASE WHEN excluded.stopped = 1
                        THEN excluded.stopped_at ELSE stopped_at END,
                    stopped_by_principal_id = CASE WHEN excluded.stopped = 1
                        THEN excluded.stopped_by_principal_id
                        ELSE stopped_by_principal_id END,
                    resumed_at = CASE WHEN excluded.stopped = 0
                        THEN excluded.updated_at ELSE resumed_at END,
                    resumed_by_principal_id = CASE WHEN excluded.stopped = 0
                        THEN excluded.stopped_by_principal_id
                        ELSE resumed_by_principal_id END,
                    updated_at = excluded.updated_at
                """,
                (
                    tenant_id, 1 if active else 0,
                    reason if active else None,
                    int(now_ts) if active else None,
                    acting_principal_id,
                    None if active else int(now_ts),
                    None if active else acting_principal_id,
                    int(now_ts),
                ),
            )
        return self.control_plane_state(tenant_id)

    def set_capability_family_enabled(
        self, tenant_id, family, enabled, now_ts, acting_principal_id=None,
    ):
        """Switch one family for one tenant, touching nothing else.

        Upsert rather than update: a family with no row is off, so the first
        time an administrator enables one there is nothing to update yet.
        """
        if not tenant_id:
            raise ValueError("tenant_id is required")
        if not family:
            raise ValueError("family is required")
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO integration_capability_families(
                    tenant_id, family, enabled, updated_at,
                    updated_by_principal_id
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, family) DO UPDATE SET
                    enabled = excluded.enabled,
                    updated_at = excluded.updated_at,
                    updated_by_principal_id = excluded.updated_by_principal_id
                """,
                (
                    tenant_id, family, 1 if enabled else 0, int(now_ts),
                    acting_principal_id,
                ),
            )
        return self.control_plane_state(tenant_id)

    def set_control_plane_sender_enabled(
        self, tenant_id, sender_id, enabled, now_ts, family="",
        acting_principal_id=None,
    ):
        if not tenant_id:
            raise ValueError("tenant_id is required")
        if not sender_id:
            raise ValueError("sender_id is required")
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO integration_control_plane_senders(
                    tenant_id, sender_id, family, enabled, updated_at,
                    updated_by_principal_id
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, sender_id) DO UPDATE SET
                    family = excluded.family,
                    enabled = excluded.enabled,
                    updated_at = excluded.updated_at,
                    updated_by_principal_id = excluded.updated_by_principal_id
                """,
                (
                    tenant_id, sender_id, family or "", 1 if enabled else 0,
                    int(now_ts), acting_principal_id,
                ),
            )
        return self.control_plane_state(tenant_id)

    def legacy_connections(self):
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM oauth_connections ORDER BY principal_id, provider"
            ).fetchall()
        return [_legacy_connection(row) for row in rows]

    def legacy_mapping(self, legacy_key):
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM integration_connection_legacy_map WHERE legacy_key = ?",
                (legacy_key,),
            ).fetchone()
        return dict(row) if row is not None else None

    def record_legacy_mapping(
        self, legacy_key, connection_id, status, checksum, now_ts, error_code=None
    ):
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO integration_connection_legacy_map(
                    legacy_key, connection_id, migration_status, source_checksum,
                    error_code, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(legacy_key) DO UPDATE SET
                    migration_status = excluded.migration_status,
                    source_checksum = excluded.source_checksum,
                    error_code = excluded.error_code,
                    updated_at = excluded.updated_at
                """,
                (
                    legacy_key,
                    connection_id,
                    status,
                    checksum,
                    error_code,
                    int(now_ts),
                    int(now_ts),
                ),
            )

    def mark_pending_revocation(self, principal_id, provider, now_ts):
        with self._lock:
            cursor = self._connection.execute(
                """
                UPDATE oauth_connections
                SET status = 'pending_revocation', updated_at = ?
                WHERE principal_id = ? AND provider = ?
                """,
                (int(now_ts), principal_id, provider),
            )
        return cursor.rowcount == 1

    def delete_connection(self, principal_id, provider, credential_id):
        with self._lock:
            cursor = self._connection.execute(
                """
                DELETE FROM oauth_connections
                WHERE principal_id = ? AND provider = ? AND credential_id = ?
                """,
                (principal_id, provider, credential_id),
            )
        return cursor.rowcount == 1

    def get_connection(self, principal_id, provider):
        with self._lock:
            row = self._connection.execute(
                """
                SELECT * FROM oauth_connections
                WHERE principal_id = ? AND provider = ?
                """,
                (principal_id, provider),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["granted_scopes"] = json.loads(result["granted_scopes"])
        result["enabled_capabilities"] = json.loads(
            result["enabled_capabilities"]
        )
        return result

    def count_transactions(self):
        with self._lock:
            row = self._connection.execute(
                "SELECT COUNT(*) AS count FROM oauth_transactions"
            ).fetchone()
        return row["count"]

    def close(self):
        with self._lock:
            self._connection.close()

    def _ensure_connection_column(self, name, declaration):
        columns = {
            row["name"]
            for row in self._connection.execute(
                "PRAGMA table_info(oauth_connections)"
            ).fetchall()
        }
        if name not in columns:
            self._connection.execute(
                "ALTER TABLE oauth_connections ADD COLUMN %s %s"
                % (name, declaration)
            )

    def _ensure_transaction_column(self, name, declaration):
        columns = {
            row["name"]
            for row in self._connection.execute(
                "PRAGMA table_info(oauth_transactions)"
            ).fetchall()
        }
        if name not in columns:
            self._connection.execute(
                "ALTER TABLE oauth_transactions ADD COLUMN %s %s"
                % (name, declaration)
            )


class PostgresOAuthRepository(object):
    """PostgreSQL implementation of the OAuth operational-state contract."""

    TRANSACTION_TTL_SECONDS = OAuthRepository.TRANSACTION_TTL_SECONDS
    PROFILE_KINDS = OAuthRepository.PROFILE_KINDS
    requires_tenant_context = True

    def __init__(self, db, pkce_cipher):
        if pkce_cipher is None:
            raise ValueError("pkce_cipher is required")
        self.db = db
        self.pkce_cipher = pkce_cipher
        self.connections = IntegrationConnectionRepository(db)
        self.provider_control = ProviderControlPlaneRepository(db)

    @staticmethod
    def hash_value(value):
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def create_transaction(
        self,
        transaction_id,
        session_id,
        principal_id,
        provider,
        requested_scopes,
        requested_capabilities,
        state,
        pkce_verifier,
        return_to,
        now_ts,
        tenant_id=None,
        app_id=None,
        intended_team_id=None,
        target_connection_id=None,
    ):
        if not tenant_id:
            raise ValueError("tenant_id is required")
        now = _utc(now_ts)
        with self.db.transaction() as conn:
            conn.execute(
                "delete from integrations.oauth_transactions "
                "where tenant_id = %s and expires_at < %s",
                (tenant_id, now),
            )
            row = conn.execute(
                """
                insert into integrations.oauth_transactions(
                    transaction_id, tenant_id, session_hash, principal_id,
                    provider, requested_scopes, requested_capabilities,
                    state_hash, pkce_verifier_ciphertext, return_to, app_id,
                    intended_team_id, target_connection_id, created_at,
                    expires_at
                ) values (
                    %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s,
                    %s, %s, %s, %s, %s, %s
                ) returning *
                """,
                (
                    transaction_id,
                    tenant_id,
                    self.hash_value(session_id),
                    principal_id,
                    provider,
                    _dumps(requested_scopes),
                    _dumps(requested_capabilities),
                    self.hash_value(state),
                    self.pkce_cipher.encrypt(pkce_verifier),
                    return_to,
                    app_id,
                    intended_team_id,
                    target_connection_id,
                    now,
                    _utc(int(now_ts) + self.TRANSACTION_TTL_SECONDS),
                ),
            ).fetchone()
        return self._transaction(row)

    def find_by_state(self, state, now_ts=None):
        if not state:
            return None
        with self.db.connection() as conn:
            row = conn.execute(
                "select * from integrations.oauth_transactions "
                "where state_hash = %s",
                (self.hash_value(state),),
            ).fetchone()
        return self._transaction(row)

    def consume_transaction(self, state, session_id, principal_id, now_ts):
        if not state or not session_id or not principal_id:
            return None
        now = _utc(now_ts)
        with self.db.transaction() as conn:
            row = conn.execute(
                """
                update integrations.oauth_transactions
                set consumed_at = %s
                where state_hash = %s and session_hash = %s
                  and principal_id = %s and consumed_at is null
                  and expires_at >= %s
                returning *
                """,
                (
                    now,
                    self.hash_value(state),
                    self.hash_value(session_id),
                    principal_id,
                    now,
                ),
            ).fetchone()
            if row is not None:
                conn.execute(
                    "update integrations.oauth_transactions "
                    "set pkce_verifier_ciphertext = '' "
                    "where transaction_id = %s",
                    (row[0],),
                )
        return self._transaction(row)

    def upsert_installation(
        self, tenant_id, principal_id, provider, app_id, credential_id,
        granted_scopes, enabled_capabilities, now_ts, connection_id=None,
        team_id=None, team_name=None, enterprise_id=None, bot_user_id=None,
        credential_version=1,
    ):
        try:
            record = self.connections.upsert(
                tenant_id, principal_id, provider, app_id, credential_id,
                granted_scopes, enabled_capabilities,
                connection_id=connection_id, team_id=team_id,
                team_name=team_name, enterprise_id=enterprise_id,
                bot_user_id=bot_user_id,
                credential_version=credential_version,
            )
        except IntegrationConnectionConflict as exc:
            raise ConnectionConflict(str(exc)) from exc
        return _postgres_installation(record)

    def upsert_connection(
        self, principal_id, provider, credential_id, granted_scopes,
        enabled_capabilities, now_ts,
    ):
        tenant_id = current_organization_id()
        if not tenant_id:
            raise ValueError("tenant_id is required")
        return self.upsert_installation(
            tenant_id, principal_id, provider, provider, credential_id,
            granted_scopes, enabled_capabilities, now_ts,
        )

    def get_connection(self, principal_id, provider):
        tenant_id = current_organization_id()
        if not tenant_id:
            return None
        rows = self.list_installations(tenant_id, principal_id, provider)
        return rows[0] if rows else None

    def mark_pending_revocation(self, principal_id, provider, now_ts):
        connection = self.get_connection(principal_id, provider)
        if connection is None:
            return False
        return self.mark_installation_status(
            connection["connection_id"], connection["tenant_id"],
            "pending_revocation", now_ts,
        )

    def delete_connection(self, principal_id, provider, credential_id):
        connection = self.get_connection(principal_id, provider)
        if connection is None or connection["credential_id"] != credential_id:
            return False
        return self.tombstone_installation(
            connection["connection_id"], connection["tenant_id"],
            int(datetime.now(tz=timezone.utc).timestamp()),
        )

    def get_installation(self, connection_id, tenant_id):
        return _postgres_installation(self.connections.get(tenant_id, connection_id))

    def list_installations(self, tenant_id, principal_id, provider=None):
        return [
            _postgres_installation(row)
            for row in self.connections.list_for_owner(
                tenant_id, principal_id, provider
            )
        ]

    def list_tenant_installations(self, tenant_id, provider=None, usable_only=True):
        return [
            _postgres_installation(row)
            for row in self.connections.list_for_tenant(
                tenant_id, provider, usable_only
            )
        ]

    def tombstone_installation(self, connection_id, tenant_id, now_ts):
        with self.db.transaction() as conn:
            cursor = conn.execute(
                """
                update integrations.connections set
                    status = 'disconnected', credential_id = null,
                    effective_scopes = '[]'::jsonb,
                    enabled_capabilities = '[]'::jsonb,
                    disconnected_at = %s, updated_at = %s
                where connection_id = %s and tenant_id = %s
                """,
                (_utc(now_ts), _utc(now_ts), connection_id, tenant_id),
            )
        return cursor.rowcount == 1

    def mark_installation_status(
        self, connection_id, tenant_id, status, now_ts, expected_status=None
    ):
        allowed = {
            "connected", "degraded", "refreshing", "rotation_uncertain",
            "pending_revocation", "disconnect_pending", "blocked_connection",
            "disconnected", "migration_blocked",
        }
        if status not in allowed:
            raise ValueError("unsupported connection status")
        sql = (
            "update integrations.connections set status = %s, updated_at = %s "
            "where connection_id = %s and tenant_id = %s"
        )
        params = [status, _utc(now_ts), connection_id, tenant_id]
        if expected_status:
            sql += " and status = %s"
            params.append(expected_status)
        with self.db.transaction() as conn:
            cursor = conn.execute(sql, params)
        return cursor.rowcount == 1

    def record_authority_profile(
        self, tenant_id, connection_id, profile_kind,
        consent_owner_principal_id, credential_id, granted_scopes, now_ts,
        slack_subject_id=None, credential_version=1, enabled=False,
    ):
        if profile_kind not in self.PROFILE_KINDS:
            raise ValueError("unsupported authority profile kind")
        if profile_kind != "bot" and not slack_subject_id:
            raise ValueError("a personal authority profile needs its subject")
        if not all((tenant_id, connection_id, consent_owner_principal_id,
                    credential_id)):
            raise ValueError("authority profile binding is required")
        profile_id = "authority:%s" % uuid.uuid4().hex
        with self.db.transaction() as conn:
            conn.execute(
                """
                insert into orchestrator.slack_authority_profiles(
                    authority_profile_id, tenant_id, connection_id,
                    profile_kind, slack_subject_id,
                    consent_owner_principal_id, credential_id,
                    credential_version, granted_scopes, status, enabled,
                    created_at, updated_at
                ) values (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb,
                    'active', %s, %s, %s
                ) on conflict (
                    tenant_id, connection_id, profile_kind,
                    consent_owner_principal_id
                ) do update set
                    slack_subject_id = excluded.slack_subject_id,
                    credential_id = excluded.credential_id,
                    credential_version = excluded.credential_version,
                    granted_scopes = excluded.granted_scopes,
                    status = 'active', revoked_at = null,
                    updated_at = excluded.updated_at
                """,
                (
                    profile_id, tenant_id, connection_id, profile_kind,
                    slack_subject_id, consent_owner_principal_id,
                    credential_id, int(credential_version),
                    _dumps(granted_scopes or ()), bool(enabled),
                    _utc(now_ts), _utc(now_ts),
                ),
            )
        return self.get_authority_profile(
            tenant_id, connection_id, profile_kind,
            consent_owner_principal_id,
        )

    def get_authority_profile(
        self, tenant_id, connection_id, profile_kind,
        consent_owner_principal_id,
    ):
        with self.db.connection() as conn:
            row = conn.execute(
                """
                select authority_profile_id, tenant_id, connection_id,
                       profile_kind, slack_subject_id,
                       consent_owner_principal_id, credential_id,
                       credential_version, granted_scopes, status, enabled,
                       created_at, updated_at, revoked_at
                from orchestrator.slack_authority_profiles
                where tenant_id = %s and connection_id = %s
                  and profile_kind = %s
                  and consent_owner_principal_id = %s
                """,
                (tenant_id, connection_id, profile_kind,
                 consent_owner_principal_id),
            ).fetchone()
        return _postgres_authority_profile(row)

    def list_personal_authority(self, tenant_id, connection_id, principal_id):
        with self.db.connection() as conn:
            rows = conn.execute(
                """
                select authority_profile_id, tenant_id, connection_id,
                       profile_kind, slack_subject_id,
                       consent_owner_principal_id, credential_id,
                       credential_version, granted_scopes, status, enabled,
                       created_at, updated_at, revoked_at
                from orchestrator.slack_authority_profiles
                where tenant_id = %s and connection_id = %s
                  and consent_owner_principal_id = %s
                  and profile_kind <> 'bot' and status = 'active'
                order by profile_kind
                """,
                (tenant_id, connection_id, principal_id),
            ).fetchall()
        return [_postgres_authority_profile(row) for row in rows]

    def revoke_authority_profile(
        self, tenant_id, connection_id, profile_kind, principal_id, now_ts
    ):
        with self.db.transaction() as conn:
            cursor = conn.execute(
                """
                update orchestrator.slack_authority_profiles
                set status = 'revoked', enabled = false, revoked_at = %s,
                    updated_at = %s
                where tenant_id = %s and connection_id = %s
                  and profile_kind = %s
                  and consent_owner_principal_id = %s
                  and status = 'active'
                """,
                (_utc(now_ts), _utc(now_ts), tenant_id, connection_id,
                 profile_kind, principal_id),
            )
        return cursor.rowcount == 1

    def set_authority_profile_enabled(
        self, tenant_id, connection_id, profile_kind, principal_id, enabled,
        now_ts,
    ):
        with self.db.transaction() as conn:
            cursor = conn.execute(
                """
                update orchestrator.slack_authority_profiles
                set enabled = %s, updated_at = %s
                where tenant_id = %s and connection_id = %s
                  and profile_kind = %s
                  and consent_owner_principal_id = %s
                  and status = 'active'
                """,
                (bool(enabled), _utc(now_ts), tenant_id, connection_id,
                 profile_kind, principal_id),
            )
        return cursor.rowcount == 1

    def grant_authority_delegation(
        self, tenant_id, authority_profile_id, audience_principal_id,
        operation_family, purpose, granted_by_principal_id, expires_at,
        now_ts,
    ):
        if not purpose or not operation_family:
            raise ValueError("a delegation needs a purpose and a family")
        if int(expires_at) <= int(now_ts):
            raise ValueError("a delegation must expire in the future")
        delegation_id = "delegation:%s" % uuid.uuid4().hex
        with self.db.transaction() as conn:
            conn.execute(
                """
                insert into orchestrator.slack_authority_delegations(
                    delegation_id, tenant_id, authority_profile_id,
                    audience_principal_id, operation_family, purpose,
                    granted_by_principal_id, expires_at, created_at
                ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (
                    tenant_id, authority_profile_id, audience_principal_id,
                    operation_family
                ) do update set
                    purpose = excluded.purpose,
                    granted_by_principal_id = excluded.granted_by_principal_id,
                    expires_at = excluded.expires_at, revoked_at = null
                """,
                (
                    delegation_id, tenant_id, authority_profile_id,
                    audience_principal_id, operation_family, purpose,
                    granted_by_principal_id, _utc(expires_at), _utc(now_ts),
                ),
            )
        return delegation_id

    def authorize_personal_authority(
        self, tenant_id, connection_id, profile_kind,
        requester_principal_id, operation_family, now_ts,
        consent_owner_principal_id=None,
    ):
        owner = consent_owner_principal_id or requester_principal_id
        profile = self.get_authority_profile(
            tenant_id, connection_id, profile_kind, owner
        )
        if profile is None:
            return {"allowed": False, "reason": "authority_profile_absent"}
        if profile["status"] != "active":
            return {"allowed": False, "reason": "authority_profile_%s" % profile["status"]}
        if not profile["enabled"]:
            return {"allowed": False, "reason": "authority_profile_disabled"}
        if profile_kind == "bot":
            return {"allowed": True, "reason": "tenant_bot_authority",
                    "authority_profile_id": profile["authority_profile_id"]}
        if owner == requester_principal_id:
            return {"allowed": True, "reason": "requester_is_subject",
                    "authority_profile_id": profile["authority_profile_id"]}
        with self.db.connection() as conn:
            delegation = conn.execute(
                """
                select delegation_id
                from orchestrator.slack_authority_delegations
                where tenant_id = %s and authority_profile_id = %s
                  and audience_principal_id = %s and operation_family = %s
                  and revoked_at is null and expires_at > %s
                """,
                (tenant_id, profile["authority_profile_id"],
                 requester_principal_id, operation_family, _utc(now_ts)),
            ).fetchone()
        if delegation is None:
            return {"allowed": False, "reason": "delegation_absent"}
        return {"allowed": True, "reason": "delegated",
                "authority_profile_id": profile["authority_profile_id"],
                "delegation_id": delegation[0]}

    def replace_voice_routes(self, tenant_id, routes):
        with self.db.transaction() as conn:
            conn.execute(
                "delete from voice.transfer_routes where tenant_id = %s",
                (tenant_id,),
            )
            for route in routes:
                conn.execute(
                    """
                    insert into voice.transfer_routes(
                        tenant_id, route_id, department, language, destination,
                        timezone, start_hour, end_hour, ring_seconds,
                        total_budget_seconds, priority, enabled
                    ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, true)
                    """,
                    (
                        tenant_id, route["route_id"], route["department"],
                        route["language"], route["destination"],
                        route["timezone"], route["start_hour"],
                        route["end_hour"], route["ring_seconds"],
                        route["total_budget_seconds"], route["priority"],
                    ),
                )

    def voice_routes(self, tenant_id):
        with self.db.connection() as conn:
            rows = conn.execute(
                """
                select route_id, department, language, destination, timezone,
                       start_hour, end_hour, ring_seconds,
                       total_budget_seconds, priority
                from voice.transfer_routes
                where tenant_id = %s and enabled
                order by priority, route_id
                """,
                (tenant_id,),
            ).fetchall()
        keys = (
            "route_id", "department", "language", "destination", "timezone",
            "start_hour", "end_hour", "ring_seconds", "total_budget_seconds",
            "priority",
        )
        return [dict(zip(keys, row)) for row in rows]

    def record_verified_account(
        self, tenant_id, connection_id, provider, provider_account_id, state
    ):
        return self.provider_control.record_verified_account(
            tenant_id, connection_id, provider, provider_account_id, state
        )

    def control_plane_state(self, tenant_id):
        return self.provider_control.control_plane_state(tenant_id)

    def set_emergency_stop(
        self, tenant_id, active, now_ts, reason=None,
        acting_principal_id=None,
    ):
        return self.provider_control.set_emergency_stop(
            tenant_id, active, reason=reason,
            acting_principal_id=acting_principal_id,
        )

    def set_capability_family_enabled(
        self, tenant_id, family, enabled, now_ts,
        acting_principal_id=None,
    ):
        with self.db.connection() as conn:
            rows = conn.execute(
                """
                select connection_id
                from integrations.provider_account_families
                where tenant_id = %s and family = %s
                order by connection_id
                """,
                (tenant_id, family),
            ).fetchall()
        for row in rows:
            self.provider_control.set_family_enabled(
                tenant_id, row[0], family, enabled
            )
        return self.control_plane_state(tenant_id)

    def set_control_plane_sender_enabled(
        self, tenant_id, sender_id, enabled, now_ts, family="",
        acting_principal_id=None,
    ):
        with self.db.connection() as conn:
            row = conn.execute(
                """
                select connection_id from integrations.provider_senders
                where tenant_id = %s and sender_id = %s
                order by connection_id limit 1
                """,
                (tenant_id, sender_id),
            ).fetchone()
        if row is not None:
            self.provider_control.set_sender_enabled(
                tenant_id, row[0], sender_id, enabled,
                acting_principal_id=acting_principal_id,
            )
        return self.control_plane_state(tenant_id)

    def count_transactions(self):
        with self.db.connection() as conn:
            return conn.execute(
                "select count(*) from integrations.oauth_transactions"
            ).fetchone()[0]

    def close(self):
        # Database ownership belongs to service composition, not repositories.
        return None

    def _transaction(self, row):
        if row is None:
            return None
        keys = (
            "transaction_id", "tenant_id", "session_hash", "principal_id",
            "provider", "requested_scopes", "requested_capabilities",
            "state_hash", "pkce_verifier_ciphertext", "return_to", "app_id",
            "intended_team_id", "target_connection_id", "created_at",
            "expires_at", "consumed_at",
        )
        result = dict(zip(keys, row))
        ciphertext = result.pop("pkce_verifier_ciphertext")
        result["pkce_verifier"] = (
            self.pkce_cipher.decrypt(ciphertext) if ciphertext else ""
        )
        for key in ("created_at", "expires_at", "consumed_at"):
            if result[key] is not None:
                result[key] = int(result[key].timestamp())
        return result


def _dumps(value):
    return json.dumps(
        sorted(set(value)), separators=(",", ":"), ensure_ascii=True
    )


def _transaction(row):
    if row is None:
        return None
    result = dict(row)
    result["requested_scopes"] = json.loads(result["requested_scopes"])
    result["requested_capabilities"] = json.loads(
        result["requested_capabilities"]
    )
    return result


def _stable_connection_id(provider, app_id, team_id, principal_id):
    identity = ":".join(
        [provider, app_id, team_id or "", principal_id if not team_id else ""]
    )
    return "conn:%s" % uuid.uuid5(uuid.NAMESPACE_URL, "tessera:%s" % identity)


def _legacy_connection(row):
    result = dict(row)
    result["granted_scopes"] = json.loads(result["granted_scopes"])
    result["enabled_capabilities"] = json.loads(result["enabled_capabilities"])
    return result


def _installation(row):
    if row is None:
        return None
    result = dict(row)
    result["granted_scopes"] = json.loads(result["granted_scopes"])
    result["enabled_capabilities"] = json.loads(result["enabled_capabilities"])
    return result


def _postgres_installation(row):
    if row is None:
        return None
    result = dict(row)
    result["principal_id"] = result.pop("owner_principal_id")
    result["granted_scopes"] = list(result.pop("effective_scopes"))
    result["enabled_capabilities"] = list(result["enabled_capabilities"])
    return result


def _postgres_authority_profile(row):
    if row is None:
        return None
    keys = (
        "authority_profile_id", "tenant_id", "connection_id",
        "profile_kind", "slack_subject_id", "consent_owner_principal_id",
        "credential_id", "credential_version", "granted_scopes", "status",
        "enabled", "created_at", "updated_at", "revoked_at",
    )
    result = dict(zip(keys, row))
    result["granted_scopes"] = list(result["granted_scopes"] or ())
    result["enabled"] = bool(result["enabled"])
    for key in ("created_at", "updated_at", "revoked_at"):
        if result[key] is not None:
            result[key] = int(result[key].timestamp())
    return result


def _utc(value):
    return datetime.fromtimestamp(int(value), tz=timezone.utc)
