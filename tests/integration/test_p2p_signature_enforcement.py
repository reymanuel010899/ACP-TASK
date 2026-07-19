"""Integration tests for cryptographic P2P request authentication (unit U18).

P2P requests may be required to prove ``requester_principal_id``
cryptographically, ON TOP of the existing Registry permission check. The
enforcement is opt-in per deployment (``require_signatures``):

* Flag OFF (default): today's behavior exactly — unsigned P2P works, only the
  Registry permission check (when a registry is configured) applies.
* Flag ON: every ``POST /p2p/request`` must carry a valid two-link signature
  (libs/signing) whose verified principal EQUALS the payload's
  ``requester_principal_id`` (else 403 identity mismatch), before the
  unchanged permission check + dispatch run.

Order under the flag: authenticate (401 on failure) -> identity-bind (403 on
mismatch) -> Registry permission check (403 on denial) -> dispatch.

These tests run REAL servers on EPHEMERAL ports against a REAL Registry (P2P
already needs one for permission checks); the agent registers its public key
with the Registry so the app's authenticator can fetch it.
"""

import json
import threading
import time

import pytest
import requests

from apps.marketplace.server.app import make_server as make_marketplace_server
from libs import request_auth, signing
from registry.app import make_server as make_registry_server

TIMEOUT = 5.0
MARKET_CAP = "marketplace.tasks"
PING_CAPABILITY = "p2p.ping"


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


@pytest.fixture
def registry():
    server = make_registry_server(port=0)
    _start(server)
    yield _url(server)
    server.shutdown()
    server.server_close()


@pytest.fixture
def marketplace_signed(registry):
    """Marketplace with signature enforcement ON, wired to the registry."""
    server = make_marketplace_server(
        port=0, registry_url=registry, require_signatures=True
    )
    _start(server)
    yield _url(server)
    server.shutdown()
    server.server_close()


@pytest.fixture
def marketplace_unsigned(registry):
    """Marketplace with the flag OFF (default) — today's behavior."""
    server = make_marketplace_server(
        port=0, registry_url=registry, require_signatures=False
    )
    _start(server)
    yield _url(server)
    server.shutdown()
    server.server_close()


# ---------------------------------------------------------------------------
# Registry + identity helpers
# ---------------------------------------------------------------------------


