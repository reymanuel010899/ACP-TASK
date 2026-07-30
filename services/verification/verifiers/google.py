"""Google receipt verification through the brokered capability gateway."""

import hashlib
import json

from libs.connectors.base import ProviderError


def _hash(value):
    canonical = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class GoogleReceiptVerifier(object):
    """Ground a signed receipt without ever requesting a provider token."""

    def __init__(self, capability_gateway):
        self.gateway = capability_gateway

    def verify(self, attestation):
        receipt = attestation["provider_receipt"]
        if receipt.get("provider") != "google":
            return {
                "verdict": "rejected",
                "reasoning": "receipt provider is not Google",
            }
        try:
            observed = self.gateway.read_receipt(
                attestation["user_principal_id"],
                attestation["credential_id"],
                attestation["capability_id"],
                receipt["provider_id"],
            )
        except (PermissionError, ProviderError):
            return {
                "verdict": "unverified",
                "reasoning": "provider receipt read was not authorized or available",
            }
        if not isinstance(observed, dict):
            return {
                "verdict": "unverified",
                "reasoning": "provider returned no checkable receipt",
            }

        exact = {
            "provider": "google",
            "capability_id": attestation["capability_id"],
            "provider_id": receipt["provider_id"],
            "user_principal_id": attestation["user_principal_id"],
            "credential_id": attestation["credential_id"],
        }
        for field, expected in exact.items():
            if observed.get(field) != expected:
                return {
                    "verdict": "rejected",
                    "reasoning": "provider receipt %s does not match" % field,
                }

        if "provider_timestamp" in receipt and observed.get(
            "provider_timestamp"
        ) != receipt["provider_timestamp"]:
            return {
                "verdict": "rejected",
                "reasoning": "provider receipt timestamp does not match",
            }
        observed_timestamp = observed.get("provider_timestamp")
        if (
            "provider_timestamp" not in receipt
            and isinstance(observed_timestamp, (int, float))
            and abs(observed_timestamp - attestation["executed_at"]) > 300
        ):
            return {
                "verdict": "rejected",
                "reasoning": "provider receipt timestamp is outside execution window",
            }
        account_hash = receipt.get("provider_account_hash")
        if account_hash is not None:
            observed_account = observed.get("provider_account_id")
            if not isinstance(observed_account, str) or _hash(
                observed_account
            ) != account_hash:
                return {
                    "verdict": "rejected",
                    "reasoning": "provider account does not match",
                }

        material = observed.get("material")
        material = material if isinstance(material, dict) else {}
        for field, expected_hash in attestation["material_hashes"].items():
            if field not in material or _hash(material[field]) != expected_hash:
                return {
                    "verdict": "rejected",
                    "reasoning": "provider material %s does not match" % field,
                }
        return {
            "verdict": "verified",
            "reasoning": "broker signature and Google receipt fields match",
        }
