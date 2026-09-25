import pytest

from libs.connectors.twilio import TwilioCredentialConnector


SID = "AC" + "1" * 32


class Response:
    def __init__(self, body, status=200):
        self.body = body
        self.status_code = status
        self.headers = {}

    def json(self):
        return self.body


class HTTP:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def test_verified_account_enumerates_owned_sender_families_and_callback_drift():
    http = HTTP([
        Response({"sid": SID, "status": "active", "owner_account_sid": "AC" + "2" * 32}),
        Response({"incoming_phone_numbers": [{
            "sid": "PN1", "phone_number": "+18095550100",
            "capabilities": {"SMS": True, "Voice": True},
            "sms_url": "https://old.example/inbound",
            "voice_url": "https://callbacks.example/voice",
        }]}),
    ])
    connector = TwilioCredentialConnector(
        http=http, expected_callback_base="https://callbacks.example"
    )

    state = connector.verify_account(SID, "secret")

    assert state["status"] == "verified"
    assert state["owner_account_sid"] == "AC" + "2" * 32
    assert state["families"] == ["sms:send", "voice:call"]
    assert {item["family"] for item in state["senders"]} == {"sms", "voice"}
    assert state["callback_drift"] == [{
        "sender_id": "+18095550100", "field": "sms_url"
    }]
    assert all(call[2]["auth"] == (SID, "secret") for call in http.calls)


def test_unverified_identity_input_fails_before_any_provider_call():
    http = HTTP([])
    with pytest.raises(ValueError):
        TwilioCredentialConnector(http=http).verify_account("not-a-sid", "secret")
    assert http.calls == []
