from services.verification.verifiers.slack import SlackReceiptVerifier


class Gateway:
    def __init__(self, observed):
        self.observed = observed

    def read_receipt(self, *args):
        return dict(self.observed)


def _attestation():
    return {
        "user_principal_id": "user:alice",
        "credential_id": "cred:slack",
        "capability_id": "slack.message.send",
        "approved_payload_hash": "a" * 64,
        "provider_receipt": {
            "provider": "slack",
            "capability_id": "slack.message.send",
            "provider_id": "123.45",
            "team_id": "T1",
            "channel_id": "C1",
            "message_ts": "123.45",
        },
        "material_hashes": {"text": "b" * 64},
    }


def test_slack_receipt_verifies_exact_workspace_channel_and_material():
    verifier = SlackReceiptVerifier(Gateway({
        "provider": "slack", "capability_id": "slack.message.send",
        "provider_id": "123.45", "team_id": "T1", "channel_id": "C1",
        "message_ts": "123.45", "approved_payload_hash": "a" * 64,
        "material_hashes": {"text": "b" * 64},
    }))
    assert verifier.verify(_attestation())["verdict"] == "verified"


def test_slack_receipt_rejects_cross_workspace_observation():
    verifier = SlackReceiptVerifier(Gateway({
        "provider": "slack", "capability_id": "slack.message.send",
        "provider_id": "123.45", "team_id": "T-OTHER", "channel_id": "C1",
        "message_ts": "123.45", "approved_payload_hash": "a" * 64,
        "material_hashes": {"text": "b" * 64},
    }))
    result = verifier.verify(_attestation())
    assert result["verdict"] == "rejected"
    assert "team_id" in result["reasoning"]
