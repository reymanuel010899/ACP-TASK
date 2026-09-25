"""Connection/method Slack rate budgets and per-channel write serialization."""

import threading
import time
import sqlite3
from contextlib import contextmanager


class SlackRatePolicy:
    def __init__(self, clock=None):
        self.clock = clock or time.time
        self._guard = threading.Lock()
        self._blocked_until = {}
        self._write_locks = {}

    def block(self, connection_id, method, retry_after):
        with self._guard:
            self._blocked_until[(connection_id, method)] = (
                self.clock() + max(1, int(retry_after))
            )

    def check(self, connection_id, method):
        with self._guard:
            blocked_until = self._blocked_until.get((connection_id, method), 0)
        if blocked_until > self.clock():
            from libs.connectors.slack import SlackRateLimitError
            raise SlackRateLimitError(
                connection_id, method, int(blocked_until - self.clock())
            )

    @contextmanager
    def write_guard(self, connection_id, channel_id):
        key = (connection_id, channel_id)
        with self._guard:
            lock = self._write_locks.setdefault(key, threading.Lock())
        with lock:
            yield


class ThroughputExceeded(RuntimeError):
    def __init__(self, retry_at):
        self.retry_at = int(retry_at)
        super().__init__("distributed throughput ceiling reached")


class DistributedThroughputLimit:
    """A fixed-window budget shared by every broker process."""

    def __init__(self, database_path, clock=None):
        self.clock = clock or time.time
        self._connection = sqlite3.connect(
            database_path, isolation_level=None, timeout=10,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.executescript("""
            pragma journal_mode=WAL;
            create table if not exists throughput_limits(
                tenant_id text not null,capability_id text not null,
                limit_count integer not null,window_seconds integer not null,
                primary key(tenant_id,capability_id)
            );
            create table if not exists throughput_windows(
                tenant_id text not null,capability_id text not null,
                window_started integer not null,used integer not null,
                primary key(tenant_id,capability_id)
            );
        """)

    def configure(self, tenant_id, capability_id, limit, window_seconds):
        if int(limit) <= 0 or int(window_seconds) <= 0:
            raise ValueError("throughput limit and window must be positive")
        self._connection.execute(
            """insert into throughput_limits(
                tenant_id,capability_id,limit_count,window_seconds
            ) values(?,?,?,?) on conflict(tenant_id,capability_id) do update set
              limit_count=excluded.limit_count,window_seconds=excluded.window_seconds""",
            (tenant_id, capability_id, int(limit), int(window_seconds)),
        )

    def acquire(self, tenant_id, capability_id, units=1):
        now = int(self.clock())
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            limit = self._connection.execute(
                "select * from throughput_limits where tenant_id=? and capability_id=?",
                (tenant_id, capability_id),
            ).fetchone()
            if limit is None:
                raise LookupError("throughput limit is not configured")
            window = self._connection.execute(
                "select * from throughput_windows where tenant_id=? and capability_id=?",
                (tenant_id, capability_id),
            ).fetchone()
            reset = (
                window is None
                or now >= window["window_started"] + limit["window_seconds"]
            )
            start = now if reset else window["window_started"]
            used = 0 if reset else window["used"]
            if used + int(units) > limit["limit_count"]:
                raise ThroughputExceeded(start + limit["window_seconds"])
            used += int(units)
            self._connection.execute(
                """insert into throughput_windows(
                    tenant_id,capability_id,window_started,used
                ) values(?,?,?,?) on conflict(tenant_id,capability_id) do update set
                  window_started=excluded.window_started,used=excluded.used""",
                (tenant_id, capability_id, start, used),
            )
            self._connection.execute("COMMIT")
            return used
        except Exception:
            if self._connection.in_transaction:
                self._connection.execute("ROLLBACK")
            raise
