"""SQLite persistence for one-use OAuth transactions and connections."""

import hashlib
import json
import sqlite3
import threading
import uuid


class ConnectionConflict(Exception):
    """A provider installation is already owned by another tenant."""


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
            """
        )
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
