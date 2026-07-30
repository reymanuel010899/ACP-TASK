"""Tests for scoped, revocable, audited agent access to vault credentials.

Covers grants, access requests, revocation, ownership checks, and the audit
trail (unit U7, Decision 8).
"""

import os
import threading

import pytest
import requests

from libs.vault_client import VaultClient
from vault import crypto
from vault.app import make_server

TEST_ITERATIONS = 1000


def base_url(server):
    host, port = server.server_address[:2]
    return "http://%s:%d" % (host, port)


@pytest.fixture
def vault():
    server = make_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def client(vault):
    return VaultClient(base_url(vault))


@pytest.fixture
def owned_credential(client):
    """A user with a stored credential; returns (user, credential_id, dek,
    plaintext)."""
    user = "ed25519_owner"
    dek, _ = client.register_user_keyring(
        "pw", user, os.urandom(32), iterations=TEST_ITERATIONS
    )
    plaintext = b'{"smtp_password": "hunch-mallow-42"}'
    ciphertext, nonce = crypto.encrypt_data(plaintext, dek)
    resp = client.store_credential(user, "smtp", "password", ciphertext, nonce)
    return user, resp["credential_id"], dek, plaintext


# ---------------------------------------------------------------------------
# Unit U4 deviation (documented R10 exception, see vault/app.py's module
# docstring): the vault's local, in-memory audit log (vault/audit_log.py) is
# gone -- GET /audit now PROXIES to the central Audit & Compliance service
# instead of reading a local list (KTD3). The plain `vault`/`client` fixtures
# above have no audit_url configured, so they correctly see an empty
# NullAuditClient result for GET /audit -- that's expected, not a bug. The
# audit-observing tests below need a real (ephemeral) central audit service
# wired via audit_url, and read that service's entry shape directly:
# activity_type "credential.access" (not the old local "access"),
# resource_id (not "credential_id"), and NEWEST-FIRST ordering (the reverse
# of the old vault-local log's oldest-first order).
# ---------------------------------------------------------------------------


@pytest.fixture
def audit_server():
    from audit.app import make_server as make_audit_server

    server = make_audit_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def audited_vault(audit_server):
    server = make_server(port=0, audit_url=base_url(audit_server))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def audited_client(audited_vault):
    return VaultClient(base_url(audited_vault))


@pytest.fixture
def audited_owned_credential(audited_client):
    user = "ed25519_owner"
    dek, _ = audited_client.register_user_keyring(
        "pw", user, os.urandom(32), iterations=TEST_ITERATIONS
    )
    plaintext = b'{"smtp_password": "hunch-mallow-42"}'
    ciphertext, nonce = crypto.encrypt_data(plaintext, dek)
    resp = audited_client.store_credential(
        user, "smtp", "password", ciphertext, nonce
    )
    return user, resp["credential_id"], dek, plaintext


# Scenario 9: grant -> access granted, audited -------------------------------


def test_grant_then_agent_access_granted_and_audited(
    audited_client, audited_owned_credential
):
    user, credential_id, dek, plaintext = audited_owned_credential
    grant = audited_client.grant_access(
        credential_id, "agent_mailer", scope="read", granted_by=user
    )
    assert grant["grant_id"]

    result = audited_client.request_access(credential_id, "agent_mailer")
    assert result["access_granted"] is True
    ciphertext = crypto.b64decode(result["encrypted_data"])
    nonce = crypto.b64decode(result["nonce"])
    assert crypto.decrypt_data(ciphertext, nonce, dek) == plaintext

    entries = audited_client.get_audit("agent_mailer")
    assert any(
        e["resource_id"] == credential_id
        and e["activity_type"] == "credential.access"
        and e["status"] == "granted"
        for e in entries
    )


# Regression: base64 principal_ids with "/" in the revoke path (B.5 URL fix) --


def test_revoke_agent_whose_principal_id_contains_slash(client, owned_credential):
    """A principal_id is a base64 ed25519 key that can contain '/'. The revoke
    path segment must be URL-encoded client-side or the slash splits the route
    and revoke 404s. Grant, then revoke an agent whose id has a literal '/'."""
    user, credential_id, _dek, _plaintext = owned_credential
    agent = "ab/cd+ef/gh"  # forced slashes, the shape base64 keys produce
    client.grant_access(credential_id, agent, scope="read", granted_by=user)
    # access works before revoke
    assert client.request_access(credential_id, agent)["access_granted"] is True
    # revoke must reach the right route despite the slashes (no 404)
    revoked = client.revoke_access(credential_id, agent)
    assert revoked["revoked"] is True
    # access denied after revoke
    denied = client.request_access(credential_id, agent)
    assert denied["access_granted"] is False


