"""Agent Marketplace hiring, revocation and rating tests (Phase B, U8).

Hiring creates a scoped grant owned by the agent marketplace; when a Vault
is wired in, credential scopes in the hire become real Vault grants (and
revoking the hire revokes Vault access too). Ratings are gated on having a
non-revoked hiring grant.

All servers run on EPHEMERAL ports (port=0), never fixed ports.
"""

import datetime
import threading

import pytest
import requests

from agent_marketplace.app import make_server as make_agent_marketplace_server
from libs.agent_marketplace_client import AgentMarketplaceClient
from registry.app import make_server as make_registry_server
from vault.app import make_server as make_vault_server

TIMEOUT = 5.0


def _start(server):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


def _url(server):
    host, port = server.server_address[:2]
    return "http://%s:%d" % (host, port)


def _register_user(registry_url, principal_id):
    resp = requests.post(
        "%s/auth/register" % registry_url,
        json={"principal_id": principal_id},
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, resp.text


def _register_agent(registry_url, principal_id, capabilities,
                    created_by="user:owner"):
    resp = requests.post(
        "%s/agents/register" % registry_url,
        json={
            "principal_id": principal_id,
            "created_by": created_by,
            "agent_card": {
                "name": principal_id,
                "description": "test agent %s" % principal_id,
                "capabilities": capabilities,
            },
        },
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, resp.text


def _store_credential(vault_url, user_principal_id, name="api-key"):
    """Store a (fake ciphertext) credential; the Vault never inspects it."""
    resp = requests.post(
        "%s/credentials" % vault_url,
        json={
            "name": name,
            "credential_type": "api_key",
            "encrypted_data": "ZmFrZS1jaXBoZXJ0ZXh0",
            "nonce": "ZmFrZS1ub25jZQ==",
            "user_principal_id": user_principal_id,
        },
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["credential_id"]


def _vault_access(vault_url, credential_id, agent_principal_id):
    return requests.post(
        "%s/credentials/%s/access" % (vault_url, credential_id),
        json={"agent_principal_id": agent_principal_id},
        timeout=TIMEOUT,
    )


# ---------------------------------------------------------------------------
# Fixtures (ephemeral ports only)
# ---------------------------------------------------------------------------


@pytest.fixture
def registry():
    server = make_registry_server(port=0)
    _start(server)
    yield _url(server)
    server.shutdown()
    server.server_close()


@pytest.fixture
def vault():
    server = make_vault_server(port=0)
    _start(server)
    yield _url(server)
    server.shutdown()
    server.server_close()


@pytest.fixture
def agent_marketplace(registry):
    """Agent marketplace connected to the registry, no vault."""
    server = make_agent_marketplace_server(port=0, registry_url=registry)
    _start(server)
    yield _url(server)
    server.shutdown()
    server.server_close()


@pytest.fixture
def agent_marketplace_with_vault(registry, vault):
    """Agent marketplace connected to both the registry and the vault."""
    server = make_agent_marketplace_server(
        port=0, registry_url=registry, vault_url=vault
    )
    _start(server)
    yield _url(server)
    server.shutdown()
    server.server_close()


@pytest.fixture
def seeded(registry):
    """A user and an agent registered in the Registry."""
    _register_user(registry, "user:owner")
    _register_user(registry, "user:alice")
    _register_agent(registry, "agent:helper", ["translation"])
    return registry


# ---------------------------------------------------------------------------
# 1-2. Hiring basics
# ---------------------------------------------------------------------------


class TestHiring:
    def test_hire_creates_active_grant_visible_to_both_sides(
        self, seeded, agent_marketplace
    ):
        client = AgentMarketplaceClient(agent_marketplace)
        grant = client.hire_agent(
            agent_principal_id="agent:helper",
            user_principal_id="user:alice",
            scoped_capabilities=["translation"],
        )
        assert grant["grant_id"]
        assert grant["status"] == "active"
        assert grant["created_at"]
        assert grant["scoped_capabilities"] == ["translation"]

        # The agent sees who hired it.
        agent_side = client.list_hirings(agent_principal_id="agent:helper")
        assert [g["grant_id"] for g in agent_side] == [grant["grant_id"]]
        assert agent_side[0]["user_principal_id"] == "user:alice"

        # The user sees its hires.
        user_side = client.list_hirings(user_principal_id="user:alice")
        assert [g["grant_id"] for g in user_side] == [grant["grant_id"]]
        assert user_side[0]["agent_principal_id"] == "agent:helper"

    def test_hire_nonexistent_agent_is_404(self, seeded, agent_marketplace):
        resp = requests.post(
            "%s/marketplace/hiring-grants" % agent_marketplace,
            json={
                "agent_principal_id": "agent:ghost",
                "user_principal_id": "user:alice",
                "scoped_capabilities": ["translation"],
            },
            timeout=TIMEOUT,
        )
        assert resp.status_code == 404, resp.text

    def test_invalid_hire_body_is_422(self, seeded, agent_marketplace):
        # Missing user_principal_id.
        resp = requests.post(
            "%s/marketplace/hiring-grants" % agent_marketplace,
            json={
                "agent_principal_id": "agent:helper",
                "scoped_capabilities": ["translation"],
            },
            timeout=TIMEOUT,
        )
        assert resp.status_code == 422, resp.text

        # scoped_capabilities not a list of non-empty strings.
        resp = requests.post(
            "%s/marketplace/hiring-grants" % agent_marketplace,
            json={
                "agent_principal_id": "agent:helper",
                "user_principal_id": "user:alice",
                "scoped_capabilities": "translation",
            },
            timeout=TIMEOUT,
        )
        assert resp.status_code == 422, resp.text

        # Malformed credential_scopes.
        resp = requests.post(
            "%s/marketplace/hiring-grants" % agent_marketplace,
            json={
                "agent_principal_id": "agent:helper",
                "user_principal_id": "user:alice",
                "scoped_capabilities": ["translation"],
                "credential_scopes": [{"scope": "read"}],
            },
            timeout=TIMEOUT,
        )
        assert resp.status_code == 422, resp.text

        # Unparseable expires_at.
        resp = requests.post(
            "%s/marketplace/hiring-grants" % agent_marketplace,
            json={
                "agent_principal_id": "agent:helper",
                "user_principal_id": "user:alice",
                "scoped_capabilities": ["translation"],
                "expires_at": "not-a-date",
            },
            timeout=TIMEOUT,
        )
        assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# 3-5. Vault-backed credential scopes + revocation
# ---------------------------------------------------------------------------


class TestVaultIntegration:
    def test_hire_with_credential_scopes_creates_vault_grant(
        self, seeded, vault, agent_marketplace_with_vault
    ):
        credential_id = _store_credential(vault, "user:alice")

        # Before hiring, the agent is denied access.
        denied = _vault_access(vault, credential_id, "agent:helper")
        assert denied.status_code == 403

        client = AgentMarketplaceClient(agent_marketplace_with_vault)
        grant = client.hire_agent(
            agent_principal_id="agent:helper",
            user_principal_id="user:alice",
            scoped_capabilities=["translation"],
            credential_scopes=[
                {"credential_id": credential_id, "scope": "read"},
            ],
        )
        assert grant["status"] == "active"

        # The hire produced a real Vault grant for the agent.
        allowed = _vault_access(vault, credential_id, "agent:helper")
        assert allowed.status_code == 200, allowed.text
        body = allowed.json()
        assert body["access_granted"] is True
        assert body["scope"] == "read"

    def test_revoke_by_hiring_user_revokes_vault_access_too(
        self, seeded, vault, agent_marketplace_with_vault
    ):
        credential_id = _store_credential(vault, "user:alice")
        client = AgentMarketplaceClient(agent_marketplace_with_vault)
        grant = client.hire_agent(
            agent_principal_id="agent:helper",
            user_principal_id="user:alice",
            scoped_capabilities=["translation"],
            credential_scopes=[
                {"credential_id": credential_id, "scope": "read"},
            ],
        )
        assert _vault_access(
            vault, credential_id, "agent:helper"
        ).status_code == 200

        revoked = client.revoke_hiring(grant["grant_id"], "user:alice")
        assert revoked["grant"]["status"] == "revoked"

        # The agent's listing reflects the revocation.
        agent_side = client.list_hirings(agent_principal_id="agent:helper")
        assert agent_side[0]["status"] == "revoked"

        # And the Vault now denies the agent.
        assert _vault_access(
            vault, credential_id, "agent:helper"
        ).status_code == 403

    def test_revoke_by_different_user_is_403(
        self, seeded, agent_marketplace
    ):
        client = AgentMarketplaceClient(agent_marketplace)
        grant = client.hire_agent(
            agent_principal_id="agent:helper",
            user_principal_id="user:alice",
            scoped_capabilities=["translation"],
        )
        resp = requests.delete(
            "%s/marketplace/hiring-grants/%s"
            % (agent_marketplace, grant["grant_id"]),
            json={"user_principal_id": "user:mallory"},
            timeout=TIMEOUT,
        )
        assert resp.status_code == 403, resp.text

        # Grant is still active.
        user_side = client.list_hirings(user_principal_id="user:alice")
        assert user_side[0]["status"] == "active"


# ---------------------------------------------------------------------------
# 6. Expiry
# ---------------------------------------------------------------------------


class TestExpiry:
    def test_past_expires_at_is_listed_as_expired(
        self, seeded, agent_marketplace
    ):
        past = (
            datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(hours=1)
        ).isoformat().replace("+00:00", "Z")
        client = AgentMarketplaceClient(agent_marketplace)
        grant = client.hire_agent(
            agent_principal_id="agent:helper",
            user_principal_id="user:alice",
            scoped_capabilities=["translation"],
            expires_at=past,
        )
        listed = client.list_hirings(user_principal_id="user:alice")
        assert listed[0]["grant_id"] == grant["grant_id"]
        assert listed[0]["status"] == "expired"

    def test_expired_status_is_a_read_time_predicate_no_write_occurs(
        self, seeded, agent_marketplace
    ):
        """Unit U8 (database architecture): 'expired' is computed by a
        query predicate every time a grant is read
        (``status = 'active' and (expires_at is null or expires_at >
        now())``) -- it is NEVER written back to the row. Proves that by
        reading the grant twice (through the HTTP API, which reports
        "expired" both times) and then inspecting the raw
        ``marketplace.hiring_grants`` row directly: ``status`` is still the
        literal ``'active'`` it was created with and ``revoked_at`` is still
        NULL -- no UPDATE was ever issued for the expiry transition."""
        from libs.db import Database

        past = (
            datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(hours=1)
        ).isoformat().replace("+00:00", "Z")
        client = AgentMarketplaceClient(agent_marketplace)
        grant = client.hire_agent(
            agent_principal_id="agent:helper",
            user_principal_id="user:alice",
            scoped_capabilities=["translation"],
            expires_at=past,
        )

        # Read it twice via the HTTP API -- both times report "expired".
        for _ in range(2):
            listed = client.list_hirings(user_principal_id="user:alice")
            assert listed[0]["status"] == "expired"

        # The underlying row was never mutated to reflect that: the raw
        # ``status`` column is still 'active' and ``revoked_at`` is NULL.
        db = Database()
        try:
            with db.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT status, revoked_at "
                        "FROM marketplace.hiring_grants WHERE grant_id = %s",
                        (grant["grant_id"],),
                    )
                    raw_status, revoked_at = cur.fetchone()
        finally:
            db.close()
        assert raw_status == "active"
        assert revoked_at is None


# ---------------------------------------------------------------------------
# 9. Hiring grant scoped to capabilities + credential scopes is queryable
#    as active (happy path, unit U8)
# ---------------------------------------------------------------------------


class TestGrantScoping:
    def test_grant_scoped_to_capabilities_and_credentials_is_active(
        self, seeded, vault, agent_marketplace_with_vault
    ):
        credential_id = _store_credential(vault, "user:alice")
        client = AgentMarketplaceClient(agent_marketplace_with_vault)
        grant = client.hire_agent(
            agent_principal_id="agent:helper",
            user_principal_id="user:alice",
            scoped_capabilities=["translation"],
            credential_scopes=[
                {"credential_id": credential_id, "scope": "read"},
            ],
        )
        assert grant["status"] == "active"
        assert grant["scoped_capabilities"] == ["translation"]
        assert grant["credential_scopes"] == [
            {"credential_id": credential_id, "scope": "read"},
        ]

        fetched = client.list_hirings(user_principal_id="user:alice")[0]
        assert fetched["status"] == "active"
        assert fetched["scoped_capabilities"] == ["translation"]
        assert fetched["credential_scopes"] == [
            {"credential_id": credential_id, "scope": "read"},
        ]


# ---------------------------------------------------------------------------
# 7-8. Ratings
# ---------------------------------------------------------------------------


class TestRatings:
    def test_rate_after_hiring_updates_avg(self, seeded, agent_marketplace):
        client = AgentMarketplaceClient(agent_marketplace)
        client.hire_agent(
            agent_principal_id="agent:helper",
            user_principal_id="user:alice",
            scoped_capabilities=["translation"],
        )
        result = client.rate_agent(
            "agent:helper", "user:alice", 5, review_text="great"
        )
        assert result["avg_rating"] == 5.0
        assert result["rating_count"] == 1

    def test_rate_without_hiring_is_403(self, seeded, agent_marketplace):
        resp = requests.post(
            "%s/marketplace/ratings" % agent_marketplace,
            json={
                "agent_principal_id": "agent:helper",
                "user_principal_id": "user:alice",
                "rating": 5,
            },
            timeout=TIMEOUT,
        )
        assert resp.status_code == 403, resp.text

    def test_invalid_rating_value_is_422(self, seeded, agent_marketplace):
        client = AgentMarketplaceClient(agent_marketplace)
        client.hire_agent(
            agent_principal_id="agent:helper",
            user_principal_id="user:alice",
            scoped_capabilities=["translation"],
        )
        for bad in (0, 6, "five", None, True):
            resp = requests.post(
                "%s/marketplace/ratings" % agent_marketplace,
                json={
                    "agent_principal_id": "agent:helper",
                    "user_principal_id": "user:alice",
                    "rating": bad,
                },
                timeout=TIMEOUT,
            )
            assert resp.status_code == 422, (bad, resp.text)

    def test_rerating_appends_history_and_updates_running_average(
        self, seeded, agent_marketplace
    ):
        """KTD8 (unit U8, database architecture): ratings are append-only
        history plus a materialized running-average summary, replacing
        today's "re-rating silently replaces the prior rating" behavior --
        a deliberate, plan-sanctioned change (R10's named exception list
        explicitly calls out "ratings history"). Re-rating the same agent
        now INSERTS a second ``marketplace.ratings`` row rather than
        overwriting the first; BOTH ratings count toward
        ``rating_summary``'s average forever, not just the latest.
        """
        client = AgentMarketplaceClient(agent_marketplace)
        client.hire_agent(
            agent_principal_id="agent:helper",
            user_principal_id="user:alice",
            scoped_capabilities=["translation"],
        )
        first = client.rate_agent("agent:helper", "user:alice", 5)
        assert first["avg_rating"] == 5.0
        assert first["rating_count"] == 1

        second = client.rate_agent("agent:helper", "user:alice", 3)
        # Appended, not replaced: both the original 5 and the new 3 count.
        assert second["avg_rating"] == pytest.approx(4.0)
        assert second["rating_count"] == 2

    def test_two_users_average_over_both(self, seeded, agent_marketplace):
        _register_user(seeded, "user:bob")
        client = AgentMarketplaceClient(agent_marketplace)
        client.hire_agent(
            agent_principal_id="agent:helper",
            user_principal_id="user:alice",
            scoped_capabilities=["translation"],
        )
        client.hire_agent(
            agent_principal_id="agent:helper",
            user_principal_id="user:bob",
            scoped_capabilities=["translation"],
        )
        client.rate_agent("agent:helper", "user:alice", 5)
        result = client.rate_agent("agent:helper", "user:bob", 2)
        assert result["rating_count"] == 2
        assert result["avg_rating"] == pytest.approx(3.5)

        # Search view agrees.
        agent = client.get_agent("agent:helper")
        assert agent["avg_rating"] == pytest.approx(3.5)
        assert agent["rating_count"] == 2
