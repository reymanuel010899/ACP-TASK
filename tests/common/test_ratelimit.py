"""Tests for the shared fixed-window rate limiter (unit U5).

Test-first: defines the contract for ``common.ratelimit.RateLimiter`` before
it exists. The clock is injectable so window resets are deterministic.
"""

import pytest

from common.ratelimit import RateLimiter


class FakeClock(object):
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


def test_allows_up_to_the_limit_then_denies():
    clock = FakeClock()
    rl = RateLimiter(max_requests=3, window_seconds=10, clock=clock)
    assert rl.allow("ip-a") is True
    assert rl.allow("ip-a") is True
    assert rl.allow("ip-a") is True
    assert rl.allow("ip-a") is False  # 4th within the window is denied


def test_window_resets_after_it_elapses():
    clock = FakeClock()
    rl = RateLimiter(max_requests=2, window_seconds=10, clock=clock)
    assert rl.allow("ip-a") is True
    assert rl.allow("ip-a") is True
    assert rl.allow("ip-a") is False
    clock.advance(10.1)  # window elapsed
    assert rl.allow("ip-a") is True  # fresh window


def test_keys_are_independent():
    clock = FakeClock()
    rl = RateLimiter(max_requests=1, window_seconds=10, clock=clock)
    assert rl.allow("ip-a") is True
    assert rl.allow("ip-b") is True  # different IP has its own bucket
    assert rl.allow("ip-a") is False


def test_disabled_never_limits():
    clock = FakeClock()
    rl = RateLimiter(max_requests=1, window_seconds=10, enabled=False, clock=clock)
    for _ in range(100):
        assert rl.allow("ip-a") is True


def test_invalid_config_rejected():
    with pytest.raises(ValueError):
        RateLimiter(max_requests=0, window_seconds=10)
    with pytest.raises(ValueError):
        RateLimiter(max_requests=5, window_seconds=0)
