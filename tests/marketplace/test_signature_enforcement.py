"""Signature enforcement on the Agent Marketplace mutating routes (U19).

Hire / revoke / rate are signed by the acting user, and the marketplace binds
the verified signer to the identity the action claims:

* hire  (POST /marketplace/hiring-grants) -> signer == body user_principal_id
* rate  (POST /marketplace/ratings)       -> signer == body user_principal_id
* revoke(DELETE .../hiring-grants/{id})   -> signer == the grant's hiring user

The keystone property is opt-in backward compatibility: with the flag OFF
(the default) the service behaves exactly as before — no signatures, no auth.

Tests run a REAL marketplace server on an ephemeral port against a REAL
Registry (source of truth for agents), but inject a ``public_key_resolver`` so
no live Registry public-key authority is needed. In this MVP the
``principal_id`` IS the principal's base64 public key, so the resolver simply
echoes the id back as the key.
"""

import json
import threading
import time

import pytest
import requests

from agent_marketplace.app import make_server as make_agent_marketplace_server
from libs import request_auth, signing
from libs.agent_marketplace_client import AgentMarketplaceClient
from registry.app import make_server as make_registry_server

TIMEOUT = 5.0


def _start(server):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


def _url(server):
    host, port = server.server_address[:2]
    return "http://%s:%d" % (host, port)


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


# In this MVP the principal_id IS the base64 public key, so a resolver that
# echoes the id back yields the correct verifying key for ANY principal.
def _echo_resolver(principal_id):
    return principal_id


def _make_identity():
    """A principal + session keypair; principal_id is the principal pubkey."""
    principal = signing.generate_keypair()
    session = signing.generate_keypair()
    principal_id = principal.public_key_b64()
    return principal, session, principal_id


def _signed_request(method, base_url, path, principal, session, principal_id,
                    body=None):
    """Issue a live, signed marketplace request over real HTTP.

    Signs the EXACT bytes we place on the wire (``data=raw``) so the server's
    reconstructed canonical string matches byte-for-byte. Uses wall-clock time
    so the request is fresh against the server's own ``time.time()``.
    """
    now_ts = time.time()
    raw = json.dumps(body).encode("utf-8") if body is not None else b""
    assertion = signing.build_session_assertion(
        principal_id, principal.signing_key, session.public_key_b64(),
        now_ts=now_ts,
    )
    headers = request_auth.build_auth_headers(
        principal_id, assertion, session.signing_key,
        method, path, raw, now_ts=now_ts,
    )
    headers["Content-Type"] = "application/json"
    return requests.request(
        method, base_url + path, data=raw, headers=headers, timeout=TIMEOUT
    )


# ---------------------------------------------------------------------------
# Fixtures (ephemeral ports only)
# ---------------------------------------------------------------------------


@pytest.fixture
def registry():
    server = make_registry_server(port=0)
    _start(server)
    url = _url(server)
    _register_agent(url, "agent:helper", ["translation"])
    yield url
    server.shutdown()
    server.server_close()


@pytest.fixture
def marketplace_off(registry):
    """Flag OFF (default): today's behavior exactly."""
    server = make_agent_marketplace_server(port=0, registry_url=registry)
    _start(server)
    yield _url(server)
    server.shutdown()
    server.server_close()


@pytest.fixture
def marketplace_on(registry):
    """Flag ON: signatures required, resolver injected (no live authority)."""
    server = make_agent_marketplace_server(
        port=0, registry_url=registry,
        require_signatures=True, public_key_resolver=_echo_resolver,
    )
    _start(server)
    yield _url(server)
    server.shutdown()
    server.server_close()


# ---------------------------------------------------------------------------
# 1. Flag OFF: existing unsigned hire flow still works (regression guard)
# ---------------------------------------------------------------------------


def test_flag_off_unsigned_hire_still_works(marketplace_off):
    client = AgentMarketplaceClient(marketplace_off)
    grant = client.hire_agent(
        agent_principal_id="agent:helper",
        user_principal_id="user:alice",
        scoped_capabilities=["translation"],
    )
    assert grant["status"] == "active"


# ---------------------------------------------------------------------------
# 2. Flag ON: valid signature hires 200; unsigned request 401
# ---------------------------------------------------------------------------


def test_flag_on_valid_signature_hires_and_unsigned_401(marketplace_on):
    principal, session, principal_id = _make_identity()
    body = {
        "agent_principal_id": "agent:helper",
        "user_principal_id": principal_id,
        "scoped_capabilities": ["translation"],
    }

    signed = _signed_request(
        "POST", marketplace_on, "/marketplace/hiring-grants",
        principal, session, principal_id, body=body,
    )
    assert signed.status_code == 200, signed.text
    assert signed.json()["grant"]["status"] == "active"

    # Same request with no auth headers -> 401.
    unsigned = requests.post(
        "%s/marketplace/hiring-grants" % marketplace_on,
        json=body, timeout=TIMEOUT,
    )
    assert unsigned.status_code == 401, unsigned.text


# ---------------------------------------------------------------------------
# 3. Flag ON: a DIFFERENT user cannot revoke someone else's grant, even with
#    a perfectly valid signature of their own -> 403
# ---------------------------------------------------------------------------


def test_flag_on_wrong_user_cannot_revoke_others_grant_403(marketplace_on):
    alice, alice_session, alice_id = _make_identity()
    # Alice hires the agent (signed as herself).
    hire = _signed_request(
        "POST", marketplace_on, "/marketplace/hiring-grants",
        alice, alice_session, alice_id,
        body={
            "agent_principal_id": "agent:helper",
            "user_principal_id": alice_id,
            "scoped_capabilities": ["translation"],
        },
    )
    assert hire.status_code == 200, hire.text
    grant_id = hire.json()["grant"]["grant_id"]

    # Mallory, a different real principal, signs a revoke of Alice's grant.
    mallory, mallory_session, mallory_id = _make_identity()
    path = "/marketplace/hiring-grants/%s" % grant_id
    revoke = _signed_request(
        "DELETE", marketplace_on, path,
        mallory, mallory_session, mallory_id,
        body={"user_principal_id": mallory_id},
    )
    assert revoke.status_code == 403, revoke.text

    # The grant is untouched.
    listed = requests.get(
        "%s/marketplace/hiring-grants" % marketplace_on,
        params={"user_principal_id": alice_id}, timeout=TIMEOUT,
    ).json()["grants"]
    assert listed[0]["status"] == "active"


# ---------------------------------------------------------------------------
# 4. Flag ON: rating signed by X but claiming user_principal_id Y -> 403
#    (identity mismatch, checked before the has-hiring gate)
# ---------------------------------------------------------------------------


def test_flag_on_rating_identity_mismatch_403(marketplace_on):
    alice, alice_session, alice_id = _make_identity()
    # Alice legitimately hires so she DOES have a hiring grant.
    hire = _signed_request(
        "POST", marketplace_on, "/marketplace/hiring-grants",
        alice, alice_session, alice_id,
        body={
            "agent_principal_id": "agent:helper",
            "user_principal_id": alice_id,
            "scoped_capabilities": ["translation"],
        },
    )
    assert hire.status_code == 200, hire.text

    # Alice signs a rating but the body claims a DIFFERENT user_principal_id.
    _bob, _bob_session, bob_id = _make_identity()
    mismatched = _signed_request(
        "POST", marketplace_on, "/marketplace/ratings",
        alice, alice_session, alice_id,
        body={
            "agent_principal_id": "agent:helper",
            "user_principal_id": bob_id,
            "rating": 5,
        },
    )
    assert mismatched.status_code == 403, mismatched.text
