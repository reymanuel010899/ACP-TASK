import pytest

from libs.twilio_signature import CallbackTokenCodec, compute_twilio_signature


def test_callback_token_rejects_tampering_and_expiry():
    codec = CallbackTokenCodec("secret", clock=lambda: 100)
    token = codec.issue("tenant:a", "effect:1", "+1", 101)
    assert codec.decode(token)["effect_id"] == "effect:1"
    with pytest.raises(ValueError):
        codec.decode(token[:-1] + ("A" if token[-1] != "A" else "B"))
    expired = CallbackTokenCodec("secret", clock=lambda: 102)
    with pytest.raises(ValueError):
        expired.decode(token)


def test_signature_includes_repeated_form_values_deterministically():
    first = compute_twilio_signature("secret", "https://example.test/cb", [
        ("Foo", "b"), ("Foo", "a"), ("Bar", "1")
    ])
    second = compute_twilio_signature("secret", "https://example.test/cb", [
        ("Bar", "1"), ("Foo", "a"), ("Foo", "b")
    ])
    assert first == second
