"""Full-stack secure-mode end-to-end integration tests (Phase B.5, U20).

The capstone proof that AgentTrust works END TO END with cryptographic request
authentication turned ON, and that it REJECTS the classic attacks:
impersonation, tampering, replay, expiry, and non-owner revoke.

Every client-facing service runs with ``require_signatures=True`` on EPHEMERAL
ports; the :class:`~libs.session.SessionContext` ties the U7 keyring-unlock flow
to session issuance, and the service client libraries
(``VaultClient``/``P2PClient``/``AgentCoordinator``/...) sign every request
automatically when handed a session — so the happy path reads exactly like the
unsigned code, just with a ``session=`` argument.

The Registry itself stays the UNSIGNED public-key authority: apps record
reputation and create vault grants server-to-server against it unsigned, so
gating its mutating routes would break inter-service calls (out of U20 scope,
which wires signing into CLIENT libraries only). In this MVP a ``principal_id``
IS its own base64 ed25519 public key, so each service is given the identity
``public_key_resolver`` (``lambda pid: pid``) — deterministic, no live
authority round-trip.
"""

import json
import threading
import time

import pytest
import requests

from agent_marketplace.app import make_server as make_agent_marketplace_server
from apps.gig_board.server.app import make_server as make_gig_board_server
from apps.marketplace.server.app import make_server as make_marketplace_server
from libs import request_auth, signing
from libs.agent_coordination import AgentCoordinator
from libs.session import SessionContext
from libs.vault_client import VaultClient
from registry.app import make_server as make_registry_server
from vault import crypto
from vault.app import make_server as make_vault_server

TIMEOUT = 5.0
MARKETPLACE_CAP = "marketplace.tasks"
GIG_BOARD_CAP = "gig-board.gigs"


# ---------------------------------------------------------------------------
# Server plumbing (ephemeral ports only)
# ---------------------------------------------------------------------------


def _start(server):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


def _url(server):
    host, port = server.server_address[:2]
    return "http://%s:%d" % (host, port)


def _identity_resolver(principal_id):
    """MVP resolver: a principal_id IS its own base64 public key."""
    return principal_id


# ---------------------------------------------------------------------------
# Identity helpers (a principal IS a KeyPair whose pubkey is its principal_id)
# ---------------------------------------------------------------------------


def make_principal(url_safe=True):
    """A principal KeyPair whose base64 public key is its ``principal_id``.

    When ``url_safe`` the key is regenerated until it has no '/' or '+', so it
    may sit unescaped in a URL path/query segment (agent/vault endpoints embed
    the principal_id in the path).
    """
    while True:
        principal = signing.generate_keypair()
        principal_id = principal.public_key_b64()
        if url_safe and ("/" in principal_id or "+" in principal_id):
            continue
        return principal, principal_id


