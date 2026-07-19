"""Tests for the shared request-authentication middleware (unit U15).

The authenticator is the single centralization point every service calls to
verify a request. It runs the full two-link chain from libs/signing.py against
a principal public key resolved from the Registry, with a public-key cache and
a shared NonceCache for replay defence.

Tests use REAL crypto (libs.signing) with a FAKE network: an injected
``public_key_resolver`` stands in for the live Registry authority endpoint, so
no HTTP server is needed. All clocks are injected via ``now_ts`` for
determinism.
"""

import pytest

from libs import request_auth
from libs import signing


FIXED_NOW = 1_700_000_000  # arbitrary fixed epoch second


def make_identity(now_ts=FIXED_NOW, ttl=signing.DEFAULT_SESSION_TTL):
    """A principal + session keypair and a valid session assertion.

    In this MVP the ``principal_id`` IS the principal's base64 public key
    (the identity anchor), matching libs/signing.py's bind check.
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


# ---------------------------------------------------------------------------
# 1. Flag OFF: pass-through no-op, resolver never called
# ---------------------------------------------------------------------------


def test_flag_off_passthrough_and_no_resolver_call():
    calls = []

    def resolver(principal_id):
        calls.append(principal_id)
        return "unused"

    auth = request_auth.RequestAuthenticator(
        "http://registry", require_signatures=False,
        public_key_resolver=resolver,
    )
    principal_id, error = auth.authenticate("POST", "/agents", b"{}", {})

    assert principal_id is None
    assert error is None
    assert calls == []  # NO Registry call in pass-through mode


# ---------------------------------------------------------------------------
# 2. Flag ON + valid signed request -> correct principal_id, no error
# ---------------------------------------------------------------------------


def test_valid_signed_request_returns_principal_id():
    _principal, session, principal_id, assertion = make_identity()

    def resolver(pid):
        return principal_id  # the principal's real public key

    auth = request_auth.RequestAuthenticator(
        "http://registry", require_signatures=True,
        public_key_resolver=resolver,
    )
    headers = request_auth.build_auth_headers(
        principal_id, assertion, session.signing_key,
        "POST", "/agents", b'{"a":1}', now_ts=FIXED_NOW, nonce="nonce-1",
    )
    # headers must be a plain str->str mapping for http.server
    assert all(
        isinstance(k, str) and isinstance(v, str) for k, v in headers.items()
    )

    got_id, error = auth.authenticate(
        "POST", "/agents", b'{"a":1}', headers, now_ts=FIXED_NOW
    )
    assert error is None
    assert got_id == principal_id


# ---------------------------------------------------------------------------
# 3. Flag ON + missing headers -> 401
# ---------------------------------------------------------------------------


def test_missing_headers_401():
    auth = request_auth.RequestAuthenticator(
        "http://registry", require_signatures=True,
        public_key_resolver=lambda pid: "x",
    )
    principal_id, error = auth.authenticate(
        "POST", "/agents", b"{}", {}, now_ts=FIXED_NOW
    )
    assert principal_id is None
    assert error is not None
    assert error.status == 401


# ---------------------------------------------------------------------------
# 4. Flag ON + assertion signed by a key the Registry does not vouch for -> 401
# ---------------------------------------------------------------------------


def test_wrong_principal_key_401():
    _principal, session, principal_id, assertion = make_identity()
    other = signing.generate_keypair()

    def resolver(pid):
        # Registry returns a DIFFERENT public key than the one that signed
        return other.public_key_b64()

    auth = request_auth.RequestAuthenticator(
        "http://registry", require_signatures=True,
        public_key_resolver=resolver,
    )
    headers = request_auth.build_auth_headers(
        principal_id, assertion, session.signing_key,
        "POST", "/agents", b"{}", now_ts=FIXED_NOW, nonce="nonce-1",
    )
    principal_out, error = auth.authenticate(
        "POST", "/agents", b"{}", headers, now_ts=FIXED_NOW
    )
    assert principal_out is None
    assert error.status == 401


# ---------------------------------------------------------------------------
# 5. Flag ON + body tampered after signing -> 401
# ---------------------------------------------------------------------------


def test_tampered_body_401():
    _principal, session, principal_id, assertion = make_identity()

    def resolver(pid):
        return principal_id

    auth = request_auth.RequestAuthenticator(
        "http://registry", require_signatures=True,
        public_key_resolver=resolver,
    )
    headers = request_auth.build_auth_headers(
        principal_id, assertion, session.signing_key,
        "POST", "/agents", b'{"amount":1}', now_ts=FIXED_NOW, nonce="nonce-1",
    )
    # body altered AFTER the signature was produced
    principal_out, error = auth.authenticate(
        "POST", "/agents", b'{"amount":999}', headers, now_ts=FIXED_NOW
    )
    assert principal_out is None
    assert error.status == 401


# ---------------------------------------------------------------------------
# 6. Flag ON + expired session -> 401
# ---------------------------------------------------------------------------


def test_expired_session_401():
    _principal, session, principal_id, assertion = make_identity(ttl=100)

    def resolver(pid):
        return principal_id

    auth = request_auth.RequestAuthenticator(
        "http://registry", require_signatures=True,
        public_key_resolver=resolver,
    )
    headers = request_auth.build_auth_headers(
        principal_id, assertion, session.signing_key,
        "POST", "/agents", b"{}", now_ts=FIXED_NOW, nonce="nonce-1",
    )
    # one second past the assertion's expiry
    principal_out, error = auth.authenticate(
        "POST", "/agents", b"{}", headers, now_ts=FIXED_NOW + 101
    )
    assert principal_out is None
    assert error.status == 401


# ---------------------------------------------------------------------------
# 7. Flag ON + replayed nonce -> first ok, second 401
# ---------------------------------------------------------------------------


def test_replayed_nonce_401_on_second_use():
    _principal, session, principal_id, assertion = make_identity()

    def resolver(pid):
        return principal_id

    auth = request_auth.RequestAuthenticator(
        "http://registry", require_signatures=True,
        public_key_resolver=resolver,
    )
    headers = request_auth.build_auth_headers(
        principal_id, assertion, session.signing_key,
        "POST", "/agents", b"{}", now_ts=FIXED_NOW, nonce="nonce-replay",
    )

    id1, err1 = auth.authenticate(
        "POST", "/agents", b"{}", headers, now_ts=FIXED_NOW
    )
    assert err1 is None
    assert id1 == principal_id

    # exact same request again -> replay
    id2, err2 = auth.authenticate(
        "POST", "/agents", b"{}", headers, now_ts=FIXED_NOW
    )
    assert id2 is None
    assert err2.status == 401


# ---------------------------------------------------------------------------
# 8. Flag ON + Registry unreachable (resolver raises) -> 401 (fail closed)
# ---------------------------------------------------------------------------


def test_registry_unreachable_fails_closed_401():
    _principal, session, principal_id, assertion = make_identity()

    def resolver(pid):
        raise RuntimeError("registry down")

    auth = request_auth.RequestAuthenticator(
        "http://registry", require_signatures=True,
        public_key_resolver=resolver,
    )
    headers = request_auth.build_auth_headers(
        principal_id, assertion, session.signing_key,
        "POST", "/agents", b"{}", now_ts=FIXED_NOW, nonce="nonce-1",
    )
    principal_out, error = auth.authenticate(
        "POST", "/agents", b"{}", headers, now_ts=FIXED_NOW
    )
    assert principal_out is None
    assert error.status == 401


# ---------------------------------------------------------------------------
# 9. Flag ON + unknown principal / null public key (resolver None) -> 401
# ---------------------------------------------------------------------------


def test_unknown_principal_null_key_401():
    _principal, session, principal_id, assertion = make_identity()

    def resolver(pid):
        return None  # unknown principal or registered without a public key

    auth = request_auth.RequestAuthenticator(
        "http://registry", require_signatures=True,
        public_key_resolver=resolver,
    )
    headers = request_auth.build_auth_headers(
        principal_id, assertion, session.signing_key,
        "POST", "/agents", b"{}", now_ts=FIXED_NOW, nonce="nonce-1",
    )
    principal_out, error = auth.authenticate(
        "POST", "/agents", b"{}", headers, now_ts=FIXED_NOW
    )
    assert principal_out is None
    assert error.status == 401


# ---------------------------------------------------------------------------
# 10. Public-key cache: two auths for same principal within TTL -> resolver
#     called ONCE
# ---------------------------------------------------------------------------


def test_public_key_cache_resolves_once_within_ttl():
    _principal, session, principal_id, assertion = make_identity()
    calls = []

    def resolver(pid):
        calls.append(pid)
        return principal_id

    auth = request_auth.RequestAuthenticator(
        "http://registry", require_signatures=True,
        public_key_resolver=resolver,
    )
    h1 = request_auth.build_auth_headers(
        principal_id, assertion, session.signing_key,
        "POST", "/agents", b"{}", now_ts=FIXED_NOW, nonce="nonce-a",
    )
    h2 = request_auth.build_auth_headers(
        principal_id, assertion, session.signing_key,
        "POST", "/agents", b"{}", now_ts=FIXED_NOW, nonce="nonce-b",
    )
    id1, err1 = auth.authenticate(
        "POST", "/agents", b"{}", h1, now_ts=FIXED_NOW
    )
    id2, err2 = auth.authenticate(
        "POST", "/agents", b"{}", h2, now_ts=FIXED_NOW
    )
    assert err1 is None and err2 is None
    assert id1 == principal_id and id2 == principal_id
    assert len(calls) == 1  # second authentication hit the cache
