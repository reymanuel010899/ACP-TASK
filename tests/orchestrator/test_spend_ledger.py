from decimal import Decimal
import threading

import pytest

from libs.spend_ledger import (
    SpendCeilingExceeded, SpendLedger, estimate_sms_cost, estimate_voice_cost,
)


def store(tmp_path):
    ledger = SpendLedger(str(tmp_path / "spend.db"), clock=lambda: 100)
    ledger.set_ceiling("tenant:a", "account", "tenant:a", "1.00")
    return ledger


def test_reservation_and_settlement_move_money_atomically(tmp_path):
    ledger = store(tmp_path)
    reservation = ledger.reserve("tenant:a", "r1", "sms", "0.20")
    assert reservation["reserved"] == Decimal("0.2")
    settled = ledger.settle("tenant:a", "r1", "0.12")
    assert settled["settled"] == Decimal("0.12")
    budget = ledger.budget("tenant:a", "account", "tenant:a")
    assert budget["reserved_micros"] == 0
    assert budget["settled_micros"] == 120000


def test_account_and_campaign_exhaustion_have_distinct_reasons(tmp_path):
    ledger = store(tmp_path)
    ledger.set_ceiling("tenant:a", "campaign", "campaign:1", "0.10")
    with pytest.raises(SpendCeilingExceeded) as raised:
        ledger.reserve("tenant:a", "r1", "sms", "0.20", "campaign:1")
    assert raised.value.reason == "campaign_ceiling_exhausted"
    with pytest.raises(SpendCeilingExceeded) as raised:
        ledger.reserve("tenant:a", "r2", "sms", "2.00")
    assert raised.value.reason == "account_ceiling_exhausted"


def test_parallel_reservations_never_oversubscribe(tmp_path):
    ledger = store(tmp_path)
    outcomes = []
    def reserve(index):
        try:
            ledger.reserve("tenant:a", "r%s" % index, "sms", "0.60")
            outcomes.append("reserved")
        except SpendCeilingExceeded:
            outcomes.append("denied")
    threads = [threading.Thread(target=reserve, args=(index,)) for index in (1, 2)]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    assert sorted(outcomes) == ["denied", "reserved"]


def test_never_dispatched_effect_releases_and_estimators_round_worst_case(tmp_path):
    ledger = store(tmp_path)
    ledger.reserve("tenant:a", "r1", "voice", "0.50")
    assert ledger.release("tenant:a", "r1") is True
    assert ledger.budget("tenant:a", "account", "tenant:a")["reserved_micros"] == 0
    assert estimate_sms_cost("a" * 161, "0.01") == Decimal("0.02")
    assert estimate_voice_cost(61, "0.02") == Decimal("0.04")


def test_brand_daily_volume_is_metered_locally_at_the_threshold(tmp_path):
    ledger = store(tmp_path)
    assert ledger.meter_brand_volume("tenant:a", "brand:1", "2026-08-06", 2) == 1
    assert ledger.meter_brand_volume("tenant:a", "brand:1", "2026-08-06", 2) == 2
    with pytest.raises(SpendCeilingExceeded) as raised:
        ledger.meter_brand_volume("tenant:a", "brand:1", "2026-08-06", 2)
    assert raised.value.reason == "brand_daily_volume_exhausted"
