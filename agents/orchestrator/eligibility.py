"""Fresh per-effect eligibility, intentionally separate from binding policy."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class EligibilityDecision:
    allowed: bool
    reason: str
    deferred_until: Optional[int] = None
    applied_rule_id: Optional[str] = None
    resolved_timezones: tuple = ()


ALLOWED = EligibilityDecision(True, "eligible")


class LiveEligibilityEvaluator:
    """Evaluate mutable facts in a fixed, auditable fail-closed order."""

    def __init__(self, consent_reader, jurisdiction_rules, permission_reader=None,
                 frequency_reader=None, registry_reader=None, budget_reader=None,
                 control_plane=None, clock=None):
        self.consent_reader = consent_reader
        self.rules = jurisdiction_rules
        self.permission_reader = permission_reader
        self.frequency_reader = frequency_reader
        self.registry_reader = registry_reader
        self.budget_reader = budget_reader
        self.control_plane = control_plane
        self.clock = clock or (lambda: datetime.now(tz=timezone.utc).timestamp())

    def evaluate(self, effect):
        if self.control_plane is not None:
            decision = self.control_plane.dispatch_decision(
                effect["tenant_id"], effect["capability_id"],
                sender_id=effect.get("sender_id"),
            )
            if not decision:
                return EligibilityDecision(False, decision.reason)
        if self.permission_reader and not self.permission_reader(effect):
            return EligibilityDecision(False, "branch_permission_lost")
        if effect.get("approved_contact_version") != effect.get("contact_version"):
            return EligibilityDecision(False, "contact_version_changed")
        consent = self.consent_reader(effect)
        if not consent:
            return EligibilityDecision(False, "consent_unavailable")
        if not consent.get("eligible"):
            return EligibilityDecision(False, consent.get("reason") or "consent_denied")
        if self.registry_reader:
            registry = self.registry_reader(effect)
            if not registry or not registry.get("fresh"):
                return EligibilityDecision(False, "registry_scrub_stale")
            if registry.get("excluded"):
                return EligibilityDecision(False, "registry_excluded")
        rule = self.rules.resolve(effect)
        if rule is None:
            return EligibilityDecision(False, "jurisdiction_rule_unavailable")
        quiet = _quiet_hours_decision(effect, rule, int(self.clock()))
        if quiet is not None:
            return quiet
        if self.frequency_reader and not self.frequency_reader(effect, rule):
            return EligibilityDecision(False, "frequency_limit")
        if self.budget_reader and not self.budget_reader(effect):
            return EligibilityDecision(False, "budget_unavailable")
        if effect["capability_id"] == "twilio.whatsapp.freeform.send":
            if int(effect.get("session_window_expires_at") or 0) <= int(self.clock()):
                return EligibilityDecision(False, "whatsapp_session_closed")
        if effect["capability_id"] == "twilio.whatsapp.template.send":
            template = effect.get("template") or {}
            if not template.get("available"):
                return EligibilityDecision(False, "whatsapp_template_unavailable")
            if template.get("category") != effect.get("purpose"):
                return EligibilityDecision(False, "template_purpose_mismatch")
        return EligibilityDecision(
            True, "eligible", applied_rule_id=rule["rule_id"],
            resolved_timezones=tuple(sorted(effect.get("plausible_timezones") or ())),
        )


class JurisdictionRuleTable:
    def __init__(self, rows=()):
        self.rows = tuple(rows)

    def resolve(self, effect):
        market = effect.get("market")
        candidates = [
            row for row in self.rows
            if row.get("enabled") and row.get("jurisdiction") == market
            and row.get("channel") in (effect.get("channel"), "all")
            and row.get("purpose") in (effect.get("purpose"), "all")
        ]
        return sorted(candidates, key=lambda row: row.get("priority", 0), reverse=True)[0] if candidates else None


def _quiet_hours_decision(effect, rule, now_ts):
    zones = tuple(effect.get("plausible_timezones") or ())
    if not zones:
        return EligibilityDecision(False, "contact_location_uncertain")
    allowed_now = []
    next_candidates = []
    for name in zones:
        local = datetime.fromtimestamp(now_ts, tz=ZoneInfo(name))
        start, end = int(rule["contact_hour_start"]), int(rule["contact_hour_end"])
        allowed_now.append(start <= local.hour < end)
        if not allowed_now[-1]:
            days = 0 if local.hour < start else 1
            target = local.replace(hour=start, minute=0, second=0, microsecond=0)
            if days:
                from datetime import timedelta
                target += timedelta(days=1)
            next_candidates.append(int(target.timestamp()))
    # Low confidence means intersection: every plausible location must permit.
    if all(allowed_now):
        return None
    return EligibilityDecision(
        False, "quiet_hours", deferred_until=max(next_candidates or [now_ts + 3600]),
        applied_rule_id=rule["rule_id"], resolved_timezones=tuple(sorted(zones)),
    )
