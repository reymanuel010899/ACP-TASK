"""Signature enforcement + identity binding for the Vault (unit U17).

The Vault adopts the shared request-authentication middleware
(``libs/request_auth.py``). The keystone property is **opt-in backward
compatibility**:

* Flag OFF (default) -> today's behavior EXACTLY. No signatures required, and
  the historically PERMISSIVE revoke (anyone may revoke) is preserved
  byte-for-byte. All 32 pre-existing vault tests stay green.
* Flag ON -> every mutating endpoint authenticates, and the verified signer is
  IDENTITY-BOUND to the action: a keyring/credential owner may only act as
  themselves, an agent may only request access as itself, and — closing the
  historical asymmetry — only the credential OWNER may revoke a grant (a
  non-owner with an otherwise valid signature gets 403).

Tests use REAL crypto (libs.signing) with a FAKE Registry: an injected
``public_key_resolver`` maps a ``principal_id`` to its public key. In this MVP
the ``principal_id`` IS the base64 public key, so ``lambda pid: pid`` resolves
every principal to its own (correct) key without any live Registry.
"""

import collections
import json
import os
import threading
import time

import pytest
import requests

from libs import request_auth
from libs import signing
from vault import crypto
from vault.app import make_server


# Resolver: principal_id == its own base64 public key in this MVP, so every
# principal resolves to the exact key that must have signed for it.
def identity_resolver(principal_id):
    return principal_id


Identity = collections.namedtuple(
    "Identity", ["principal", "session", "principal_id", "assertion"]
)


def make_identity(url_safe=False):
    """A principal + session keypair and a fresh, valid session assertion.

    When ``url_safe`` is set the principal_id (a base64 public key) is
    regenerated until it contains no '/' or '+', so it may sit unescaped in a
    single URL path segment (e.g. PUT /keyring/{id}).
    """
    while True:
        principal = signing.generate_keypair()
        principal_id = principal.public_key_b64()
        if url_safe and ("/" in principal_id or "+" in principal_id):
            continue
        break
    session = signing.generate_keypair()
    assertion = signing.build_session_assertion(
        principal_id, principal.signing_key, session.public_key_b64()
    )
    return Identity(principal, session, principal_id, assertion)


def base_url(server):
    host, port = server.server_address[:2]
    return "http://%s:%d" % (host, port)


def signed_request(method, base, path, identity, payload=None,
                   principal_override=None, timeout=5):
    """Issue an HTTP request carrying a valid signature from ``identity``.

    The body is serialized to fixed bytes and signed over (method, path,
    body) so the server reconstructs identical canonical bytes.
    ``principal_override`` swaps ONLY the X-AT-Principal header (to simulate a
    caller claiming another identity it cannot actually sign for).
    """
    body_bytes = b"" if payload is None else json.dumps(payload).encode("utf-8")
    now = time.time()
    headers = request_auth.build_auth_headers(
        identity.principal_id, identity.assertion, identity.session.signing_key,
        method, path, body_bytes, now_ts=now, nonce=os.urandom(8).hex(),
    )
    if principal_override is not None:
        headers[request_auth.HEADER_PRINCIPAL] = principal_override
    headers["Content-Type"] = "application/json"
    return requests.request(
        method, base + path, data=body_bytes, headers=headers, timeout=timeout
    )


def run_server(server):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


