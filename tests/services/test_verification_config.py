import pytest

from services.verification.app import load_broker_keys


def test_broker_keys_are_optional_only_outside_production():
    assert load_broker_keys(None, "test") == {}
    with pytest.raises(RuntimeError, match="required in production"):
        load_broker_keys(None, "production")
