"""Persistent, server-side storage for first-party browser sessions."""

import hashlib
import secrets
import sqlite3
import threading


class SessionRepository(object):
    def __init__(self, database_path, idle_ttl_seconds=1800,
                 absolute_ttl_seconds=43200):
        self.idle_ttl_seconds = int(idle_ttl_seconds)
        self.absolute_ttl_seconds = int(absolute_ttl_seconds)
        self._connection = sqlite3.connect(
            database_path, check_same_thread=False, isolation_level=None
        )
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS web_sessions (
                session_hash TEXT PRIMARY KEY,
                principal_id TEXT NOT NULL,
                csrf_hash TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                last_seen_at INTEGER NOT NULL,
                absolute_expires_at INTEGER NOT NULL,
                revoked_at INTEGER
            );
            CREATE INDEX IF NOT EXISTS web_sessions_principal_idx
                ON web_sessions(principal_id);
            CREATE TABLE IF NOT EXISTS consumed_identity_proofs (
                proof_hash TEXT PRIMARY KEY,
                consumed_at INTEGER NOT NULL
            );
            """
        )

    @staticmethod
    def _hash(value):
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def create(self, principal_id, proof_fingerprint, now_ts,
               previous_session_id=None):
        now = int(now_ts)
        session_id = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        session_hash = self._hash(session_id)
        proof_hash = self._hash(proof_fingerprint)
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                self._connection.execute(
                    "INSERT INTO consumed_identity_proofs(proof_hash, consumed_at) "
                    "VALUES (?, ?)",
                    (proof_hash, now),
                )
                if previous_session_id:
                    self._connection.execute(
                        "UPDATE web_sessions SET revoked_at = ? "
                        "WHERE session_hash = ? AND revoked_at IS NULL",
                        (now, self._hash(previous_session_id)),
                    )
                self._connection.execute(
                    """
                    INSERT INTO web_sessions(
                        session_hash, principal_id, csrf_hash, created_at,
                        last_seen_at, absolute_expires_at, revoked_at
                    ) VALUES (?, ?, ?, ?, ?, ?, NULL)
                    """,
                    (
                        session_hash,
                        principal_id,
                        self._hash(csrf_token),
                        now,
                        now,
                        now + self.absolute_ttl_seconds,
                    ),
                )
                self._connection.execute("COMMIT")
            except sqlite3.IntegrityError:
                self._connection.execute("ROLLBACK")
                raise ValueError("identity proof has already been consumed")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
        return {
            "session_id": session_id,
            "principal_id": principal_id,
            "csrf_token": csrf_token,
            "created_at": now,
            "expires_at": now + self.absolute_ttl_seconds,
        }

    def resolve(self, session_id, now_ts, touch=True):
        if not session_id:
            return None
        now = int(now_ts)
        session_hash = self._hash(session_id)
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM web_sessions WHERE session_hash = ?",
                (session_hash,),
            ).fetchone()
            if row is None or row["revoked_at"] is not None:
                return None
            expired = (
                now > row["absolute_expires_at"]
                or now - row["last_seen_at"] > self.idle_ttl_seconds
            )
            if expired:
                self._connection.execute(
                    "UPDATE web_sessions SET revoked_at = ? WHERE session_hash = ?",
                    (now, session_hash),
                )
                return None
            if touch and now != row["last_seen_at"]:
                self._connection.execute(
                    "UPDATE web_sessions SET last_seen_at = ? WHERE session_hash = ?",
                    (now, session_hash),
                )
            return {
                "principal_id": row["principal_id"],
                "created_at": row["created_at"],
                "expires_at": row["absolute_expires_at"],
            }

    def csrf_matches(self, session_id, csrf_token):
        if not session_id or not csrf_token:
            return False
        with self._lock:
            row = self._connection.execute(
                "SELECT csrf_hash FROM web_sessions "
                "WHERE session_hash = ? AND revoked_at IS NULL",
                (self._hash(session_id),),
            ).fetchone()
        return bool(row) and secrets.compare_digest(
            row["csrf_hash"], self._hash(csrf_token)
        )

    def revoke(self, session_id, now_ts):
        if not session_id:
            return False
        with self._lock:
            cursor = self._connection.execute(
                "UPDATE web_sessions SET revoked_at = ? "
                "WHERE session_hash = ? AND revoked_at IS NULL",
                (int(now_ts), self._hash(session_id)),
            )
        return cursor.rowcount == 1

    def count_active(self, now_ts):
        now = int(now_ts)
        with self._lock:
            row = self._connection.execute(
                """
                SELECT COUNT(*) AS count FROM web_sessions
                WHERE revoked_at IS NULL
                  AND absolute_expires_at >= ?
                  AND last_seen_at >= ?
                """,
                (now, now - self.idle_ttl_seconds),
            ).fetchone()
        return row["count"]

    def close(self):
        with self._lock:
            self._connection.close()
