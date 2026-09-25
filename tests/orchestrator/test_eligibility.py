from datetime import datetime, timezone

from agents.orchestrator.eligibility import JurisdictionRuleTable, LiveEligibilityEvaluator


NOW = int(datetime(2026, 8, 6, 16, 0, tzinfo=timezone.utc).timestamp())


def effect(**changes):
    value = {
        "tenant_id": "tenant:a", "capability_id": "twilio.sms.send",
        "sender_id": "+18095550100", "contact_version": "v1",
        "approved_contact_version": "v1", "channel": "sms",
        "purpose": "transactional", "market": "US",
        "plausible_timezones": ["America/Los_Angeles"],
    }
    value.update(changes)
    return value


def rules():
    return JurisdictionRuleTable([{
        "rule_id": "us-test-v1", "jurisdiction": "US", "channel": "all",
        "purpose": "all", "priority": 1, "contact_hour_start": 8,
        "contact_hour_end": 21, "enabled": True,
    }])


def evaluator(consent=lambda _effect: {"eligible": True, "reason": "eligible"}, **kwargs):
    return LiveEligibilityEvaluator(consent, rules(), clock=lambda: NOW, **kwargs)


def test_eligible_effect_passes_with_rule_and_zone_evidence():
    decision = evaluator().evaluate(effect())
    assert decision.allowed is True
    assert decision.applied_rule_id == "us-test-v1"


def test_each_mutable_denial_has_a_named_reason_not_stale_policy():
    assert evaluator(consent=lambda _e: {"eligible": False, "reason": "suppressed_by_optout"}).evaluate(effect()).reason == "suppressed_by_optout"
    assert evaluator().evaluate(effect(contact_version="v2")).reason == "contact_version_changed"
    assert evaluator(registry_reader=lambda _e: {"fresh": False}).evaluate(effect()).reason == "registry_scrub_stale"


def test_low_confidence_location_uses_intersection_and_defers():
    decision = evaluator().evaluate(effect(
        plausible_timezones=["America/Los_Angeles", "Pacific/Honolulu"]
    ))
    assert decision.allowed is False
    assert decision.reason == "quiet_hours"
    assert decision.deferred_until > NOW


def test_freeform_whatsapp_window_is_checked_at_dispatch_time():
    decision = evaluator().evaluate(effect(
        capability_id="twilio.whatsapp.freeform.send", channel="whatsapp",
        session_window_expires_at=NOW - 1,
    ))
    assert decision.reason == "whatsapp_session_closed"
