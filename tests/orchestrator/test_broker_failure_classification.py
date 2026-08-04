import logging

import pytest

from libs.connectors.base import ProviderNetworkError
from libs.connectors.slack import SlackAPIError
from services.action_broker.app import _safe_provider_error


def test_a_missing_credential_names_reconnect_instead_of_a_provider_fault():
    status, body = _safe_provider_error(
        KeyError("managed OAuth credential not found")
    )

    assert status == 403
    assert body["error"] == "credential_unavailable"
    assert body["category"] == "auth"
    assert body["recovery"] == "reconnect_integration"


def test_an_unclassified_failure_names_its_type_and_is_logged(caplog):
    with caplog.at_level(logging.ERROR):
        status, body = _safe_provider_error(RuntimeError("something odd"))

    assert status == 502
    assert body["error_class"] == "RuntimeError"
    assert "unclassified provider failure" in caplog.text
    assert "RuntimeError" in caplog.text


@pytest.mark.parametrize("exc,expected", [
    (SlackAPIError("conversations.history", "not_in_channel", "membership"), 403),
    (SlackAPIError("conversations.history", "channel_not_found", "validation"), 422),
    (ProviderNetworkError("timeout"), 503),
    (PermissionError("denied"), 403),
])
def test_classified_failures_keep_their_existing_statuses(exc, expected):
    status, body = _safe_provider_error(exc)

    assert status == expected
    assert "error_class" not in body
