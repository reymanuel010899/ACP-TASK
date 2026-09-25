import pytest

from services.action_broker.rate_limits import DistributedThroughputLimit, ThroughputExceeded


def test_two_processes_share_one_throughput_ceiling(tmp_path):
    path = str(tmp_path / "rates.db")
    first = DistributedThroughputLimit(path, clock=lambda: 100)
    second = DistributedThroughputLimit(path, clock=lambda: 100)
    first.configure("tenant:a", "twilio.sms.send", limit=2, window_seconds=60)
    assert first.acquire("tenant:a", "twilio.sms.send") == 1
    assert second.acquire("tenant:a", "twilio.sms.send") == 2
    with pytest.raises(ThroughputExceeded) as error:
        first.acquire("tenant:a", "twilio.sms.send")
    assert error.value.retry_at == 160
