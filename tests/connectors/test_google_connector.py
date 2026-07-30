"""Contract tests for the provider-neutral connector boundary (U2)."""

from urllib.parse import parse_qs, urlsplit

import pytest
import requests

from libs.config import ConfigurationError, get_google_oauth_config
from libs.connectors.base import (
    ProviderNetworkError,
    UnsupportedCapabilityError,
)
from libs.connectors.google import GoogleActionExecutor, GoogleCredentialConnector


class Response(object):
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload or {}
        self.text = "provider response"

    def json(self):
        return self._payload


class FakeHTTP(object):
    def __init__(self, responses=()):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def connector(http=None):
    return GoogleCredentialConnector(
        client_id="client-id",
        client_secret="client-secret",
        redirect_uri="https://app.example.test/oauth/google/callback",
        http=http or FakeHTTP(),
    )


def test_google_configuration_is_environment_only_and_fails_closed():
    config = get_google_oauth_config(
        {
            "GOOGLE_OAUTH_CLIENT_ID": "configured-id",
            "GOOGLE_OAUTH_CLIENT_SECRET": "configured-secret",
            "GOOGLE_OAUTH_REDIRECT_URI": "https://app.example.test/callback",
        }
    )
    assert config.client_id == "configured-id"
    assert config.redirect_uri == "https://app.example.test/callback"
    with pytest.raises(ConfigurationError):
        get_google_oauth_config({})


def test_authorization_url_binds_pkce_state_offline_and_incremental_scopes():
    url = connector().authorization_url(
        state="one-use-state",
        code_challenge="pkce-challenge",
        scopes=["openid", "https://www.googleapis.com/auth/calendar.events"],
    )
    query = parse_qs(urlsplit(url).query)

    assert query["client_id"] == ["client-id"]
    assert query["redirect_uri"] == [
        "https://app.example.test/oauth/google/callback"
    ]
    assert query["state"] == ["one-use-state"]
    assert query["code_challenge"] == ["pkce-challenge"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["access_type"] == ["offline"]
    assert query["include_granted_scopes"] == ["true"]
    assert set(query["scope"][0].split(" ")) == {
        "openid",
        "https://www.googleapis.com/auth/calendar.events",
    }


def test_exchange_and_refresh_report_google_actual_authority_without_fake_ttl():
    http = FakeHTTP(
        [
            Response(
                payload={
                    "access_token": "access-one",
                    "refresh_token": "refresh-one",
                    "expires_in": 3599,
                    "scope": "scope.a scope.b",
                    "token_type": "Bearer",
                }
            ),
            Response(
                payload={
                    "access_token": "access-two",
                    "expires_in": 1800,
                    "scope": "scope.a",
                    "token_type": "Bearer",
                }
            ),
        ]
    )
    google = connector(http)

    exchanged = google.exchange_code("code", "verifier")
    refreshed = google.refresh("refresh-one")

    assert exchanged.expires_in == 3599
    assert exchanged.granted_scopes == frozenset({"scope.a", "scope.b"})
    assert exchanged.refresh_token == "refresh-one"
    assert refreshed.expires_in == 1800
    assert refreshed.granted_scopes == frozenset({"scope.a"})
    assert refreshed.refresh_token is None
    assert "scope" not in http.calls[1][2]["data"]
    assert "expires_in" not in http.calls[1][2]["data"]


def test_revoke_and_network_failures_are_typed():
    http = FakeHTTP([Response(status=200), requests.ConnectionError("offline")])
    google = connector(http)
    google.revoke("refresh-token")

    with pytest.raises(ProviderNetworkError):
        google.refresh("refresh-token")


def test_revoke_treats_confirmed_invalid_token_as_already_revoked():
    google = connector(
        FakeHTTP([Response(status=400, payload={"error": "invalid_token"})])
    )
    assert google.revoke("stale-refresh-token") == "invalid_token"


@pytest.mark.parametrize(
    "capability,payload,response,expected_id",
    [
        ("gmail.send", {"raw": "base64-message"}, {"id": "msg-1"}, "msg-1"),
        (
            "calendar.create",
            {"calendar_id": "primary", "event": {"summary": "Interview"}},
            {"id": "evt-1"},
            "evt-1",
        ),
        (
            "drive.upload",
            {"name": "brief.txt", "content": b"hello", "mime_type": "text/plain"},
            {"id": "file-1"},
            "file-1",
        ),
    ],
)
def test_side_effects_route_through_action_executor(
    capability, payload, response, expected_id
):
    http = FakeHTTP([Response(payload=response)])
    executor = GoogleActionExecutor(http=http)

    receipt = executor.execute(
        capability, payload, {"access_token": "broker-only-access"}
    )

    assert receipt.provider == "google"
    assert receipt.capability_id == capability
    assert receipt.provider_id == expected_id
    assert http.calls[0][2]["headers"]["Authorization"] == (
        "Bearer broker-only-access"
    )


def test_high_level_gmail_and_calendar_inputs_are_compiled_for_google():
    http = FakeHTTP([
        Response(payload={"id": "msg-1"}),
        Response(payload={"id": "evt-1"}),
    ])
    executor = GoogleActionExecutor(http=http)

    executor.execute("gmail.send", {
        "to": "laura@example.com", "subject": "Entrevista", "body": "Mañana a las 10",
    }, {"access_token": "access"})
    executor.execute("calendar.create", {
        "summary": "Entrevista", "start": "2026-07-30T10:00:00-04:00",
        "end": "2026-07-30T10:30:00-04:00", "attendees": ["laura@example.com"],
    }, {"access_token": "access"})

    gmail_raw = http.calls[0][2]["json"]["raw"]
    assert isinstance(gmail_raw, str) and gmail_raw
    event = http.calls[1][2]["json"]
    assert event["summary"] == "Entrevista"
    assert event["attendees"] == [{"email": "laura@example.com"}]


def test_reads_return_only_filtered_fields_and_unsupported_fails_closed():
    http = FakeHTTP(
        [
            Response(
                payload={
                    "items": [
                        {
                            "id": "evt-1",
                            "summary": "Interview",
                            "start": {"dateTime": "2026-08-01T10:00:00Z"},
                            "end": {"dateTime": "2026-08-01T11:00:00Z"},
                            "attendees": [{"email": "secret@example.test"}],
                            "hangoutLink": "https://meet.example/secret",
                        }
                    ]
                }
            )
        ]
    )
    executor = GoogleActionExecutor(http=http)

    result = executor.read(
        "calendar.read",
        {"calendar_id": "primary"},
        {"access_token": "broker-only-access"},
    )

    assert result == {
        "items": [
            {
                "id": "evt-1",
                "summary": "Interview",
                "start": {"dateTime": "2026-08-01T10:00:00Z"},
                "end": {"dateTime": "2026-08-01T11:00:00Z"},
                "status": None,
            }
        ]
    }
    with pytest.raises(UnsupportedCapabilityError):
        executor.execute(
            "google.raw_request", {}, {"access_token": "broker-only-access"}
        )
