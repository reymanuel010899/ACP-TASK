import requests

from libs.connectors.twilio import TwilioActionExecutor


class Response:
    status_code = 201
    headers = {}
    def json(self): return {"sid": "CA123", "status": "queued"}


class HTTP:
    def __init__(self): self.calls = []
    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs)); return Response()


def test_voice_call_posts_literal_twilio_definition():
    http = HTTP()
    result = TwilioActionExecutor(http=http).execute("twilio.voice.call", {
        "to": "+15551234567", "from": "+15557654321",
        "status_callback": "https://hooks.example/voice", "twiml_url": "https://hooks.example/connect",
        "maximum_duration_seconds": 300, "ring_timeout_seconds": 20, "recording": False,
        "definition_hash": "a" * 64,
    }, {"account_id": "AC" + "1" * 32, "access_token": "secret"})
    assert result["provider_id"] == "CA123"
    data = http.calls[0][1]["data"]
    assert data["TimeLimit"] == "300"
    assert data["Timeout"] == "20"
    assert data["Record"] == "false"
    assert data["StatusCallbackEvent"] == ["initiated", "ringing", "answered", "completed"]


def test_terminate_call_posts_completed_status():
    http = HTTP()
    TwilioActionExecutor(http=http).terminate_call(
        "CA123", {"account_id": "AC" + "1" * 32, "access_token": "secret"}
    )
    assert http.calls[0][1]["data"] == {"Status": "completed"}