def _register_app(registry_url, app_id, endpoint, capabilities):
    resp = requests.post(
        "%s/apps/register" % registry_url,
        json={
            "app_id": app_id,
            "app_endpoint": endpoint,
            "p2p_endpoint": endpoint,
            "capabilities": capabilities,
        },
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, resp.text


def _register_principal_with_key(registry_url, principal_id, public_key):
    """Register a user principal AND publish its public key so the app's
    authenticator can resolve it from the Registry authority endpoint."""
    resp = requests.post(
        "%s/auth/register" % registry_url,
        json={"principal_id": principal_id, "public_key": public_key},
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, resp.text


def make_identity():
    """A principal + session keypair and a fresh valid session assertion.

    Per the MVP convention (libs/signing bind check) the ``principal_id`` IS
    the principal's base64 public key — the identity anchor the Registry pins.
    """
    principal = signing.generate_keypair()
    session = signing.generate_keypair()
    principal_id = principal.public_key_b64()
    assertion = signing.build_session_assertion(
        principal_id,
        principal.signing_key,
        session.public_key_b64(),
    )
    return session, principal_id, assertion


def _signed_p2p_post(app_url, payload, principal_id, assertion, session_key):
    """POST /p2p/request signing the EXACT bytes sent on the wire."""
    raw = json.dumps(payload).encode("utf-8")
    headers = request_auth.build_auth_headers(
        principal_id, assertion, session_key,
        "POST", "/p2p/request", raw, now_ts=time.time(),
    )
    headers["Content-Type"] = "application/json"
    return requests.post(
        "%s/p2p/request" % app_url, data=raw, headers=headers, timeout=TIMEOUT
    )


def _create_task(app_url, author, description):
    resp = requests.post(
        "%s/api/tasks" % app_url,
        json={"principal_id": author, "description": description},
        timeout=TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["task"]["id"]


# ---------------------------------------------------------------------------
# 1. Flag OFF: existing unsigned P2P still works (regression guard)
# ---------------------------------------------------------------------------


class TestFlagOff:
    def test_unsigned_ping_still_works(self, registry, marketplace_unsigned):
        _register_principal_with_key(registry, "user:alice", None)
        _register_app(
            registry, "marketplace", marketplace_unsigned,
            [MARKET_CAP, PING_CAPABILITY],
        )
        resp = requests.post(
            "%s/p2p/request" % marketplace_unsigned,
            json={
                "requester_principal_id": "user:alice",
                "request_type": "ping",
                "capability_id": PING_CAPABILITY,
            },
            timeout=TIMEOUT,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["result"]["pong"] is True

    def test_unsigned_bid_still_works(self, registry, marketplace_unsigned):
        _register_principal_with_key(registry, "user:agent", None)
        _register_app(
            registry, "marketplace", marketplace_unsigned, [MARKET_CAP],
        )
        task_id = _create_task(
            marketplace_unsigned, "user:author", "translate a doc"
        )
        resp = requests.post(
            "%s/p2p/request" % marketplace_unsigned,
            json={
                "requester_principal_id": "user:agent",
                "request_type": "submit.work_bid",
                "capability_id": MARKET_CAP,
                "input": {"task_id": task_id, "proposed_terms": "2 days"},
            },
            timeout=TIMEOUT,
        )
        assert resp.status_code == 200, resp.text
        assert (
            resp.json()["result"]["bid"]["agent_principal_id"] == "user:agent"
        )


# ---------------------------------------------------------------------------
# 2. Flag ON + valid signature matching requester -> 200
# ---------------------------------------------------------------------------


class TestFlagOnValidSignature:
    def test_valid_signed_bid_is_accepted(self, registry, marketplace_signed):
        session, principal_id, assertion = make_identity()
        _register_principal_with_key(registry, principal_id, principal_id)
        _register_app(
            registry, "marketplace", marketplace_signed, [MARKET_CAP],
        )
        task_id = _create_task(
            marketplace_signed, "user:author", "translate a doc"
        )

        resp = _signed_p2p_post(
            marketplace_signed,
            {
                "requester_principal_id": principal_id,
                "request_type": "submit.work_bid",
                "capability_id": MARKET_CAP,
                "input": {"task_id": task_id, "proposed_terms": "2 days"},
            },
            principal_id, assertion, session,
        )
        assert resp.status_code == 200, resp.text
        bid = resp.json()["result"]["bid"]
        assert bid["agent_principal_id"] == principal_id


# ---------------------------------------------------------------------------
# 3. Flag ON + valid signature but claims another principal -> 403 mismatch
# ---------------------------------------------------------------------------


class TestFlagOnIdentityMismatch:
    def test_signed_by_self_but_claims_other_is_403(
        self, registry, marketplace_signed
    ):
        session, principal_id, assertion = make_identity()
        # The signer registers its OWN key so authentication succeeds...
        _register_principal_with_key(registry, principal_id, principal_id)
        _register_app(
            registry, "marketplace", marketplace_signed,
            [MARKET_CAP, PING_CAPABILITY],
        )
        task_id = _create_task(
            marketplace_signed, "user:author", "translate a doc"
        )

        # ...but the payload claims to be a DIFFERENT principal.
        resp = _signed_p2p_post(
            marketplace_signed,
            {
                "requester_principal_id": "user:someone-else",
                "request_type": "submit.work_bid",
                "capability_id": MARKET_CAP,
                "input": {"task_id": task_id, "proposed_terms": "2 days"},
            },
            principal_id, assertion, session,
        )
        assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# 4. Flag ON + unsigned P2P request -> 401
# ---------------------------------------------------------------------------


class TestFlagOnUnsigned:
    def test_unsigned_request_is_401(self, registry, marketplace_signed):
        _register_principal_with_key(registry, "user:alice", None)
        _register_app(
            registry, "marketplace", marketplace_signed,
            [MARKET_CAP, PING_CAPABILITY],
        )
        resp = requests.post(
            "%s/p2p/request" % marketplace_signed,
            json={
                "requester_principal_id": "user:alice",
                "request_type": "ping",
                "capability_id": PING_CAPABILITY,
            },
            timeout=TIMEOUT,
        )
        assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# 5. Flag ON + valid signature but permission denied -> 403 (layer still runs)
# ---------------------------------------------------------------------------


class TestFlagOnPermissionStillApplies:
    def test_valid_signature_unsupported_capability_is_403(
        self, registry, marketplace_signed
    ):
        session, principal_id, assertion = make_identity()
        _register_principal_with_key(registry, principal_id, principal_id)
        # marketplace does NOT advertise "vault.read".
        _register_app(
            registry, "marketplace", marketplace_signed, [MARKET_CAP],
        )

        resp = _signed_p2p_post(
            marketplace_signed,
            {
                "requester_principal_id": principal_id,
                "request_type": "ping",
                "capability_id": "vault.read",
            },
            principal_id, assertion, session,
        )
        assert resp.status_code == 403, resp.text
