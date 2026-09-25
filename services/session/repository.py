"""Persistent, server-side storage for first-party browser sessions."""

import hashlib
import secrets
import sqlite3
import threading

import psycopg


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
        self._ensure_columns()

    def _ensure_columns(self):
        columns = {
            row["name"]
            for row in self._connection.execute("PRAGMA table_info(web_sessions)")
        }
        if "authenticated_at" not in columns:
            self._connection.execute(
                "ALTER TABLE web_sessions ADD COLUMN authenticated_at INTEGER"
            )
            self._connection.execute(
                "UPDATE web_sessions SET authenticated_at = created_at "
                "WHERE authenticated_at IS NULL"
            )

    def attest_authentication(self, session_id, now_ts):
        """Record that this session just proved who it is, again.

        Distinct from touching the session: using a session keeps it alive but
        proves nothing new. A step-up needs the moment authentication actually
        happened, or a session left open all day would look freshly verified.
        """
        with self._lock:
            cursor = self._connection.execute(
                "UPDATE web_sessions SET authenticated_at = ?, last_seen_at = ? "
                "WHERE session_hash = ? AND revoked_at IS NULL",
                (int(now_ts), int(now_ts), self._hash(session_id)),
            )
        return cursor.rowcount == 1

    def authentication_attestation(self, session_id, now_ts,
                                   freshness_seconds=300):
        """Report how recently this session authenticated, and whether that
        is inside the named window. An unknown session is never fresh."""
        with self._lock:
            row = self._connection.execute(
                "SELECT authenticated_at, created_at FROM web_sessions "
                "WHERE session_hash = ? AND revoked_at IS NULL",
                (self._hash(session_id),),
            ).fetchone()
        if row is None:
            return {
                "fresh": False, "reason": "session_absent",
                "freshness_seconds": int(freshness_seconds),
            }
        authenticated_at = int(row["authenticated_at"] or row["created_at"])
        age = int(now_ts) - authenticated_at
        return {
            "fresh": age <= int(freshness_seconds) and age >= 0,
            "reason": "fresh" if age <= int(freshness_seconds) and age >= 0
            else "authentication_stale",
            "authenticated_at": authenticated_at,
            "age_seconds": age,
            "freshness_seconds": int(freshness_seconds),
        }

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
                        last_seen_at, absolute_expires_at, revoked_at,
                        authenticated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?)
                    """,
                    (
                        session_hash,
                        principal_id,
                        self._hash(csrf_token),
                        now,
                        now,
                        now + self.absolute_ttl_seconds,
                        now,
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
            "idle_ttl_seconds": self.idle_ttl_seconds,
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
                "idle_ttl_seconds": self.idle_ttl_seconds,
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


class PostgresSessionRepository(object):
    """PostgreSQL implementation of the first-party session contract.

    Session lookup precedes organization selection, so these authentication
    rows are intentionally global while every authorization performed after
    resolution remains tenant-bound.
    """

    def __init__(self, db, idle_ttl_seconds=1800, absolute_ttl_seconds=43200):
        self.db = db
        self.idle_ttl_seconds = int(idle_ttl_seconds)
        self.absolute_ttl_seconds = int(absolute_ttl_seconds)

    @staticmethod
    def _hash(value):
        return SessionRepository._hash(value)

    def attest_authentication(self, session_id, now_ts):
        with self.db.transaction() as conn:
            row = conn.execute(
                """
                update identity.web_sessions
                   set authenticated_at = to_timestamp(%s),
                       last_seen_at = to_timestamp(%s)
                 where session_hash = %s and revoked_at is null
                returning session_hash
                """,
                (int(now_ts), int(now_ts), self._hash(session_id)),
            ).fetchone()
        return row is not None

    def authentication_attestation(
        self, session_id, now_ts, freshness_seconds=300
    ):
        with self.db.connection() as conn:
            row = conn.execute(
                """
                select extract(epoch from authenticated_at)::bigint
                from identity.web_sessions
                where session_hash = %s and revoked_at is null
                """,
                (self._hash(session_id),),
            ).fetchone()
        if row is None:
            return {
                "fresh": False,
                "reason": "session_absent",
                "freshness_seconds": int(freshness_seconds),
            }
        authenticated_at = int(row[0])
        age = int(now_ts) - authenticated_at
        fresh = 0 <= age <= int(freshness_seconds)
        return {
            "fresh": fresh,
            "reason": "fresh" if fresh else "authentication_stale",
            "authenticated_at": authenticated_at,
            "age_seconds": age,
            "freshness_seconds": int(freshness_seconds),
        }

    def create(
        self,
        principal_id,
        proof_fingerprint,
        now_ts,
        previous_session_id=None,
    ):
        now = int(now_ts)
        session_id = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        session_hash = self._hash(session_id)
        proof_hash = self._hash(proof_fingerprint)
        try:
            with self.db.transaction() as conn:
                conn.execute(
                    """
                    insert into identity.consumed_identity_proofs(
                        proof_hash, consumed_at
                    ) values (%s, to_timestamp(%s))
                    """,
                    (proof_hash, now),
                )
                if previous_session_id:
                    conn.execute(
                        """
                        update identity.web_sessions
                           set revoked_at = to_timestamp(%s)
                         where session_hash = %s and revoked_at is null
                        """,
                        (now, self._hash(previous_session_id)),
                    )
                conn.execute(
                    """
                    insert into identity.web_sessions(
                        session_hash, principal_id, csrf_hash, created_at,
                        last_seen_at, authenticated_at, absolute_expires_at
                    ) values (
                        %s, %s, %s, to_timestamp(%s), to_timestamp(%s),
                        to_timestamp(%s), to_timestamp(%s)
                    )
                    """,
                    (
                        session_hash,
                        principal_id,
                        self._hash(csrf_token),
                        now,
                        now,
                        now,
                        now + self.absolute_ttl_seconds,
                    ),
                )
        except psycopg.errors.UniqueViolation as exc:
            raise ValueError("identity proof has already been consumed") from exc
        return {
            "session_id": session_id,
            "principal_id": principal_id,
            "csrf_token": csrf_token,
            "created_at": now,
            "expires_at": now + self.absolute_ttl_seconds,
            "idle_ttl_seconds": self.idle_ttl_seconds,
        }

    def resolve(self, session_id, now_ts, touch=True):
        if not session_id:
            return None
        now = int(now_ts)
        session_hash = self._hash(session_id)
        with self.db.transaction() as conn:
            row = conn.execute(
                """
                select principal_id,
                       extract(epoch from created_at)::bigint,
                       extract(epoch from last_seen_at)::bigint,
                       extract(epoch from absolute_expires_at)::bigint,
                       revoked_at
                from identity.web_sessions
                where session_hash = %s
                for update
                """,
                (session_hash,),
            ).fetchone()
            if row is None or row[4] is not None:
                return None
            expired = (
                now > int(row[3])
                or now - int(row[2]) > self.idle_ttl_seconds
            )
            if expired:
                conn.execute(
                    """
                    update identity.web_sessions
                       set revoked_at = to_timestamp(%s)
                     where session_hash = %s
                    """,
                    (now, session_hash),
                )
                return None
            if touch and now != int(row[2]):
                conn.execute(
                    """
                    update identity.web_sessions
                       set last_seen_at = to_timestamp(%s)
                     where session_hash = %s
                    """,
                    (now, session_hash),
                )
            return {
                "principal_id": row[0],
                "created_at": int(row[1]),
                "expires_at": int(row[3]),
                "idle_ttl_seconds": self.idle_ttl_seconds,
            }

    def csrf_matches(self, session_id, csrf_token):
        if not session_id or not csrf_token:
            return False
        with self.db.connection() as conn:
            row = conn.execute(
                """
                select csrf_hash from identity.web_sessions
                where session_hash = %s and revoked_at is null
                """,
                (self._hash(session_id),),
            ).fetchone()
        return bool(row) and secrets.compare_digest(
            row[0], self._hash(csrf_token)
        )

    def revoke(self, session_id, now_ts):
        if not session_id:
            return False
        with self.db.transaction() as conn:
            row = conn.execute(
                """
                update identity.web_sessions
                   set revoked_at = to_timestamp(%s)
                 where session_hash = %s and revoked_at is null
                returning session_hash
                """,
                (int(now_ts), self._hash(session_id)),
            ).fetchone()
        return row is not None

    def count_active(self, now_ts):
        now = int(now_ts)
        with self.db.connection() as conn:
            row = conn.execute(
                """
                select count(*) from identity.web_sessions
                where revoked_at is null
                  and absolute_expires_at >= to_timestamp(%s)
                  and last_seen_at >= to_timestamp(%s)
                """,
                (now, now - self.idle_ttl_seconds),
            ).fetchone()
        return int(row[0])

    def close(self):
        # The shared Database pool belongs to process composition, not to one
        # repository instance.
        return None
