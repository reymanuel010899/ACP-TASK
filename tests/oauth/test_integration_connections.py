import pytest

from services.oauth.repository import ConnectionConflict, OAuthRepository


def _repo(tmp_path):
    return OAuthRepository(str(tmp_path / "oauth.sqlite3"))


def test_multiple_slack_workspaces_are_distinct_and_selectable(tmp_path):
    repository = _repo(tmp_path)

    team_a = repository.upsert_installation(
        tenant_id="org:acme",
        principal_id="user:alice",
        provider="slack",
        app_id="app:tessera",
        team_id="T-A",
        credential_id="cred-a",
        granted_scopes=["chat:write"],
        enabled_capabilities=["slack.message.send"],
        now_ts=10,
    )
    team_b = repository.upsert_installation(
        tenant_id="org:acme",
        principal_id="user:alice",
        provider="slack",
        app_id="app:tessera",
        team_id="T-B",
        enterprise_id="E-1",
        credential_id="cred-b",
        granted_scopes=["channels:read"],
        enabled_capabilities=["slack.channels.list"],
        now_ts=11,
    )

    assert team_a["connection_id"] != team_b["connection_id"]
    assert repository.get_installation(team_b["connection_id"], "org:acme") == team_b
    assert [item["team_id"] for item in repository.list_installations(
        "org:acme", "user:alice", "slack"
    )] == ["T-A", "T-B"]
    assert team_b["enterprise_id"] == "E-1"


def test_same_slack_installation_cannot_cross_tenants(tmp_path):
    repository = _repo(tmp_path)
    kwargs = dict(
        principal_id="user:alice",
        provider="slack",
        app_id="app:tessera",
        team_id="T-A",
        credential_id="cred-a",
        granted_scopes=["chat:write"],
        enabled_capabilities=["slack.message.send"],
        now_ts=10,
    )
    repository.upsert_installation(tenant_id="org:acme", **kwargs)

    with pytest.raises(ConnectionConflict):
        repository.upsert_installation(tenant_id="org:other", **kwargs)


def test_installation_requires_an_explicit_tenant(tmp_path):
    repository = _repo(tmp_path)
    with pytest.raises(ValueError, match="tenant_id"):
        repository.upsert_installation(
            tenant_id="",
            principal_id="user:alice",
            provider="slack",
            app_id="app:tessera",
            team_id="T-A",
            credential_id="cred-a",
            granted_scopes=[],
            enabled_capabilities=[],
            now_ts=10,
        )


def test_disconnect_tombstones_instead_of_deleting(tmp_path):
    repository = _repo(tmp_path)
    connection = repository.upsert_installation(
        tenant_id="org:acme",
        principal_id="user:alice",
        provider="slack",
        app_id="app:tessera",
        team_id="T-A",
        credential_id="cred-a",
        granted_scopes=[],
        enabled_capabilities=[],
        now_ts=10,
    )

    assert repository.tombstone_installation(
        connection["connection_id"], "org:acme", 20
    )
    stored = repository.get_installation(connection["connection_id"], "org:acme")
    assert stored["status"] == "disconnected"
    assert stored["credential_id"] is None
