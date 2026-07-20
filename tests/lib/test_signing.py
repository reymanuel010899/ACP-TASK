"""Tests for the shared signing library (unit U13).

Covers the two-link chain:
    Principal long-term ed25519 keypair (identity anchor)
      -> stateless SESSION assertion signed by the principal key
        -> per-REQUEST canonical signature made by the session key
with replay protection (NonceCache) and clock-skew checks.

All time-dependent behaviour is driven with explicit ``now_ts`` values so
these tests are fully deterministic.
"""

import pytest

from libs import signing


FIXED_NOW = 1_700_000_000  # arbitrary fixed epoch second


# ---------------------------------------------------------------------------
# 1. Keypair -> sign request -> verify roundtrip
# ---------------------------------------------------------------------------


def test_request_roundtrip_verifies():
    kp = signing.generate_keypair()
    sig = signing.sign_request(
        kp.signing_key, "POST", "/agents", b'{"a":1}', FIXED_NOW, "nonce-1"
    )
    assert signing.verify_request_signature(
        kp.public_key_b64(),
        "POST",
        "/agents",
        b'{"a":1}',
        FIXED_NOW,
        "nonce-1",
        sig,
    ) is True


def test_key_serialization_roundtrip():
    kp = signing.generate_keypair()
    pub_b64 = kp.public_key_b64()
    # public key is base64 and ~44 chars (matches web/app.py principal_id check)
    assert isinstance(pub_b64, str)
    assert 40 <= len(pub_b64) <= 48

    # reload the signing key from its base64 seed and get the same public key
    seed_b64 = kp.signing_key_b64()
    reloaded = signing.load_signing_key(seed_b64)
    assert signing.public_key_b64(reloaded.verify_key) == pub_b64

    # load_verify_key round-trips too
    vk = signing.load_verify_key(pub_b64)
    assert signing.public_key_b64(vk) == pub_b64


# ---------------------------------------------------------------------------
# 2. Tamper detection: each single field alteration must fail
# ---------------------------------------------------------------------------


@pytest.fixture
def signed_request():
    kp = signing.generate_keypair()
    base = {
        "method": "POST",
        "path": "/agents/xyz",
        "body_bytes": b'{"hello":"world"}',
        "timestamp": FIXED_NOW,
        "nonce": "nonce-abc",
    }
    sig = signing.sign_request(kp.signing_key, **base)
    return kp.public_key_b64(), base, sig


def _verify(pub, params, sig):
    return signing.verify_request_signature(
        pub,
        params["method"],
        params["path"],
        params["body_bytes"],
        params["timestamp"],
        params["nonce"],
        sig,
    )


def test_altered_body_fails(signed_request):
    pub, params, sig = signed_request
    params = dict(params, body_bytes=b'{"hello":"WORLD"}')
    with pytest.raises(signing.SignatureError):
        _verify(pub, params, sig)


def test_altered_method_fails(signed_request):
    pub, params, sig = signed_request
    params = dict(params, method="GET")
    with pytest.raises(signing.SignatureError):
        _verify(pub, params, sig)


def test_altered_path_fails(signed_request):
    pub, params, sig = signed_request
    params = dict(params, path="/agents/other")
    with pytest.raises(signing.SignatureError):
        _verify(pub, params, sig)


def test_altered_timestamp_fails(signed_request):
    pub, params, sig = signed_request
    params = dict(params, timestamp=FIXED_NOW + 1)
    with pytest.raises(signing.SignatureError):
        _verify(pub, params, sig)


def test_altered_nonce_fails(signed_request):
    pub, params, sig = signed_request
    params = dict(params, nonce="nonce-xyz")
    with pytest.raises(signing.SignatureError):
        _verify(pub, params, sig)


# ---------------------------------------------------------------------------
# 3. Session assertion signed by principal; wrong principal key rejected
# ---------------------------------------------------------------------------


def test_session_assertion_verifies_against_principal():
    principal = signing.generate_keypair()
    session = signing.generate_keypair()
    principal_id = principal.public_key_b64()

    assertion = signing.build_session_assertion(
        principal_id,
        principal.signing_key,
        session.public_key_b64(),
        ttl_seconds=signing.DEFAULT_SESSION_TTL,
        now_ts=FIXED_NOW,
    )
    returned = signing.verify_session_assertion(
        assertion, principal_id, now_ts=FIXED_NOW
    )
    assert returned == session.public_key_b64()