def _register_user(registry_url, principal_id, public_key=None):
    resp = requests.post(
        "%s/auth/register" % registry_url,
        json={"principal_id": principal_id, "public_key": public_key},
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, resp.text


def _register_agent(registry_url, principal_id, capabilities,
                    created_by="user:agent-owner"):
    resp = requests.post(
        "%s/agents/register" % registry_url,
        json={
            "principal_id": principal_id,
            "created_by": created_by,
            "agent_card": {
                "name": "secure work agent",
                "description": "secure-mode e2e agent",
                "capabilities": capabilities,
            },
        },
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, resp.text


def _register_app(registry_url, app_id, endpoint, capabilities,
                  **service_flags):
    payload = {
        "app_id": app_id,
        "app_endpoint": endpoint,
        "p2p_endpoint": endpoint,
        "capabilities": capabilities,
    }
    payload.update(service_flags)
    resp = requests.post(
        "%s/apps/register" % registry_url, json=payload, timeout=TIMEOUT
    )
    assert resp.status_code == 200, resp.text


# -- marketplace REST helpers (these routes are NOT gated; only /p2p is) -----


def _create_task(marketplace_url, author, description):
    resp = requests.post(
        "%s/api/tasks" % marketplace_url,
        json={"principal_id": author, "description": description},
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["task"]


def _get_bids(marketplace_url, task_id):
    resp = requests.get(
        "%s/api/tasks/%s/bids" % (marketplace_url, task_id), timeout=TIMEOUT
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["bids"]


def _accept_bid(marketplace_url, task_id, bid_id, author):
    return requests.post(
        "%s/api/tasks/%s/bids/%s/accept" % (marketplace_url, task_id, bid_id),
        json={"author_principal": author},
        timeout=TIMEOUT,
    )


def _complete_task(marketplace_url, task_id, author, outcome="great work"):
    return requests.post(
        "%s/api/negotiations/%s/complete" % (marketplace_url, task_id),
        json={"author_principal": author, "outcome": outcome},
        timeout=TIMEOUT,
    )


def _agent_reputation(registry_url, agent_principal_id):
    resp = requests.get(
        "%s/agents/%s" % (registry_url, agent_principal_id), timeout=TIMEOUT
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["reputation"]


# ---------------------------------------------------------------------------
# The full secure-mode stack: Registry (unsigned authority) + Vault + Agent
# Marketplace + Marketplace + Gig Board, the last four with signatures ON.
# ---------------------------------------------------------------------------


class SecureStack(object):
    def __init__(self, registry, vault, agent_marketplace, marketplace,
                 gig_board):
        self.registry = registry
        self.vault = vault
        self.agent_marketplace = agent_marketplace
        self.marketplace = marketplace
        self.gig_board = gig_board


@pytest.fixture
def stack():
    servers = []

    def spin(server):
        servers.append(server)
        _start(server)
        return _url(server)

    # The Registry is the public-key authority and receives unsigned
    # server-to-server writes (reputation, vault grants): it stays unsigned.
    registry = spin(make_registry_server(port=0))

    # Every client-facing service enforces signatures, resolving principals
    # locally (principal_id IS the public key).
    vault = spin(make_vault_server(
        port=0, require_signatures=True,
        public_key_resolver=_identity_resolver,
    ))
    agent_marketplace = spin(make_agent_marketplace_server(
        port=0, registry_url=registry, vault_url=vault,
        require_signatures=True, public_key_resolver=_identity_resolver,
    ))
    marketplace = spin(make_marketplace_server(
        port=0, registry_url=registry,
        require_signatures=True, public_key_resolver=_identity_resolver,
    ))
    gig_board = spin(make_gig_board_server(
        port=0, registry_url=registry,
        require_signatures=True, public_key_resolver=_identity_resolver,
    ))

    _register_app(
        registry, "marketplace", marketplace, [MARKETPLACE_CAP, "p2p.ping"]
    )
    _register_app(registry, "gig-board", gig_board, [GIG_BOARD_CAP, "p2p.ping"])
    _register_app(registry, "vault", vault, [], credential_vault=True)
    _register_app(
        registry, "agent-marketplace", agent_marketplace, [],
        agent_marketplace=True,
    )

    yield SecureStack(
        registry, vault, agent_marketplace, marketplace, gig_board
    )

    for server in reversed(servers):
        server.shutdown()
        server.server_close()


# ---------------------------------------------------------------------------
# 1. Full secure-mode happy path: signed autonomous marketplace lifecycle.
# ---------------------------------------------------------------------------


class TestSecureHappyPath:
    def test_signed_autonomous_marketplace_cycle_updates_reputation(
        self, stack
    ):
        author, author_id = make_principal()
        agent, agent_id = make_principal()
        _register_user(stack.registry, author_id, public_key=author_id)
        _register_user(stack.registry, agent_id, public_key=agent_id)
        _register_agent(stack.registry, agent_id, [MARKETPLACE_CAP])

        # The agent issues a session from its principal key and hands it to
        # the coordinator, which now SIGNS every P2P call automatically.
        agent_session = SessionContext.create(agent_id, agent.signing_key)
        coordinator = AgentCoordinator(
            stack.registry, agent_id, session=agent_session
        )

        # Author posts a task (REST, ungated), agent bids (P2P, signed).
        task = _create_task(stack.marketplace, author_id, "translate a doc")
        bid = coordinator.submit_bid(
            "marketplace", task["id"], "2 credits"
        )
        assert bid["agent_principal_id"] == agent_id

        # Author accepts (REST), agent delivers (P2P, signed), author
        # completes (REST) -> reputation recorded in the Registry.
        bids = _get_bids(stack.marketplace, task["id"])
        assert _accept_bid(
            stack.marketplace, task["id"], bids[0]["bid_id"], author_id
        ).status_code == 200

        delivered = coordinator.submit_result(
            "marketplace", task["id"], "work delivered"
        )
        assert delivered["work_result"]["submitted_by"] == agent_id

        assert _complete_task(
            stack.marketplace, task["id"], author_id
        ).status_code == 200

        reputation = _agent_reputation(stack.registry, agent_id)
        assert reputation["tasks_verified"] == 1
        assert reputation["verification_rate"] == 1.0

    def test_unsigned_coordinator_is_rejected_in_secure_mode(self, stack):
        """A coordinator with NO session cannot bid once signatures are on."""
        author, author_id = make_principal()
        agent, agent_id = make_principal()
        _register_user(stack.registry, author_id)
        _register_agent(stack.registry, agent_id, [MARKETPLACE_CAP])
        task = _create_task(stack.marketplace, author_id, "unsigned attempt")

        coordinator = AgentCoordinator(stack.registry, agent_id)  # no session
        with pytest.raises(Exception):
            coordinator.submit_bid("marketplace", task["id"], "2 credits")


# ---------------------------------------------------------------------------
# 2. Multi-device: unlock a keyring on a second device, issue a fresh session.
# ---------------------------------------------------------------------------


class TestMultiDeviceSession:
    def test_second_device_unlock_issues_working_session(self, stack):
        principal, principal_id = make_principal()
        password = "correct horse battery staple"

        # Device 1 issues a session from the in-memory principal key and
        # stores the wrapped keyring (POST /keyring is gated -> signed).
        device1 = SessionContext.create(principal_id, principal.signing_key)
        vault1 = VaultClient(stack.vault, session=device1)
        vault1.register_user_keyring(
            password, principal_id, bytes(principal.signing_key),
            iterations=1000,
        )

        # Device 2 knows only the password + principal_id: it fetches the
        # blob (GET, ungated), unlocks it (U7), and derives a FRESH session
        # from the recovered principal key.
        vault2 = VaultClient(stack.vault)
        device2 = SessionContext.from_keyring_unlock(
            vault2, password, principal_id
        )
        assert device2.principal_id == principal_id
        # A genuinely fresh, distinct ephemeral session key.
        assert device2.session.public_key_b64() != device1.session.public_key_b64()

        # The device-2 session signs a real mutating request -> accepted.
        vault2.session = device2
        stored = vault2.store_credential(
            principal_id, "api-key", "api_key", b"ciphertext", b"nonce--------"
        )
        assert "credential_id" in stored


# ---------------------------------------------------------------------------
# 3. Impersonation: signing with the WRONG key for a claimed principal -> 401.
# ---------------------------------------------------------------------------


class TestImpersonationRejected:
    def test_session_signed_by_wrong_key_is_rejected(self, stack):
        victim, victim_id = make_principal()
        attacker, _attacker_id = make_principal()

        # The attacker forges a session that CLAIMS to be the victim but is
        # signed by the attacker's principal key.
        forged = SessionContext.create(victim_id, attacker.signing_key)
        vault = VaultClient(stack.vault, session=forged)

        with pytest.raises(requests.HTTPError) as exc:
            vault.store_credential(
                victim_id, "api-key", "api_key", b"ct", b"nonce--------"
            )
        assert exc.value.response.status_code == 401


# ---------------------------------------------------------------------------
# 4. Tampering: altering the body after signing -> 401 (signed != sent bytes).
# ---------------------------------------------------------------------------


class TestTamperingRejected:
    def test_body_altered_after_signing_is_rejected(self, stack):
        owner, owner_id = make_principal()
        session = SessionContext.create(owner_id, owner.signing_key)

        honest_body = {
            "name": "smtp", "credential_type": "password",
            "encrypted_data": crypto.b64encode(b"ct"),
            "nonce": crypto.b64encode(b"nc"),
            "user_principal_id": owner_id,
        }
        honest_bytes = json.dumps(honest_body).encode("utf-8")
        headers = session.auth_headers(
            "POST", "/credentials", honest_bytes
        )
        headers["Content-Type"] = "application/json"

        # Send DIFFERENT bytes than were signed.
        tampered = dict(honest_body)
        tampered["user_principal_id"] = "user:someone-else"
        tampered_bytes = json.dumps(tampered).encode("utf-8")

        resp = requests.post(
            "%s/credentials" % stack.vault, data=tampered_bytes,
            headers=headers, timeout=TIMEOUT,
        )
        assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# 5. Replay: re-sending a captured signed request -> second attempt 401.
# ---------------------------------------------------------------------------


class TestReplayRejected:
    def test_replayed_request_is_rejected(self, stack):
        owner, owner_id = make_principal()
        session = SessionContext.create(owner_id, owner.signing_key)

        body = {
            "name": "smtp", "credential_type": "password",
            "encrypted_data": crypto.b64encode(b"ct"),
            "nonce": crypto.b64encode(b"nc"),
            "user_principal_id": owner_id,
        }
        raw = json.dumps(body).encode("utf-8")
        headers = session.auth_headers(
            "POST", "/credentials", raw, now_ts=time.time(), nonce="fixed-nonce-123",
        )
        headers["Content-Type"] = "application/json"

        first = requests.post(
            "%s/credentials" % stack.vault, data=raw, headers=headers,
            timeout=TIMEOUT,
        )
        assert first.status_code == 200, first.text

        # Byte-identical replay: same nonce + timestamp -> rejected.
        second = requests.post(
            "%s/credentials" % stack.vault, data=raw, headers=headers,
            timeout=TIMEOUT,
        )
        assert second.status_code == 401, second.text


# ---------------------------------------------------------------------------
# 6. Expiry: a session whose assertion is already past its expiry -> 401.
# ---------------------------------------------------------------------------


class TestExpiredSessionRejected:
    def test_expired_session_is_rejected(self, stack):
        owner, owner_id = make_principal()
        # Issued an hour ago with a 1s TTL: long expired.
        expired = SessionContext.create(
            owner_id, owner.signing_key, ttl=1, now_ts=time.time() - 3600
        )
        vault = VaultClient(stack.vault, session=expired)

        with pytest.raises(requests.HTTPError) as exc:
            vault.store_credential(
                owner_id, "api-key", "api_key", b"ct", b"nonce--------"
            )
        assert exc.value.response.status_code == 401


# ---------------------------------------------------------------------------
# 7. Non-owner revoke: a valid signature by a non-owner -> 403 (asymmetry fix).
# ---------------------------------------------------------------------------


class TestNonOwnerRevokeForbidden:
    def test_non_owner_signed_revoke_is_forbidden_owner_still_can(self, stack):
        owner, owner_id = make_principal()
        agent, agent_id = make_principal()
        mallory, mallory_id = make_principal()

        owner_session = SessionContext.create(owner_id, owner.signing_key)
        owner_vault = VaultClient(stack.vault, session=owner_session)

        stored = owner_vault.store_credential(
            owner_id, "smtp", "password", b"ciphertext", b"nonce--------"
        )
        credential_id = stored["credential_id"]
        owner_vault.grant_access(credential_id, agent_id, "read", owner_id)

        # Mallory holds a perfectly valid signature -- but is NOT the owner.
        mallory_session = SessionContext.create(
            mallory_id, mallory.signing_key
        )
        mallory_vault = VaultClient(stack.vault, session=mallory_session)
        with pytest.raises(requests.HTTPError) as exc:
            mallory_vault.revoke_access(credential_id, agent_id)
        assert exc.value.response.status_code == 403

        # The owner, signing for themselves, still can (asymmetry closed).
        revoked = owner_vault.revoke_access(credential_id, agent_id)
        assert revoked["revoked"] is True


# ---------------------------------------------------------------------------
# 8. Mixed mode: an unsigned service still accepts an unsigned client.
# ---------------------------------------------------------------------------


class TestMixedModeMigration:
    def test_unsigned_service_accepts_unsigned_client(self):
        """Gradual migration: a service with the flag OFF is unchanged."""
        server = make_vault_server(port=0)  # require_signatures defaults False
        _start(server)
        try:
            vault = VaultClient(_url(server))  # no session
            stored = vault.store_credential(
                "user:legacy", "api-key", "api_key",
                b"ciphertext", b"nonce--------",
            )
            assert "credential_id" in stored
        finally:
            server.shutdown()
            server.server_close()
