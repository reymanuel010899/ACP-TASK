import json

import pytest

from libs.connectors.twilio import TwilioActionExecutor


SID = "AC" + "1" * 32
HX = "HX" + "2" * 32


class Response:
    status_code = 201
    headers = {}
    def json(self): return {"sid": "SM" + "3" * 32, "status": "queued"}


class HTTP:
    def __init__(self): self.calls = []
    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs)); return Response()


def context(): return {"account_id": SID, "access_token": "secret"}


def test_freeform_whatsapp_uses_body_and_channel_addresses():
    http = HTTP()
    result = TwilioActionExecutor(http=http).execute(
        "twilio.whatsapp.freeform.send",
        {"to": "+18095550101", "from": "+18095550100", "body": "Hola",
         "status_callback": "https://example.test/callback"}, context(),
    )
    data = http.calls[0][1]["data"]
    assert data["To"] == "whatsapp:+18095550101"
    assert data["From"] == "whatsapp:+18095550100"
    assert data["Body"] == "Hola"
    assert result["provider_id"].startswith("SM")


def test_template_send_uses_content_sid_and_canonical_variables_not_body():
    http = HTTP()
    TwilioActionExecutor(http=http).execute(
        "twilio.whatsapp.template.send",
        {"to": "+18095550101", "from": "+18095550100", "content_sid": HX,
         "content_variables": {"2": "B", "1": "A"},
         "status_callback": "https://example.test/callback"}, context(),
    )
    data = http.calls[0][1]["data"]
    assert data["ContentSid"] == HX
    assert data["ContentVariables"] == '{"1":"A","2":"B"}'
    assert "Body" not in data


def test_template_send_never_silently_falls_back_to_body():
    with pytest.raises(ValueError):
        TwilioActionExecutor(http=HTTP()).execute(
            "twilio.whatsapp.template.send",
            {"to": "+18095550101", "from": "+18095550100", "body": "fallback",
             "status_callback": "https://example.test/callback"}, context(),
        )
