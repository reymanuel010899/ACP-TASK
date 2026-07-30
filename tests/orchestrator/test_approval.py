"""Tests for the orchestrator approval gate + spend policy (unit U23).

Covers the full decision matrix of ``ApprovalGate.require``:

* below ``auto_approve_under``  -> auto-approved, callback NOT called
* between the two thresholds   -> callback consulted, its answer honored
* above ``hard_ceiling``       -> refused, callback NOT called (ceiling wins)

plus the exact-boundary semantics (strict ``<`` / strict ``>``), the CLI
prompt callback's input parsing (garbage input denies), non-empty reasons
on denial, and best-effort audit emission (a broken sink never breaks
the gate).
"""

from decimal import Decimal

import pytest

from agents.orchestrator.approval import (
    ApprovalGate,
    Decision,
    SpendPolicy,
    always_approve_callback,
    auto_deny_callback,
    cli_prompt_callback,
)


# -- test doubles ----------------------------------------------------------


class SpyCallback(object):
    """Approval callback that records every invocation."""

    def __init__(self, result=True):
        self.result = result
        self.calls = []

    def __call__(self, action, cost, details):
        self.calls.append((action, cost, details))
        return self.result


class RecordingAuditSink(object):
    """Audit client double matching libs.audit_client's ``log`` signature."""

    def __init__(self):
        self.entries = []

    def log(self, principal_id, activity_type, resource_id=None,
            status="ok", details=None):
        self.entries.append({
            "principal_id": principal_id,
            "activity_type": activity_type,
            "resource_id": resource_id,
            "status": status,
            "details": details,
        })


class ExplodingAuditSink(object):
    """Audit sink that always raises — the gate must shrug it off."""

    def log(self, *args, **kwargs):
        raise RuntimeError("audit service is down")


def make_policy():
    return SpendPolicy(
        auto_approve_under=Decimal("10.00"),
        hard_ceiling=Decimal("100.00"),
    )


# -- scenario 1: auto-approval below the threshold -------------------------


def test_cost_below_auto_approve_is_approved_without_callback():
    spy = SpyCallback(result=False)  # would deny if (wrongly) consulted
    gate = ApprovalGate(make_policy(), spy)

    decision = gate.require("buy.api_credits", Decimal("9.99"))

    assert isinstance(decision, Decision)
    assert decision.approved is True
    assert spy.calls == []


# -- scenario 2: between thresholds -> callback decides --------------------


def test_cost_between_thresholds_invokes_callback_and_honors_approve():
    spy = SpyCallback(result=True)
    gate = ApprovalGate(make_policy(), spy)

    decision = gate.require(
        "buy.compute", Decimal("50.00"), details={"provider": "acme"}
    )

    assert decision.approved is True
    assert spy.calls == [
        ("buy.compute", Decimal("50.00"), {"provider": "acme"})
    ]


def test_cost_between_thresholds_invokes_callback_and_honors_deny():
    spy = SpyCallback(result=False)
    gate = ApprovalGate(make_policy(), spy)

    decision = gate.require("buy.compute", Decimal("50.00"))

    assert decision.approved is False
    assert len(spy.calls) == 1


def test_auto_deny_and_always_approve_callbacks():
    gate_deny = ApprovalGate(make_policy(), auto_deny_callback)
    gate_ok = ApprovalGate(make_policy(), always_approve_callback)

    assert gate_deny.require("x", Decimal("50")).approved is False
    assert gate_ok.require("x", Decimal("50")).approved is True


# -- scenario 3: hard ceiling wins over everything -------------------------


def test_cost_above_hard_ceiling_refused_even_with_always_approve():
    spy = SpyCallback(result=True)
    gate = ApprovalGate(make_policy(), spy)

    decision = gate.require("buy.gpu_cluster", Decimal("100.01"))

    assert decision.approved is False
    assert spy.calls == []  # ceiling refusal never consults the callback
    assert "ceiling" in decision.reason.lower()

    gate2 = ApprovalGate(make_policy(), always_approve_callback)
    assert gate2.require("buy.gpu_cluster", Decimal("1000")).approved is False


# -- boundary semantics (strict comparisons) -------------------------------


def test_cost_exactly_auto_approve_under_goes_to_callback():
    # strict `<`: cost == auto_approve_under is NOT auto-approved
    spy = SpyCallback(result=True)
    gate = ApprovalGate(make_policy(), spy)

    decision = gate.require("buy.thing", Decimal("10.00"))

    assert decision.approved is True
    assert len(spy.calls) == 1


def test_cost_exactly_hard_ceiling_goes_to_callback():
    # strict `>`: cost == hard_ceiling is still eligible for approval
    spy = SpyCallback(result=True)
    gate = ApprovalGate(make_policy(), spy)

    decision = gate.require("buy.thing", Decimal("100.00"))

    assert decision.approved is True
    assert len(spy.calls) == 1


# -- scenario 4: cli_prompt_callback input parsing -------------------------


@pytest.mark.parametrize("answer", ["y", "yes", "s", "si", "Y", "YES", " si "])
def test_cli_prompt_callback_approves_on_yes_variants(answer):
    result = cli_prompt_callback(
        "buy.thing", Decimal("5"), None,
        input_fn=lambda prompt="": answer,
        print_fn=lambda *a, **k: None,
    )
    assert result is True