# Scenario 10: no grant -> denied 403, audited -------------------------------


def test_access_without_grant_denied_and_audited(
    audited_client, audited_owned_credential
):
    _user, credential_id, _dek, _plaintext = audited_owned_credential

    result = audited_client.request_access(credential_id, "agent_sneaky")
    assert result["access_granted"] is False
    assert result["status_code"] == 403
    assert "encrypted_data" not in result

    entries = audited_client.get_audit("agent_sneaky")
    assert any(
        e["resource_id"] == credential_id
        and e["activity_type"] == "credential.access"
        and e["status"] == "denied"
        for e in entries
    )


# Scenario 11: revoke -> subsequent access denied ----------------------------


def test_revoke_grant_then_access_denied(client, owned_credential):
    user, credential_id, _dek, _plaintext = owned_credential
    client.grant_access(
        credential_id, "agent_temp", scope="read", granted_by=user
    )
    assert client.request_access(credential_id, "agent_temp")[
        "access_granted"
    ] is True

    client.revoke_access(credential_id, "agent_temp")

    result = client.request_access(credential_id, "agent_temp")
    assert result["access_granted"] is False
    assert result["status_code"] == 403


# Scenario 12: non-owner cannot grant ----------------------------------------


def test_non_owner_grant_rejected_403(client, vault, owned_credential):
    _user, credential_id, _dek, _plaintext = owned_credential
    resp = requests.post(
        base_url(vault) + "/credentials/%s/grants" % credential_id,
        json={
            "agent_principal_id": "agent_evil",
            "scope": "read",
            "granted_by": "ed25519_mallory",  # not the credential owner
        },
        timeout=5,
    )
    assert resp.status_code == 403
    # And the agent still cannot access
    result = client.request_access(credential_id, "agent_evil")
    assert result["access_granted"] is False


def test_grant_on_unknown_credential_404(client):
    with pytest.raises(requests.HTTPError) as excinfo:
        client.grant_access(
            "no-such-credential", "agent_x", scope="read", granted_by="u"
        )
    assert excinfo.value.response.status_code == 404


# Scenario 14: audit query by principal, in order ----------------------------


def test_audit_query_by_principal_returns_entries_in_order(
    audited_client, audited_owned_credential
):
    user, credential_id, _dek, _plaintext = audited_owned_credential
    # Unique per test run: the central audit.audit_log table (unlike the old
    # per-test in-memory list) persists across runs, and get_audit(principal)
    # filters ONLY by principal_id -- a fixed literal here would pick up
    # stale rows from a previous run and break the exact-sequence assertion
    # below (see tests/vault/conftest.py's docstring for the same class of
    # issue on vault's own tables).
    agent = "agent_audit_%s" % os.urandom(4).hex()
    unrelated_agent = "agent_unrelated_%s" % os.urandom(4).hex()

    # denied, then granted, then denied again (after revoke)
    audited_client.request_access(credential_id, agent)
    audited_client.grant_access(
        credential_id, agent, scope="read", granted_by=user
    )
    audited_client.request_access(credential_id, agent)
    audited_client.revoke_access(credential_id, agent)
    audited_client.request_access(credential_id, agent)

    entries = audited_client.get_audit(agent)
    access_entries = [
        e for e in entries if e["activity_type"] == "credential.access"
    ]
    # The central store returns NEWEST FIRST (unit U4's documented R10
    # exception -- the reverse of the old vault-local log's oldest-first
    # order) -- reverse before asserting the temporal sequence.
    chronological = list(reversed(access_entries))
    assert [e["status"] for e in chronological] == [
        "denied", "granted", "denied"
    ]
    for e in access_entries:
        assert e["principal_id"] == agent
        assert e["resource_id"] == credential_id
        assert "timestamp" in e

    # Other principals' entries are not included
    other = audited_client.get_audit(unrelated_agent)
    assert other == []
