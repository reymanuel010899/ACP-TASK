from services.twilio_webhook.app import InboundVoiceService


def test_unroutable_call_never_uses_default_tenant():
    service = InboundVoiceService(identity_owner_resolver=lambda *_: None)
    result = service.answer({"To": "+15550000000", "From": "+15551111111"}, event_time=100)
    assert result.state == "unrouted"
    assert "We cannot route your call" in result.twiml


def test_known_caller_gets_disclosure_and_empty_contacts_projection():
    service = InboundVoiceService(identity_owner_resolver=lambda *_: "tenant-1",
                                  public_corpus_resolver=lambda tenant: "Public hours only")
    result = service.answer({"To": "+15550000000", "From": "+15551111111"}, event_time=100)
    assert result.state == "disclosure_pending"
    assert result.principal.kind == "external_caller"
    assert result.capability_projection.isdisjoint({"contacts.search", "contacts.get"})
    assert "This call uses an AI assistant" in result.twiml


def test_spoken_stop_only_creates_restrictive_suppression():
    writes = []
    service = InboundVoiceService(lambda *_: "tenant-1", suppression_writer=lambda **v: writes.append(v))
    service.spoken_stop("tenant-1", "+15551111111")
    assert writes == [{"tenant_id": "tenant-1", "address": "+15551111111", "channel": "voice", "source": "spoken_request", "restrictive": True}]


def test_emergency_stop_is_transfer_only():
    service = InboundVoiceService(lambda *_: "tenant-1", emergency_stop=lambda tenant: True)
    result = service.answer({"To": "+15550000000", "From": "+15551111111"}, event_time=100)
    assert result.state == "agent_unavailable"
    assert result.transfer_only is True
