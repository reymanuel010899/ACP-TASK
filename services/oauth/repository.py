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
                    SELECT tenant_id, principal_id FROM integration_connections
                    WHERE connection_id = ?
                       OR (provider = 'slack' AND provider = ? AND app_id = ? AND team_id = ?)
                    """,
                    (resolved_id, provider, app_id, team_id),
                ).fetchone()
                if existing is not None and (
                    existing["tenant_id"] != tenant_id
                    or existing["principal_id"] != principal_id
                ):
                    raise ConnectionConflict(
                        "provider installation belongs to another tenant or owner"
                    )
                self._connection.execute(
                    """
                    INSERT INTO integration_connections(
                        connection_id, tenant_id, principal_id, provider, app_id,
                        team_id, team_name, enterprise_id, bot_user_id, credential_id,
                        credential_version, granted_scopes, enabled_capabilities,
                        status, created_at, updated_at, disconnected_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'connected', ?, ?, NULL)
                    ON CONFLICT(connection_id) DO UPDATE SET
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
