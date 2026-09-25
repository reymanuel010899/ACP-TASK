from libs.whatsapp_state import WhatsAppStateRepository, WINDOW_SECONDS


def test_inbound_event_opens_exactly_one_24_hour_window_and_replay_does_not_shorten(tmp_path):
    now = [100]
    repository = WhatsAppStateRepository(
        str(tmp_path / "wa.db"), clock=lambda: now[0]
    )
    first = repository.open_window("tenant:a", "address:1", "sender:1", "event:1")
    now[0] = 200
    second = repository.open_window(
        "tenant:a", "address:1", "sender:1", "event:2", received_at=50
    )
    assert first["expires_at"] == 100 + WINDOW_SECONDS
    assert second["expires_at"] == first["expires_at"]


def test_paused_template_is_unavailable_without_affecting_another(tmp_path):
    repository = WhatsAppStateRepository(str(tmp_path / "wa.db"), clock=lambda: 100)
    sid_a, sid_b = "HX" + "1" * 32, "HX" + "2" * 32
    repository.register_template("tenant:a", sid_a, "sender:1", "a", "es", "utility", "paused")
    repository.register_template("tenant:a", sid_b, "sender:1", "b", "es", "utility", "approved")
    assert repository.template("tenant:a", sid_a, "sender:1")["available"] is False
    assert repository.template("tenant:a", sid_b, "sender:1")["available"] is True
