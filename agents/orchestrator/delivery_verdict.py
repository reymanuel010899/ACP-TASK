"""Translate Twilio callbacks into delivery truth on the verification axis."""

import time


DELIVERED = frozenset({"delivered", "read", "completed"})
FAILED = frozenset({"undelivered", "failed", "busy", "no-answer", "canceled"})
# Twilio error codes that are durable destination evidence, not service faults.
DEAD_ADDRESS_CODES = frozenset({"21211", "21612", "21614", "30003", "30005", "30006"})
PROVIDER_OPTOUT_CODES = frozenset({"21610"})


class DeliveryVerdictService:
    def __init__(self, workflow_repository, suppression_writer=None,
                 correction_writer=None, clock=None,
                 deadlines=None):
        self.workflows = workflow_repository
        self.suppression_writer = suppression_writer
        self.correction_writer = correction_writer
        self.clock = clock or time.time
        self.deadlines = dict(deadlines or {
            "sms": 24 * 60 * 60, "whatsapp": 24 * 60 * 60,
            "voice": 2 * 60 * 60,
        })

    def apply(self, effect, status, error_code=None):
        verification = (
            "verified" if status in DELIVERED
            else "failed" if status in FAILED
            else "pending"
        )
        if verification == "pending":
            return verification
        self.workflows.set_verification_status(
            effect["workflow_revision_id"], effect["step_id"],
            effect["tenant_id"], verification,
        )
        code = str(error_code) if error_code is not None else None
        if verification == "failed" and self.suppression_writer:
            if code in PROVIDER_OPTOUT_CODES:
                self.suppression_writer(
                    tenant_id=effect["tenant_id"], address_id=effect["address_id"],
                    channel=effect["channel"], state="suppressed_by_optout",
                    reason_code="provider_optout", source="twilio_callback",
                )
            elif code in DEAD_ADDRESS_CODES:
                self.suppression_writer(
                    tenant_id=effect["tenant_id"], address_id=effect["address_id"],
                    channel=effect["channel"], state="suppressed_by_bounce",
                    reason_code="carrier_rejection", source="twilio_callback",
                )
        if self.correction_writer and effect.get("conversation_closed"):
            self.correction_writer(
                tenant_id=effect["tenant_id"], effect_id=effect["effect_id"],
                verification_status=verification, provider_status=status,
            )
        return verification

    def expire(self, effects):
        now = int(self.clock())
        expired = []
        for effect in effects:
            deadline = int(effect["accepted_at"]) + self.deadlines[effect["channel"]]
            if effect.get("verification_status") == "pending" and deadline <= now:
                self.workflows.set_verification_status(
                    effect["workflow_revision_id"], effect["step_id"],
                    effect["tenant_id"], "inconclusive",
                )
                expired.append(effect["effect_id"])
                if self.correction_writer and effect.get("conversation_closed"):
                    self.correction_writer(
                        tenant_id=effect["tenant_id"], effect_id=effect["effect_id"],
                        verification_status="inconclusive",
                        provider_status="deadline_elapsed",
                    )
        return expired
