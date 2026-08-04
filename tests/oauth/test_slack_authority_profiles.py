import pytest

from services.oauth.repository import OAuthRepository

NOW = 1_700_000_000


def _repository(tmp_path):
    return OAuthRepository(str(tmp_path / "oauth.sqlite3"))


def _user_profile(repository, enabled=True, owner="user:maria"):
    return repository.record_authority_profile(
        "org:acme", "conn:slack", "user", owner, "cred:user",
        ["search:read"], NOW, slack_subject_id="U1", enabled=enabled,
    )


def test_a_personal_profile_records_the_identity_it_acts_as(tmp_path):
    repository = _repository(tmp_path)

    profile = _user_profile(repository)

    assert profile["profile_kind"] == "user"
    assert profile["slack_subject_id"] == "U1"
    assert profile["consent_owner_principal_id"] == "user:maria"
    assert profile["granted_scopes"] == ["search:read"]
    assert profile["status"] == "active"


def test_a_personal_profile_cannot_exist_without_a_subject(tmp_path):
    repository = _repository(tmp_path)

    with pytest.raises(ValueError, match="needs its subject"):
        repository.record_authority_profile(
            "org:acme", "conn:slack", "user", "user:maria", "cred:user",
            ["search:read"], NOW,
        )


def test_the_subject_may_use_their_own_authority(tmp_path):
    repository = _repository(tmp_path)
    _user_profile(repository)

    decision = repository.authorize_personal_authority(
        "org:acme", "conn:slack", "user", "user:maria", "slack_search", NOW,
    )

    assert decision["allowed"] is True
    assert decision["reason"] == "requester_is_subject"


def test_another_tenant_member_cannot_borrow_a_personal_token(tmp_path):
    repository = _repository(tmp_path)
    _user_profile(repository)

    decision = repository.authorize_personal_authority(
        "org:acme", "conn:slack", "user", "user:bob", "slack_search", NOW,
        consent_owner_principal_id="user:maria",
    )

    assert decision["allowed"] is False
    assert decision["reason"] == "delegation_absent"


def test_a_delegation_is_bound_to_one_audience_family_and_expiry(tmp_path):
    repository = _repository(tmp_path)
    profile = _user_profile(repository)
    repository.grant_authority_delegation(
        "org:acme", profile["authority_profile_id"], "user:bob",
        "slack_search", "incident triage", "user:maria", NOW + 600, NOW,
    )

    def decide(principal, family, now):
        return repository.authorize_personal_authority(
            "org:acme", "conn:slack", "user", principal, family, now,
            consent_owner_principal_id="user:maria",
        )

    assert decide("user:bob", "slack_search", NOW)["allowed"] is True
    # A different person, a different family, or a later moment all deny.
    assert decide("user:carol", "slack_search", NOW)["allowed"] is False
    assert decide("user:bob", "slack_messaging", NOW)["allowed"] is False
    assert decide("user:bob", "slack_search", NOW + 601)["allowed"] is False


def test_a_delegation_must_expire_in_the_future(tmp_path):
    repository = _repository(tmp_path)
    profile = _user_profile(repository)

    with pytest.raises(ValueError, match="must expire in the future"):
        repository.grant_authority_delegation(
            "org:acme", profile["authority_profile_id"], "user:bob",
            "slack_search", "triage", "user:maria", NOW, NOW,
        )


def test_a_profile_lands_disabled_and_stays_denied_until_enabled(tmp_path):
    repository = _repository(tmp_path)
    _user_profile(repository, enabled=False)

    decision = repository.authorize_personal_authority(
        "org:acme", "conn:slack", "user", "user:maria", "slack_search", NOW,
    )

    assert decision["allowed"] is False
    assert decision["reason"] == "authority_profile_disabled"


def test_an_absent_profile_denies_rather_than_falling_back(tmp_path):
    repository = _repository(tmp_path)

    decision = repository.authorize_personal_authority(
        "org:acme", "conn:slack", "enterprise_admin", "user:maria",
        "slack_admin", NOW,
    )

    assert decision["allowed"] is False
    assert decision["reason"] == "authority_profile_absent"


def test_authority_is_scoped_to_its_tenant_and_connection(tmp_path):
    repository = _repository(tmp_path)
    _user_profile(repository)

    for tenant, connection in (
        ("org:other", "conn:slack"), ("org:acme", "conn:other"),
    ):
        assert repository.authorize_personal_authority(
            tenant, connection, "user", "user:maria", "slack_search", NOW,
        )["reason"] == "authority_profile_absent"
