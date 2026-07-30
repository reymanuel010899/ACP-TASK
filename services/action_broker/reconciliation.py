"""Bounded reconciliation for Slack writes with ambiguous dispatch outcomes."""

from libs.connectors.slack import SlackRateLimitError


class SlackReconciler(object):
    def __init__(self, capability_gateway):
        self.gateway = capability_gateway

    def reconcile(self, attempt):
        try:
            observed = self.gateway.find_effect(**{
                key: attempt.get(key) for key in (
                    "connection_id", "channel_id", "user_id", "capability_id",
                    "approved_payload_hash", "dispatch_started_at",
                    "dispatch_ended_at",
                ) if attempt.get(key) is not None
            })
        except SlackRateLimitError as exc:
            return {
                "execution_status": "execution_unknown",
                "verification_status": "pending",
                "retry_safe": False,
                "retry_after": exc.retry_after,
            }
        outcome = observed.get("outcome") if isinstance(observed, dict) else None
        if outcome == "found" and observed.get("provider_id"):
            result = {
                "execution_status": "completed",
                "verification_status": "pending",
                "provider_id": observed["provider_id"],
                "retry_safe": False,
            }
            if observed.get("receipt") is not None:
                result["receipt"] = observed["receipt"]
            if observed.get("attestation") is not None:
                result["attestation"] = observed["attestation"]
            return result
        if outcome == "absent" and observed.get("complete_interval") is True:
            return {
                "execution_status": "queued",
                "verification_status": "pending",
                "retry_safe": True,
            }
        return {
            "execution_status": "execution_unknown",
            "verification_status": "pending",
            "retry_safe": False,
        }
