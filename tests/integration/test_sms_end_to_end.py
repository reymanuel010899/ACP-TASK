from agents.orchestrator.dispatch_ledger import DispatchLedger
from libs.connectors.twilio import TwilioActionExecutor
from libs.twilio_events import TwilioEventRepository
from libs.twilio_signature import CallbackTokenCodec, compute_twilio_signature
from services.twilio_webhook.app import TwilioWebhookProcessor


SID = "AC" + "1" * 32
URL = "https://callbacks.example/twilio/status"


class Response:
    status_code = 201
    headers = {}
    def json(self): return {"sid": "SM" + "2" * 32, "status": "queued"}


class HTTP:
    def __init__(self): self.calls = 0
    def request(self, *_args, **_kwargs): self.calls += 1; return Response()


def test_one_literal_sms_reaches_one_provider_create_and_later_delivery_truth(tmp_path):
    clock = lambda: 100
    codec = CallbackTokenCodec("callback-secret", clock=clock)
    token = codec.issue("tenant:a", "effect:1", "+18095550100", 200)
    ledger = DispatchLedger(str(tmp_path / "dispatch.db"), clock=clock)
    http = HTTP()
    executor = TwilioActionExecutor(http=http, dispatch_ledger=ledger)
    payload = {
        "to": "+18095550101", "from": "+18095550100", "body": "Hola",
        "status_callback": URL + "?token=" + token,
    }
    receipt = executor.execute("twilio.sms.send", payload, {
        "account_id": SID, "access_token": "auth-secret",
        "tenant_id": "tenant:a", "dispatch_key": "dispatch:1",
        "effect_id": "effect:1", "callback_token": token,
    })
    assert receipt["status"] == "queued"
    assert http.calls == 1

    events = TwilioEventRepository(str(tmp_path / "events.db"), clock=clock)
    webhook = TwilioWebhookProcessor(
        events, codec, lambda _tenant, _identity: "auth-secret"
    )
    pairs = [("AcpToken", token), ("MessageSid", receipt["provider_id"]),
             ("MessageStatus", "delivered"), ("To", "+18095550100")]
    signature = compute_twilio_signature("auth-secret", URL, pairs)
    assert webhook.process(URL, signature, pairs)[0] == 200
    assert events.verdict("tenant:a", "effect:1")["status"] == "delivered"
