import threading

import pytest

from agents.orchestrator.dispatch_ledger import (
    AmbiguousDispatch, DispatchLedger, DuplicateDispatch,
)
from libs.connectors.base import ProviderNetworkError


def ledger(tmp_path):
    return DispatchLedger(str(tmp_path / "dispatch.db"), clock=lambda: 100)


def test_intent_and_callback_token_exist_before_provider_call(tmp_path):
    store = ledger(tmp_path)
    observed = []

    def provider(intent):
        observed.append(store.get("tenant:a", "dispatch:1"))
        return {"provider_id": "SM1", "status": "queued"}

    result = store.dispatch(
        "tenant:a", "dispatch:1", "effect:1", {"to": "+1"}, "token",
        provider,
    )

    assert observed[0]["status"] == "intent_recorded"
    assert observed[0]["callback_token"] == "token"
    assert result["provider_id"] == "SM1"
    assert store.get("tenant:a", "dispatch:1")["status"] == "accepted"


def test_timeout_after_possible_acceptance_becomes_ambiguous_and_never_retries(tmp_path):
    store = ledger(tmp_path)
    calls = []

    def timeout(_intent):
        calls.append(1)
        raise TimeoutError("response lost")

    with pytest.raises(AmbiguousDispatch):
        store.dispatch("tenant:a", "dispatch:1", "effect:1", {}, "token", timeout)
    with pytest.raises(AmbiguousDispatch):
        store.dispatch("tenant:a", "dispatch:1", "effect:1", {}, "token", timeout)

    assert calls == [1]
    assert store.get("tenant:a", "dispatch:1")["status"] == "ambiguous"


def test_provider_network_failure_is_ambiguous_after_crossing_dispatch_boundary(tmp_path):
    store = ledger(tmp_path)

    def disconnected(_intent):
        raise ProviderNetworkError("connection closed before response")

    with pytest.raises(AmbiguousDispatch):
        store.dispatch(
            "tenant:a", "dispatch:1", "effect:1", {}, "token", disconnected
        )
    assert store.get("tenant:a", "dispatch:1")["status"] == "ambiguous"


def test_two_workers_make_one_provider_call(tmp_path):
    store = ledger(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    calls = []
    errors = []

    def provider(_intent):
        calls.append(1)
        entered.set()
        release.wait(2)
        return {"provider_id": "SM1", "status": "queued"}

    def run():
        try:
            store.dispatch("tenant:a", "dispatch:1", "effect:1", {}, "token", provider)
        except DuplicateDispatch as exc:
            errors.append(exc)

    first = threading.Thread(target=run)
    second = threading.Thread(target=run)
    first.start()
    entered.wait(2)
    second.start()
    second.join(2)
    release.set()
    first.join(2)

    assert calls == [1]
    assert len(errors) == 1


def test_safe_rate_limit_can_reopen_the_same_intent(tmp_path):
    store = ledger(tmp_path)
    calls = []

    class RateLimited(Exception):
        category = "rate_limit"

    def provider(_intent):
        calls.append(1)
        if len(calls) == 1:
            raise RateLimited()
        return {"provider_id": "SM1"}

    with pytest.raises(RateLimited):
        store.dispatch("tenant:a", "dispatch:1", "effect:1", {}, "token", provider)
    assert store.dispatch(
        "tenant:a", "dispatch:1", "effect:1", {}, "token", provider
    )["provider_id"] == "SM1"
    assert len(calls) == 2
