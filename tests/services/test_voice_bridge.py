import json

import pytest

from services.voice_bridge.app import VoiceBridgeSession, VoiceBridgeTicketCodec, VoiceSessionStore


class Grok:
    def __init__(self): self.audio = []
    def append_audio(self, payload): self.audio.append(payload)


def test_mulaw_payload_passes_through_without_transcoding(tmp_path):
    grok = Grok()
    session = VoiceBridgeSession("tenant-1", "CA1", "MZ1", grok, frozenset())
    session.receive_twilio({"event": "media", "media": {"payload": "AQID"}})
    assert grok.audio == ["AQID"]
    assert session.twilio_audio("BAUG")["media"]["payload"] == "BAUG"


def test_voice_tool_projection_is_bound_and_has_no_contacts():
    called = []
    session = VoiceBridgeSession("tenant-1", "CA1", "MZ1", Grok(), {"public.lookup", "transfer.request"},
                                 tool_executor=lambda name, args: called.append((name, args)) or {"ok": True})
    assert session.execute_tool("public.lookup", {"q": "hours"}) == {"ok": True}
    with pytest.raises(PermissionError): session.execute_tool("contacts.search", {"q": "Ana"})
    with pytest.raises(PermissionError): session.execute_tool("admin.grant", {})


def test_transcript_has_expiry_and_is_purged(tmp_path):
    store = VoiceSessionStore(tmp_path / "voice.db")
    store.append("tenant-1", "CA1", "caller", "hola", now=100, ttl_seconds=20)
    assert store.transcript("tenant-1", "CA1", now=119)
    assert store.purge_expired(now=121) == 1
    assert store.transcript("tenant-1", "CA1", now=121) == []


def test_bridge_ticket_is_expiring_and_tamper_evident():
    codec = VoiceBridgeTicketCodec("secret", clock=lambda: 100)
    token = codec.encode({"tenant_id": "tenant-1", "call_sid": "CA1", "expires_at": 101})
    assert codec.decode(token)["call_sid"] == "CA1"
    with pytest.raises(PermissionError): codec.decode(token + "x")
