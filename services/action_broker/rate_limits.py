"""Connection/method Slack rate budgets and per-channel write serialization."""

import threading
import time
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
