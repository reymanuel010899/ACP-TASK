import json

import pytest

from libs.connectors.base import (
    INTERACTIVE_AUTHORIZATION_UNSUPPORTED,
    PROVIDER_REVOCATION_UNSUPPORTED,
    REFRESH_AUTHORITY_UNSUPPORTED,
    ConnectorLimitation,
    CredentialConnector,
    OAuthCredentialConnector,
    StaticCredentialConnector,
)
from libs.connectors.google import GoogleCredentialConnector
from libs.connectors.slack import SlackCredentialConnector
from libs.integrations.catalog import (
    STATIC_ACCOUNT_CREDENTIAL,
    CapabilityUnavailable,
    VerifiedAccountState,
    VerifiedSender,
    account_state,
    derive_synthetic_scopes,
    synthetic_scope,
)
from services.action_broker.token_rotation import ManagedOAuthRotator


ACCOUNT_STATE = {
    "provider": "twilio",
    "account_id": "AC0000000000000000000000000000001",
    "status": "verified",
    "families": ["sms:send", "voice:call"],
    "senders": [
        {
            "sender_id": "+18095550100",
            "family": "sms",
            "countries": ["ES", "DO"],
        },
        {"sender_id": "+18095550200", "family": "sms", "countries": ["DO"]},
    ],
    "templates": ["appointment_reminder_es"],
}


class AccountConnector(StaticCredentialConnector):
    provider = "twilio"

    def __init__(self, state=None):
        self.state = state or dict(ACCOUNT_STATE)
        self.refresh_calls = []

    def verify_account(self, account_id, auth_token):
        return dict(self.state, account_id=account_id)

    def scope_catalog(self):
        return {
            "twilio.sms.send": ("twilio:sms:send",),
            "twilio.voice.call": ("twilio:voice:call",),
        }

    def refresh(self, refresh_token):  # pragma: no cover - must never run
        self.refresh_calls.append(refresh_token)
        return None


class StaticVault:
    def __init__(self, document):
        self.document = document

    def read_rotation_document(self, credential_id, service_identity):
        return 4, "active", dict(self.document)

    def compare_and_swap_rotation_document(self, *args):  # pragma: no cover
        raise AssertionError("a static credential must never be swapped")


def _sealed(document):
    return json.dumps(document).encode("utf-8")


def test_a_provider_with_no_redirect_or_refresh_still_satisfies_the_contract():
    connector = AccountConnector()

    assert isinstance(connector, CredentialConnector)
    assert connector.supports_interactive_authorization is False
    assert connector.supports_refresh is False
    assert connector.supports_provider_revocation is False
    assert connector.verify_account("AC1", "token")["status"] == "verified"


@pytest.mark.parametrize(
    "call, limitation",
    [
        (
            lambda connector: connector.authorization_url("state", None, ("a",)),
            INTERACTIVE_AUTHORIZATION_UNSUPPORTED,
        ),
        (
            lambda connector: connector.exchange_code("code", "verifier"),
            INTERACTIVE_AUTHORIZATION_UNSUPPORTED,
        ),
        (
            lambda connector: CredentialConnector.refresh(connector, "token"),
            REFRESH_AUTHORITY_UNSUPPORTED,
        ),
        (
            lambda connector: connector.revoke("token"),
            PROVIDER_REVOCATION_UNSUPPORTED,
        ),
    ],
)
def test_an_unsupported_oauth_mechanism_names_its_limitation(call, limitation):
    connector = AccountConnector()

    with pytest.raises(ConnectorLimitation) as raised:
        call(connector)

    assert raised.value.limitation == limitation
    assert raised.value.provider == "twilio"


def test_oauth_providers_keep_their_authorization_refresh_and_revoke_contract():
    for connector_class in (GoogleCredentialConnector, SlackCredentialConnector):
        assert issubclass(connector_class, OAuthCredentialConnector)
        assert connector_class.supports_interactive_authorization is True
        assert connector_class.supports_refresh is True
        assert connector_class.supports_provider_revocation is True
        for method in ("authorization_url", "exchange_code", "refresh", "revoke"):
            assert method in vars(connector_class)


def test_a_static_credential_is_sealed_stored_and_resolved_without_refreshing():
    connector = AccountConnector()
    scopes = sorted(derive_synthetic_scopes(account_state(ACCOUNT_STATE)))
    sealed = _sealed({
        "account_id": ACCOUNT_STATE["account_id"],
        "auth_token": "static-auth-token",
        "granted_scopes": scopes,
        "token_type": "account",
    })

    authority = STATIC_ACCOUNT_CREDENTIAL.authority(sealed, connector)

    assert authority.access_token == "static-auth-token"
    assert authority.account_id == ACCOUNT_STATE["account_id"]
    assert "twilio:sender:+18095550100" in authority.granted_scopes
    assert connector.refresh_calls == []


