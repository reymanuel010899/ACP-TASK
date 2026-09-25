"""Tests for optional signature enforcement on the Registry (unit U16).

With ``require_signatures`` OFF (the default) the Registry behaves EXACTLY as
before — unsigned mutating requests succeed — so every pre-U16 registry test
stays green. With the flag ON, the MUTATING endpoints require a valid two-link
signature (per libs/signing.py + libs/request_auth.py) and answer 401 to an
unsigned or invalid request. GET routes stay OPEN regardless of the flag.

Because the Registry IS the public-key authority, the authenticator resolves
principals in-process (no HTTP self-call). Signer principals are seeded by
calling the service methods directly — those are never gated; only the HTTP
handler enforces signatures.

Real crypto, a real server on an ephemeral port (``port=0``).
"""

import json
import threading
import time

import pytest
import requests

from libs import request_auth, signing
from registry.app import RegistryService, make_server
from registry.index_store import IndexStore


AGENT_CARD = {
    "name": "deploy-bot",
    "description": "Deploys infrastructure to AWS",
    "capabilities": ["aws.deploy", "terraform.apply"],
}


def make_identity(now_ts, ttl=signing.DEFAULT_SESSION_TTL):
    """A principal + session keypair and a valid session assertion.

    The ``principal_id`` IS the principal's base64 public key (identity
    anchor), matching libs/signing.py's bind check.
    """
    principal = signing.generate_keypair()
    session = signing.generate_keypair()
    principal_id = principal.public_key_b64()
    assertion = signing.build_session_assertion(
        principal_id,
        principal.signing_key,
        session.public_key_b64(),
        ttl_seconds=ttl,
        now_ts=now_ts,
    )
    return principal, session, principal_id, assertion


def serve(service):
    """Start ``service`` on an ephemeral port; return (base_url, stop)."""
    server = make_server(port=0, service=service)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = "http://%s:%d" % server.server_address[:2]

    def stop():
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    return base_url, stop


def signed_post(base_url, path, payload, principal_id, session, assertion,
                now_ts):
    """POST ``payload`` to ``path`` with a valid signature over the raw body."""
    raw = json.dumps(payload).encode("utf-8")
    headers = request_auth.build_auth_headers(
        principal_id, assertion, session.signing_key,
        "POST", path, raw, now_ts=now_ts,
    )
    headers["Content-Type"] = "application/json"
    headers["X-Organization-Id"] = "org:test-registry-suite"
    return requests.post(base_url + path, data=raw, headers=headers, timeout=5)


# ---------------------------------------------------------------------------
# 1. Flag OFF: unsigned mutating request still succeeds (backward compat)
# ---------------------------------------------------------------------------


def test_flag_off_unsigned_agent_register_still_200():
    service = RegistryService(IndexStore())  # default: require_signatures=False
    base_url, stop = serve(service)
    try:
        resp = requests.post(
            base_url + "/agents/register",
            json={
                "agent_card": dict(AGENT_CARD),
                "principal_id": "agent-plain",
                "created_by": "user-plain",
            },
            headers={"X-Organization-Id": "org:test-registry-suite"},
            timeout=5,
        )
        assert resp.status_code == 200, resp.text
    finally:
        stop()


# ---------------------------------------------------------------------------
# 2. Flag ON + unsigned POST /agents/register -> 401
# ---------------------------------------------------------------------------


def test_flag_on_unsigned_agent_register_401():
    service = RegistryService(IndexStore(), require_signatures=True)
    base_url, stop = serve(service)
    try:
        resp = requests.post(
            base_url + "/agents/register",
            json={
                "agent_card": dict(AGENT_CARD),
                "principal_id": "agent-plain",
                "created_by": "user-plain",
            },
            timeout=5,
        )
        assert resp.status_code == 401, resp.text
        assert "error" in resp.json()
    finally:
        stop()


# ---------------------------------------------------------------------------
# 3. Flag ON + validly-signed POST /agents/register -> 200
# ---------------------------------------------------------------------------


def test_flag_on_signed_agent_register_200():
    now_ts = time.time()
    _principal, session, principal_id, assertion = make_identity(now_ts)

    service = RegistryService(IndexStore(), require_signatures=True)
    # Seed the signer principal's public key in-process (never gated).
    status, body = service.register_user(
        {"principal_id": principal_id, "public_key": principal_id}
    )
    assert status == 200, body

    base_url, stop = serve(service)
    try:
        resp = signed_post(
            base_url, "/agents/register",
            {
                "agent_card": dict(AGENT_CARD),
                "principal_id": "agent-signed",
                "created_by": principal_id,
            },
            principal_id, session, assertion, now_ts,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["agent"]["principal_id"] == "agent-signed"
    finally:
        stop()


# ---------------------------------------------------------------------------
# 4. Flag ON + reputation: signed -> 200, unsigned -> 401
# ---------------------------------------------------------------------------


def test_flag_on_reputation_signed_200_unsigned_401():
    now_ts = time.time()
    _principal, session, principal_id, assertion = make_identity(now_ts)

    service = RegistryService(IndexStore(), require_signatures=True)
    # Signer principal (resolvable public key) ...
    service.register_user(
        {"principal_id": principal_id, "public_key": principal_id}
    )
    # ... and a target user whose reputation we update.
    service.register_user({"principal_id": "user-target"})

    base_url, stop = serve(service)
    try:
        path = "/users/user-target/reputation"
        payload = {
            "task_id": "task-1",
            "verified": True,
            "capability_id": "aws.deploy",
        }

        # Unsigned -> 401
        resp = requests.post(base_url + path, json=payload, timeout=5)
        assert resp.status_code == 401, resp.text

        # Signed -> 200
        resp = signed_post(
            base_url, path, payload,
            principal_id, session, assertion, now_ts,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["task_id"] == "task-1"
    finally:
        stop()


# ---------------------------------------------------------------------------
# 5. Flag ON + GET routes stay OPEN (no signature required)
# ---------------------------------------------------------------------------


def test_flag_on_get_routes_open():
    service = RegistryService(IndexStore(), require_signatures=True)
    base_url, stop = serve(service)
    try:
        resp = requests.get(
            base_url + "/agents", params={"capability": "aws.deploy"},
            timeout=5,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["agents"] == []

        resp = requests.get(base_url + "/healthz", timeout=5)
        assert resp.status_code == 200, resp.text
    finally:
        stop()