def stop_server(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


@pytest.fixture
def vault_off():
    """A vault with signatures OFF (default) — today's behavior exactly."""
    server = make_server(port=0)
    thread = run_server(server)
    try:
        yield server
    finally:
        stop_server(server, thread)


@pytest.fixture
def vault_on():
    """A vault with signatures ON, using the injected identity resolver."""
    server = make_server(
        port=0, require_signatures=True, public_key_resolver=identity_resolver
    )
    thread = run_server(server)
    try:
        yield server
    finally:
        stop_server(server, thread)


def _keyring_blob(user_principal_id):
    blob, _dek = crypto.build_keyring_blob(
        "pw", os.urandom(32), iterations=1000
    )
    body = dict(blob)
    body["user_principal_id"] = user_principal_id
    return body


def _store_credential_signed(base, owner):
    """Owner stores a credential under a valid signature; returns its id."""
    payload = {
        "name": "smtp",
        "credential_type": "password",
        "encrypted_data": crypto.b64encode(b"ciphertext-blob"),
        "nonce": crypto.b64encode(b"nonce-blob-000000000000000"),
        "user_principal_id": owner.principal_id,
    }
    resp = signed_request("POST", base, "/credentials", owner, payload)
    assert resp.status_code == 200, resp.text
    return resp.json()["credential_id"]


# ---------------------------------------------------------------------------
# 1. Flag OFF characterization: a NON-OWNER unsigned revoke STILL succeeds.
#    This locks in today's permissive revoke as backward-compatible behavior.
# ---------------------------------------------------------------------------


def test_flag_off_non_owner_unsigned_revoke_still_succeeds(vault_off):
    base = base_url(vault_off)
    # Store a credential owned by "owner_a" (no signatures required).
    store = requests.post(
        base + "/credentials",
        json={
            "name": "smtp",
            "credential_type": "password",
            "encrypted_data": crypto.b64encode(b"ct"),
            "nonce": crypto.b64encode(b"nc"),
            "user_principal_id": "owner_a",
        },
        timeout=5,
    )
    credential_id = store.json()["credential_id"]
    requests.post(
        base + "/credentials/%s/grants" % credential_id,
        json={
            "agent_principal_id": "agent_temp",
            "scope": "read",
            "granted_by": "owner_a",
        },
        timeout=5,
    )

    # An UNSIGNED, non-owner caller revokes — and today this succeeds (200).
    resp = requests.delete(
        base + "/credentials/%s/grants/agent_temp" % credential_id, timeout=5
    )
    assert resp.status_code == 200
    assert resp.json()["revoked"] is True


# ---------------------------------------------------------------------------
# 2. Flag ON: agent requests its OWN granted credential with a valid signature
#    -> 200 + ciphertext.
# ---------------------------------------------------------------------------


def test_flag_on_agent_signed_access_returns_ciphertext(vault_on):
    base = base_url(vault_on)
    owner = make_identity(url_safe=True)
    agent = make_identity()
    credential_id = _store_credential_signed(base, owner)

    grant = signed_request(
        "POST", base, "/credentials/%s/grants" % credential_id, owner,
        {"agent_principal_id": agent.principal_id, "scope": "read",
         "granted_by": owner.principal_id},
    )
    assert grant.status_code == 200, grant.text

    access = signed_request(
        "POST", base, "/credentials/%s/access" % credential_id, agent,
        {"agent_principal_id": agent.principal_id},
    )
    assert access.status_code == 200, access.text
    body = access.json()
    assert body["access_granted"] is True
    assert body["encrypted_data"] == crypto.b64encode(b"ciphertext-blob")


# ---------------------------------------------------------------------------
# 3. Flag ON: a caller claims ANOTHER agent's identity without a valid
#    signature for it -> 401 (the assertion cannot bind to the claimed id).
# ---------------------------------------------------------------------------


def test_flag_on_claiming_other_identity_without_signature_401(vault_on):
    base = base_url(vault_on)
    owner = make_identity(url_safe=True)
    agent_a = make_identity()
    agent_b = make_identity()
    credential_id = _store_credential_signed(base, owner)
    signed_request(
        "POST", base, "/credentials/%s/grants" % credential_id, owner,
        {"agent_principal_id": agent_b.principal_id, "scope": "read",
         "granted_by": owner.principal_id},
    )

    # Sign as A but CLAIM to be B in the principal header: B's registered key
    # cannot verify A's assertion -> authentication fails closed.
    resp = signed_request(
        "POST", base, "/credentials/%s/access" % credential_id, agent_a,
        {"agent_principal_id": agent_b.principal_id},
        principal_override=agent_b.principal_id,
    )
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# 4. Flag ON: OWNER revokes a grant with a valid owner signature -> 200.
# ---------------------------------------------------------------------------


def test_flag_on_owner_signed_revoke_succeeds(vault_on):
    base = base_url(vault_on)
    owner = make_identity(url_safe=True)
    credential_id = _store_credential_signed(base, owner)
    signed_request(
        "POST", base, "/credentials/%s/grants" % credential_id, owner,
        {"agent_principal_id": "agent_temp", "scope": "read",
         "granted_by": owner.principal_id},
    )

    resp = signed_request(
        "DELETE", base,
        "/credentials/%s/grants/agent_temp" % credential_id, owner,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["revoked"] is True


# ---------------------------------------------------------------------------
# 5. Flag ON: a NON-OWNER with a valid signature attempts revoke -> 403.
#    THIS IS THE ASYMMETRY FIX.
# ---------------------------------------------------------------------------


def test_flag_on_non_owner_signed_revoke_forbidden(vault_on):
    base = base_url(vault_on)
    owner = make_identity(url_safe=True)
    mallory = make_identity(url_safe=True)  # a valid principal, but NOT owner
    credential_id = _store_credential_signed(base, owner)
    signed_request(
        "POST", base, "/credentials/%s/grants" % credential_id, owner,
        {"agent_principal_id": "agent_temp", "scope": "read",
         "granted_by": owner.principal_id},
    )

    # Mallory signs a perfectly valid request — but she is not the owner.
    resp = signed_request(
        "DELETE", base,
        "/credentials/%s/grants/agent_temp" % credential_id, mallory,
    )
    assert resp.status_code == 403, resp.text

    # And the grant was NOT removed: the agent can still get the ciphertext
    # (owner requests on the agent's behalf is a mismatch, so query the
    # agent's own signed access instead is unnecessary — prove non-removal by
    # a fresh owner-authorized re-grant being idempotent is overkill; instead
    # assert the audit endpoint is reachable and the grant path still 200s via
    # a direct owner-signed revoke now succeeding).
    owner_revoke = signed_request(
        "DELETE", base,
        "/credentials/%s/grants/agent_temp" % credential_id, owner,
    )
    assert owner_revoke.status_code == 200, owner_revoke.text
    assert owner_revoke.json()["revoked"] is True


# ---------------------------------------------------------------------------
# 6. Flag ON: keyring rotate (PUT) signed by a NON-OWNER -> 403.
# ---------------------------------------------------------------------------


def test_flag_on_keyring_rotate_by_non_owner_forbidden(vault_on):
    base = base_url(vault_on)
    owner = make_identity(url_safe=True)
    mallory = make_identity(url_safe=True)

    store = signed_request(
        "POST", base, "/keyring", owner, _keyring_blob(owner.principal_id)
    )
    assert store.status_code == 200, store.text

    # Mallory has a valid signature but rotates the OWNER's keyring.
    rotation = _keyring_blob(owner.principal_id)
    rotation["rotation_reason"] = "malicious rotate"
    resp = signed_request(
        "PUT", base, "/keyring/%s" % owner.principal_id, mallory, rotation
    )
    assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# 7. Flag ON: UNSIGNED credential access -> 401.
# ---------------------------------------------------------------------------


def test_flag_on_unsigned_access_401(vault_on):
    base = base_url(vault_on)
    owner = make_identity(url_safe=True)
    credential_id = _store_credential_signed(base, owner)

    resp = requests.post(
        base + "/credentials/%s/access" % credential_id,
        json={"agent_principal_id": "agent_temp"},
        timeout=5,
    )
    assert resp.status_code == 401, resp.text
