import pytest

from libs.grok_realtime import GrokRealtimeProtocol


def test_realtime_session_is_pinned_mulaw_and_resumable():
    protocol = GrokRealtimeProtocol("grok-voice-2026-06-15", "eve")
    assert "model=grok-voice-2026-06-15" in protocol.url()
    update = protocol.session_update("Habla español o inglés.", [])
    assert update["session"]["audio"]["input"]["format"]["type"] == "audio/pcmu"
    assert update["session"]["resumption"]["enabled"] is True
    assert protocol.input_audio("AQID")["audio"] == "AQID"


def test_latest_model_is_refused():
    with pytest.raises(ValueError, match="pinned"):
        GrokRealtimeProtocol("grok-voice-latest", "eve")