def test_session_assertion_wrong_principal_key_fails():
    principal = signing.generate_keypair()
    other = signing.generate_keypair()
    session = signing.generate_keypair()
    principal_id = principal.public_key_b64()

    assertion = signing.build_session_assertion(
        principal_id,
        principal.signing_key,
        session.public_key_b64(),
        ttl_seconds=signing.DEFAULT_SESSION_TTL,
        now_ts=FIXED_NOW,
    )
    # verifying with a DIFFERENT public key must fail the signature check
    with pytest.raises(signing.SignatureError):
        signing.verify_session_assertion(
            assertion, other.public_key_b64(), now_ts=FIXED_NOW
        )


# ---------------------------------------------------------------------------
# 4. Expired assertion
# ---------------------------------------------------------------------------


def test_expired_session_assertion_raises():
    principal = signing.generate_keypair()
    session = signing.generate_keypair()
    principal_id = principal.public_key_b64()

    assertion = signing.build_session_assertion(
        principal_id,
        principal.signing_key,
        session.public_key_b64(),
        ttl_seconds=100,
        now_ts=FIXED_NOW,
    )
    # now is one second past expiry
    with pytest.raises(signing.ExpiredError):
        signing.verify_session_assertion(
            assertion, principal_id, now_ts=FIXED_NOW + 101
        )


# ---------------------------------------------------------------------------
# 5. principal_id bind check: embedded id must match claimed principal
# ---------------------------------------------------------------------------


def test_session_assertion_principal_id_mismatch_raises():
    principal = signing.generate_keypair()
    session = signing.generate_keypair()

    assertion = signing.build_session_assertion(
        "atp:some-other-principal",
        principal.signing_key,
        session.public_key_b64(),
        ttl_seconds=signing.DEFAULT_SESSION_TTL,
        now_ts=FIXED_NOW,
    )
    # signature is valid for principal's key, but embedded principal_id does
    # not match the principal we claim to be verifying against.
    with pytest.raises(signing.SignatureError):
        signing.verify_session_assertion(
            assertion, principal.public_key_b64(), now_ts=FIXED_NOW
        )


# ---------------------------------------------------------------------------
# 6. NonceCache replay protection
# ---------------------------------------------------------------------------


def test_nonce_cache_detects_replay_and_evicts():
    cache = signing.NonceCache(skew_seconds=120)
    assert cache.check_and_add("n1", FIXED_NOW) is True
    # immediate repeat is a replay
    assert cache.check_and_add("n1", FIXED_NOW) is False
    # a repeat well after the skew window: the old entry is evicted and the
    # nonce is accepted again.
    assert cache.check_and_add("n1", FIXED_NOW + 121) is True


def test_nonce_cache_independent_nonces():
    cache = signing.NonceCache(skew_seconds=120)
    assert cache.check_and_add("a", FIXED_NOW) is True
    assert cache.check_and_add("b", FIXED_NOW) is True
    assert cache.check_and_add("a", FIXED_NOW) is False


# ---------------------------------------------------------------------------
# 7. timestamp_fresh
# ---------------------------------------------------------------------------


def test_timestamp_fresh_within_skew():
    assert signing.timestamp_fresh(FIXED_NOW, FIXED_NOW, 120) is True
    assert signing.timestamp_fresh(FIXED_NOW - 119, FIXED_NOW, 120) is True
    assert signing.timestamp_fresh(FIXED_NOW + 119, FIXED_NOW, 120) is True


def test_timestamp_fresh_outside_skew():
    assert signing.timestamp_fresh(FIXED_NOW - 121, FIXED_NOW, 120) is False
    assert signing.timestamp_fresh(FIXED_NOW + 121, FIXED_NOW, 120) is False


# ---------------------------------------------------------------------------
# 8. canonical_request stability / sensitivity
# ---------------------------------------------------------------------------


def test_canonical_request_stable():
    a = signing.canonical_request("POST", "/x", b"body", FIXED_NOW, "n")
    b = signing.canonical_request("POST", "/x", b"body", FIXED_NOW, "n")
    assert a == b


@pytest.mark.parametrize(
    "field,value",
    [
        ("method", "GET"),
        ("path", "/y"),
        ("body_bytes", b"other"),
        ("timestamp", FIXED_NOW + 1),
        ("nonce", "n2"),
    ],
)
def test_canonical_request_differs_per_field(field, value):
    base = {
        "method": "POST",
        "path": "/x",
        "body_bytes": b"body",
        "timestamp": FIXED_NOW,
        "nonce": "n",
    }
    ref = signing.canonical_request(**base)
    changed = signing.canonical_request(**dict(base, **{field: value}))
    assert ref != changed
