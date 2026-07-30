"""Independent Slack receipt verification through a brokered read gateway."""

from libs.connectors.base import ProviderError
from libs.connectors.slack import SlackRateLimitError


class SlackReceiptVerifier(object):
    def __init__(self, capability_gateway):
        self.gateway = capability_gateway

    def verify(self, attestation):
        receipt = attestation.get("provider_receipt", {})
        if receipt.get("provider") != "slack":
            return {"verdict": "rejected", "reasoning": "receipt provider is not Slack"}
        try:
            observed = self.gateway.read_receipt(
                attestation["user_principal_id"],
                attestation["credential_id"],
                attestation["capability_id"],
                receipt,
            )
        except SlackRateLimitError as exc:
            return {
                "verdict": "unverified",
                "reasoning": "Slack readback is rate limited",
                "retry_after": exc.retry_after,
            }
        except (PermissionError, ProviderError):
            return {
                "verdict": "unverified",
                "reasoning": "Slack receipt read was not authorized or available",
            }
        if not isinstance(observed, dict):
            return {"verdict": "unverified", "reasoning": "Slack returned no checkable receipt"}
        exact = {
            "provider": "slack",
            "capability_id": attestation["capability_id"],
            "provider_id": receipt.get("provider_id"),
            "team_id": receipt.get("team_id"),
            "channel_id": receipt.get("channel_id"),
            "approved_payload_hash": attestation["approved_payload_hash"],
        }
        if receipt.get("message_ts") is not None:
            exact["message_ts"] = receipt["message_ts"]
        for field, expected in exact.items():
            if observed.get(field) != expected:
                return {
                    "verdict": "rejected",
                    "reasoning": "Slack receipt %s does not match" % field,
                }
        observed_hashes = observed.get("material_hashes", {})
        for field, expected in attestation.get("material_hashes", {}).items():
            if observed_hashes.get(field) != expected:
                return {
                    "verdict": "rejected",
                    "reasoning": "Slack material %s does not match" % field,
                }
        return {
            "verdict": "verified",
            "reasoning": "broker signature and Slack receipt fields match",
        }