@pytest.mark.parametrize(
    "document, message",
    [
        ({"auth_token": "t"}, "provider account identity is unavailable"),
        ({"account_id": "AC1"}, "provider access authority is unavailable"),
    ],
)
def test_a_static_credential_missing_either_half_holds_no_authority(
    document, message,
):
    with pytest.raises(PermissionError) as raised:
        STATIC_ACCOUNT_CREDENTIAL.authority(_sealed(document))

    assert str(raised.value) == message


def test_rotating_a_provider_with_no_refresh_authority_names_the_limitation():
    vault = StaticVault({
        "account_id": "AC1", "auth_token": "static-auth-token",
    })
    rotator = ManagedOAuthRotator(vault, AccountConnector(), clock=lambda: 200)

    result = rotator.rotate("conn:twilio", "cred:twilio", "service:broker")

    assert result == {
        "credential_version": 4,
        "status": "active",
        "limitation": REFRESH_AUTHORITY_UNSUPPORTED,
    }


def test_an_oauth_provider_missing_its_refresh_token_still_fails_closed():
    class RefreshingConnector:
        supports_refresh = True

    vault = StaticVault({"access_token": "xoxb-current", "expires_at": 0})
    rotator = ManagedOAuthRotator(
        vault, RefreshingConnector(), clock=lambda: 200
    )

    with pytest.raises(PermissionError) as raised:
        rotator.rotate("conn:slack", "cred:slack", "service:broker")

    assert str(raised.value) == "refresh authority is unavailable"


def test_synthetic_scopes_are_derived_per_family_sender_geography_and_template():
    scopes = derive_synthetic_scopes(account_state(ACCOUNT_STATE))

    assert scopes == frozenset({
        "twilio:sms:send",
        "twilio:voice:call",
        "twilio:sender:+18095550100",
        "twilio:sender:+18095550200",
        "twilio:geo:ES",
        "twilio:geo:DO",
        "twilio:template:appointment_reminder_es",
    })


def test_disabling_one_sender_removes_exactly_that_senders_authority():
    disabled = dict(ACCOUNT_STATE, senders=[
        dict(ACCOUNT_STATE["senders"][0], enabled=False),
        ACCOUNT_STATE["senders"][1],
    ])

    before = derive_synthetic_scopes(account_state(ACCOUNT_STATE))
    after = derive_synthetic_scopes(account_state(disabled))

    # The disabled sender and the geography only it could reach are gone; the
    # other sender on the same account, and the family itself, are untouched.
    assert before - after == frozenset({
        "twilio:sender:+18095550100", "twilio:geo:ES",
    })
    assert "twilio:sender:+18095550200" in after
    assert "twilio:sms:send" in after


def test_an_account_that_is_not_verified_derives_no_authority_at_all():
    for status in ("unverified", "suspended", "unavailable"):
        state = account_state(dict(ACCOUNT_STATE, status=status))

        assert derive_synthetic_scopes(state) == frozenset()


def test_a_sender_whose_family_is_not_live_carries_no_authority():
    state = account_state(dict(
        ACCOUNT_STATE, families=["voice:call"], templates=[],
    ))

    scopes = derive_synthetic_scopes(state)

    # Both senders belong to the sms family, which is not live, so neither
    # they nor the destinations they reach are authority.
    assert scopes == frozenset({"twilio:voice:call"})


def test_verified_account_state_refuses_shapes_it_cannot_derive_from():
    with pytest.raises(CapabilityUnavailable):
        account_state({"provider": "twilio"})
    with pytest.raises(CapabilityUnavailable):
        account_state("not a mapping")
    with pytest.raises(ValueError):
        VerifiedAccountState(
            provider="twilio", account_id="AC1", status="made_up",
        )
    with pytest.raises(ValueError):
        VerifiedAccountState(
            provider="twilio", account_id="AC1", status="verified",
            families=frozenset({"sms"}),
        )


def test_a_synthetic_scope_is_a_namespaced_three_part_string():
    assert synthetic_scope("twilio", "sms", "send") == "twilio:sms:send"
    assert synthetic_scope("twilio", "sender", "+1809") == "twilio:sender:+1809"
    with pytest.raises(ValueError):
        synthetic_scope("twilio", "sen:der", "+1809")
    with pytest.raises(ValueError):
        synthetic_scope("twilio", "sender", "")


def test_a_verified_sender_defaults_to_enabled_and_no_destinations():
    sender = VerifiedSender(sender_id="+18095550100", family="sms")

    assert sender.enabled is True
    assert sender.countries == frozenset()
