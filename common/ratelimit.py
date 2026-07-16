"""A minimal in-memory fixed-window rate limiter (unit U5).

Per-key (typically per client IP) request cap over a fixed time window. Basic
abuse mitigation for the reference stdlib servers — not distributed, not
persistent (both deferred). Thread-safe so it can back a ThreadingHTTPServer.

Usage::

    rl = RateLimiter(max_requests=100, window_seconds=60)
    if not rl.allow(client_ip):
        # respond 429
"""

import threading
import time

from typing import Callable, Dict, Optional, Tuple


class RateLimiter(object):
    def __init__(
        self,
        max_requests,
        window_seconds,
        enabled=True,
        clock=None,
    ):
        # type: (int, float, bool, Optional[Callable[[], float]]) -> None
        if max_requests < 1:
            raise ValueError("max_requests must be >= 1")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")
        self.max_requests = max_requests
        self.window_seconds = float(window_seconds)
        self.enabled = enabled
        self._clock = clock or time.time
        self._lock = threading.Lock()
        # key -> (window_start, count)
        self._buckets = {}  # type: Dict[str, Tuple[float, int]]

    def allow(self, key):
        # type: (str) -> bool
        """Record a request for ``key``; return False iff it exceeds the cap
        within the current window."""
        if not self.enabled:
            return True
        now = self._clock()
        with self._lock:
            window_start, count = self._buckets.get(key, (now, 0))
            if now - window_start >= self.window_seconds:
                window_start, count = now, 0  # window elapsed -> reset
            if count >= self.max_requests:
                self._buckets[key] = (window_start, count)
                return False
            self._buckets[key] = (window_start, count + 1)
            return True