@pytest.mark.parametrize("answer", ["n", "no", "N", "NO"])
def test_cli_prompt_callback_denies_on_no_variants(answer):
    result = cli_prompt_callback(
        "buy.thing", Decimal("5"), None,
        input_fn=lambda prompt="": answer,
        print_fn=lambda *a, **k: None,
    )
    assert result is False


@pytest.mark.parametrize("answer", ["", "maybe", "yy", "ok", "approve", "1"])
def test_cli_prompt_callback_denies_on_garbage(answer):
    # anything unrecognized denies: safe default
    result = cli_prompt_callback(
        "buy.thing", Decimal("5"), None,
        input_fn=lambda prompt="": answer,
        print_fn=lambda *a, **k: None,
    )
    assert result is False


def test_cli_prompt_callback_via_monkeypatched_input(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "yes")
    assert cli_prompt_callback(
        "buy.thing", Decimal("5"), None, print_fn=lambda *a, **k: None
    ) is True


@pytest.mark.parametrize("exc", [EOFError, KeyboardInterrupt])
def test_cli_prompt_callback_denies_on_eof_or_interrupt(exc):
    """Closed/piped stdin (or ctrl-C) during the prompt must deny -- the
    safe default -- not propagate past the callback."""
    def raising_input(prompt=""):
        raise exc()

    result = cli_prompt_callback(
        "buy.thing", Decimal("5"), None,
        input_fn=raising_input, print_fn=lambda *a, **k: None,
    )
    assert result is False


def test_eof_during_the_gray_zone_prompt_still_produces_an_audit_entry():
    """The EOF-safe denial must still flow through ApprovalGate.require
    so the decision is recorded -- an uncaught EOFError would skip
    _record entirely, silently breaking the gate's audit trail."""
    def raising_input(prompt=""):
        raise EOFError()

    def callback(action, cost, details=None):
        return cli_prompt_callback(
            action, cost, details,
            input_fn=raising_input, print_fn=lambda *a, **k: None,
        )

    sink = RecordingAuditSink()
    gate = ApprovalGate(make_policy(), callback, audit_client=sink)

    decision = gate.require("buy.thing", Decimal("50"))

    assert decision.approved is False
    assert len(sink.entries) == 1
    assert sink.entries[0]["status"] == "denied"


# -- scenario 5: denials carry a human-readable reason ---------------------


def test_denied_decisions_carry_nonempty_reason():
    gate = ApprovalGate(make_policy(), auto_deny_callback)

    denied_by_callback = gate.require("buy.thing", Decimal("50"))
    denied_by_ceiling = gate.require("buy.thing", Decimal("500"))

    for decision in (denied_by_callback, denied_by_ceiling):
        assert decision.approved is False
        assert isinstance(decision.reason, str)
        assert decision.reason.strip() != ""


def test_approved_decisions_also_carry_reason():
    gate = ApprovalGate(make_policy(), always_approve_callback)
    assert gate.require("buy.thing", Decimal("1")).reason.strip() != ""
    assert gate.require("buy.thing", Decimal("50")).reason.strip() != ""


# -- scenario 6: audit emission (best-effort) ------------------------------


def test_decisions_are_emitted_to_configured_audit_sink():
    sink = RecordingAuditSink()
    gate = ApprovalGate(
        make_policy(), always_approve_callback, audit_client=sink
    )

    gate.require("buy.small", Decimal("1.00"))            # auto-approve
    gate.require("buy.medium", Decimal("50.00"))          # callback approve
    gate.require("buy.huge", Decimal("999.00"))           # ceiling refusal

    assert len(sink.entries) == 3
    small, medium, huge = sink.entries

    assert small["resource_id"] == "buy.small"
    assert small["status"] == "approved"
    assert small["details"]["cost"] == "1.00"

    assert medium["resource_id"] == "buy.medium"
    assert medium["status"] == "approved"

    assert huge["resource_id"] == "buy.huge"
    assert huge["status"] == "denied"
    assert huge["details"]["cost"] == "999.00"
    assert huge["details"]["reason"].strip() != ""


def test_exploding_audit_sink_does_not_break_require():
    gate = ApprovalGate(
        make_policy(), always_approve_callback,
        audit_client=ExplodingAuditSink(),
    )

    decision = gate.require("buy.thing", Decimal("1.00"))

    assert decision.approved is True  # gate result unaffected by audit


def test_no_audit_url_uses_null_client_and_still_works():
    gate = ApprovalGate(make_policy(), auto_deny_callback, audit_url=None)
    assert gate.require("buy.thing", Decimal("50")).approved is False


# -- money hygiene: Decimal, never float -----------------------------------


def test_policy_rejects_float_amounts():
    with pytest.raises(TypeError):
        SpendPolicy(auto_approve_under=0.5, hard_ceiling=Decimal("100"))
    with pytest.raises(TypeError):
        SpendPolicy(auto_approve_under=Decimal("1"), hard_ceiling=100.0)


def test_require_rejects_float_cost():
    gate = ApprovalGate(make_policy(), always_approve_callback)
    with pytest.raises(TypeError):
        gate.require("buy.thing", 5.0)
