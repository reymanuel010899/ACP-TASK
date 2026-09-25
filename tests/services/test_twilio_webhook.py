from libs.twilio_events import TwilioEventRepository
from libs.twilio_signature import (
    CallbackTokenCodec, compute_twilio_signature,
)
from services.twilio_webhook.app import TwilioWebhookProcessor


URL = "https://callbacks.example/twilio?token=ignored"
AUTH = "auth-secret"


def processor(tmp_path, clock=lambda: 100, suppressions=None):
    codec = CallbackTokenCodec("callback-secret", clock=clock)
    events = TwilioEventRepository(str(tmp_path / "events.db"), clock=clock)
    writer = None
    if suppressions is not None:
        writer = lambda **kwargs: suppressions.append(kwargs)
    return events, codec, TwilioWebhookProcessor(
        events, codec, lambda tenant, identity: AUTH,
        suppression_writer=writer,
    )


def test_invalid_signature_changes_no_state(tmp_path):
    events, codec, service = processor(tmp_path)
    token = codec.issue("tenant:a", "effect:1", "+18095550100", 200)
    pairs = [("AcpToken", token), ("MessageSid", "SM1"),
             ("MessageStatus", "delivered"), ("To", "+18095550100")]

    status, body = service.process(URL, "invalid", pairs)

    assert (status, body) == (403, {"error": "invalid_signature"})
    assert events.event_count("tenant:a") == 0


def test_callback_token_correlates_before_provider_id_and_replays_idempotently(tmp_path):
    events, codec, service = processor(tmp_path)
    token = codec.issue("tenant:a", "effect:1", "+18095550100", 200)
    pairs = [("AcpToken", token), ("MessageSid", "SM1"),
             ("MessageStatus", "delivered"), ("To", "+18095550100")]
    signature = compute_twilio_signature(AUTH, URL, pairs)

    assert service.process(URL, signature, pairs)[1]["duplicate"] is False
    assert service.process(URL, signature, pairs)[1]["duplicate"] is True
    assert events.event_count("tenant:a") == 1
    assert events.verdict("tenant:a", "effect:1")["status"] == "delivered"


def test_out_of_order_status_does_not_regress_terminal_verdict(tmp_path):
    events, codec, service = processor(tmp_path)
    token = codec.issue("tenant:a", "effect:1", "+18095550100", 200)
    for status in ("delivered", "queued"):
        pairs = [("AcpToken", token), ("MessageSid", "SM1"),
                 ("MessageStatus", status), ("To", "+18095550100")]
        service.process(URL, compute_twilio_signature(AUTH, URL, pairs), pairs)
    assert events.verdict("tenant:a", "effect:1")["status"] == "delivered"


def test_inbound_opt_out_is_immediate_and_replay_safe(tmp_path):
    suppressions = []
    events, codec, service = processor(tmp_path, suppressions=suppressions)
    token = codec.issue("tenant:a", "inbound:1", "+18095550100", 200)
    pairs = [("AcpToken", token), ("MessageSid", "SM-IN"),
             ("From", "+18095550999"), ("To", "+18095550100"),
             ("Body", "STOP")]
    signature = compute_twilio_signature(AUTH, URL, pairs)
    service.process(URL, signature, pairs)
    service.process(URL, signature, pairs)

    assert len(suppressions) == 1
    assert suppressions[0]["restrictive"] is True
