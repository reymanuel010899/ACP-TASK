"""Shared signing & stateless session library (unit U13).

A single, dependency-light home for the cryptographic identity primitives the
AgentTrust services share. It generalises the ad-hoc ed25519 pattern already
used by ``agents/provider/agent.py`` (PyNaCl ``SigningKey`` / ``VerifyKey``)
and mirrors the base64/error-class style of ``vault/crypto.py``.

The trust model is a two-link chain:

1. **Principal.** A long-term ed25519 keypair. Its *public* key (base64) is the
   identity anchor — the ``principal_id`` other services register and pin.

2. **Session.** A *stateless* assertion — plain JSON
   ``{principal_id, session_public_key, issued_at, expires_at}`` plus a
   detached ``signature`` made by the *principal's* private key. There is no
   session server and no stored state: a verifier checks the signature against
   the principal's known public key and the expiry against its own clock.

3. **Request.** Every request is signed by the *session's* private key over a
   canonical string binding method, path, a hash of the body, a timestamp and a
   nonce. :class:`NonceCache` plus :func:`timestamp_fresh` give replay
   protection within a bounded clock-skew window.

All time-dependent functions accept an explicit ``now_ts`` (epoch seconds) so
callers — and tests — can inject the clock; they default to ``time.time()``.
"""

import base64
import hashlib
import json
import threading
import time

import nacl.exceptions
import nacl.signing


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_SESSION_TTL = 900  # 15 minutes
DEFAULT_SKEW_SECONDS = 120  # 2 minutes of tolerated clock skew / replay window


# ---------------------------------------------------------------------------
# Errors (mirrors vault/crypto.py's small, explicit hierarchy)
# ---------------------------------------------------------------------------


class SigningError(Exception):
    """Base class for signing-library errors."""


class SignatureError(SigningError):
    """A signature did not verify, or a bound identity did not match."""


class ExpiredError(SigningError):
    """A session assertion is past its ``expires_at``."""


# ---------------------------------------------------------------------------
# Encoding helpers (keys and signatures travel as base64 strings in JSON)
# ---------------------------------------------------------------------------


def b64encode(raw):
    # type: (bytes) -> str
    return base64.b64encode(raw).decode("ascii")


def b64decode(text):
    # type: (str) -> bytes
    return base64.b64decode(text.encode("ascii"))


# ---------------------------------------------------------------------------
# Keypairs
# ---------------------------------------------------------------------------


class KeyPair(object):
    """A generated ed25519 keypair with base64 serialization helpers.

    ``signing_key`` is the private key (a ``nacl.signing.SigningKey``);
    ``verify_key`` is its public half. Serialize the public key with
    :meth:`public_key_b64` (the identity anchor) and the private seed with
    :meth:`signing_key_b64` (secret — persist only through the Vault, never
    transmit).
    """

    __slots__ = ("signing_key", "verify_key")

    def __init__(self, signing_key):
        # type: (nacl.signing.SigningKey) -> None
        self.signing_key = signing_key
        self.verify_key = signing_key.verify_key

    def public_key_b64(self):
        # type: () -> str
        return public_key_b64(self.verify_key)

    def signing_key_b64(self):
        # type: () -> str
        """Base64 of the 32-byte private seed. Secret material."""
        return b64encode(bytes(self.signing_key))


def generate_keypair():
    # type: () -> KeyPair
    """Generate a fresh ed25519 keypair (locally; the seed never leaves)."""
    return KeyPair(nacl.signing.SigningKey.generate())


def public_key_b64(verify_key):
    # type: (nacl.signing.VerifyKey) -> str
    """Serialize an ed25519 public key to base64 (~44 chars)."""
    return b64encode(bytes(verify_key))


def load_signing_key(seed_b64):
    # type: (str) -> KeyPair
    """Rebuild a :class:`KeyPair` from a base64 private seed."""
    try:
        return KeyPair(nacl.signing.SigningKey(b64decode(seed_b64)))
    except (ValueError, TypeError, nacl.exceptions.CryptoError) as exc:
        raise SigningError("invalid signing key seed") from exc


def load_verify_key(public_key_b64_str):
    # type: (str) -> nacl.signing.VerifyKey
    """Rebuild an ed25519 public key from its base64 form."""
    try:
        return nacl.signing.VerifyKey(b64decode(public_key_b64_str))
    except (ValueError, TypeError, nacl.exceptions.CryptoError) as exc:
        raise SigningError("invalid public key") from exc


# ---------------------------------------------------------------------------
# Stateless session assertions
# ---------------------------------------------------------------------------


def _canonical_session_bytes(principal_id, session_public_key_b64,
                             issued_at, expires_at):
    # type: (str, str, int, int) -> bytes
    """Canonical byte string the principal signs for a session assertion.

    Compact, key-sorted JSON of exactly the bound claims — so both signer and
    verifier reconstruct identical bytes regardless of dict ordering.
    """
    claims = {
        "principal_id": principal_id,
        "session_public_key": session_public_key_b64,
        "issued_at": issued_at,
        "expires_at": expires_at,
    }
    return json.dumps(
        claims, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def build_session_assertion(principal_id, principal_signing_key,
                            session_public_key_b64,
                            ttl_seconds=DEFAULT_SESSION_TTL, now_ts=None):
    # type: (str, nacl.signing.SigningKey, str, int, float) -> dict
    """Issue a stateless session assertion signed by the principal key.

    ``principal_signing_key`` may be a :class:`KeyPair` or a raw
    ``nacl.signing.SigningKey``. Returns a JSON-safe dict carrying the bound
    claims plus a detached base64 ``signature``. ``issued_at``/``expires_at``
    are epoch seconds; ``now_ts`` defaults to ``time.time()`` but may be
    injected for deterministic issuance.
    """
    if now_ts is None:
        now_ts = time.time()
    signing_key = _as_signing_key(principal_signing_key)

    issued_at = int(now_ts)
    expires_at = issued_at + int(ttl_seconds)
    message = _canonical_session_bytes(
        principal_id, session_public_key_b64, issued_at, expires_at
    )
    signature = signing_key.sign(message).signature
    return {
        "principal_id": principal_id,
        "session_public_key": session_public_key_b64,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "signature": b64encode(signature),
    }


def verify_session_assertion(assertion, principal_public_key_b64, now_ts=None):
    # type: (dict, str, float) -> str
    """Verify a session assertion against a known principal public key.

    Checks, in order: the embedded ``principal_id`` matches the key we are
    verifying against (bind check), the principal's signature over the
    canonical claims, and that the assertion has not expired. Returns the
    ``session_public_key`` (base64) on success.

    Raises :class:`SignatureError` for an id mismatch or a bad signature, and
    :class:`ExpiredError` when ``now_ts`` is past ``expires_at``.
    """
    if now_ts is None:
        now_ts = time.time()

    principal_id = assertion.get("principal_id")
    session_public_key = assertion.get("session_public_key")
    issued_at = assertion.get("issued_at")
    expires_at = assertion.get("expires_at")
    signature_b64 = assertion.get("signature")

    if principal_id != principal_public_key_b64:
        # The assertion binds itself to a principal_id; it must be the very
        # identity (public key) the verifier is authenticating against.
        raise SignatureError("assertion principal_id does not match principal")

    if not signature_b64:
        raise SignatureError("assertion is missing its signature")

    verify_key = load_verify_key(principal_public_key_b64)
    message = _canonical_session_bytes(
        principal_id, session_public_key, issued_at, expires_at
    )
    try:
        verify_key.verify(message, b64decode(signature_b64))
    except (nacl.exceptions.BadSignatureError, ValueError, TypeError) as exc:
        raise SignatureError("session assertion signature invalid") from exc

    if not isinstance(expires_at, (int, float)) or now_ts > expires_at:
        raise ExpiredError("session assertion has expired")

    return session_public_key


# ---------------------------------------------------------------------------
# Per-request canonical signing
# ---------------------------------------------------------------------------


def canonical_request(method, path, body_bytes, timestamp, nonce):
    # type: (str, str, bytes, int, str) -> str
    """The canonical string a session key signs for one request.

    ``method + "\\n" + path + "\\n" + sha256_hex(body) + "\\n" +
    timestamp + "\\n" + nonce`` — hashing the body keeps the signed string
    bounded while still binding the exact payload.
    """
    if body_bytes is None:
        body_bytes = b""
    if isinstance(body_bytes, str):
        body_bytes = body_bytes.encode("utf-8")
    body_hash = hashlib.sha256(body_bytes).hexdigest()
    return "\n".join(
        [str(method), str(path), body_hash, str(timestamp), str(nonce)]
    )


def sign_request(session_signing_key, method, path, body_bytes,
                 timestamp, nonce):
    # type: (nacl.signing.SigningKey, str, str, bytes, int, str) -> str
    """Sign the canonical request string with the session's private key.

    Returns the detached signature as base64. ``session_signing_key`` may be a
    :class:`KeyPair` or a raw ``nacl.signing.SigningKey``.
    """
    signing_key = _as_signing_key(session_signing_key)
    message = canonical_request(
        method, path, body_bytes, timestamp, nonce
    ).encode("utf-8")
    return b64encode(signing_key.sign(message).signature)


def verify_request_signature(session_public_key_b64, method, path, body_bytes,
                             timestamp, nonce, signature_b64):
    # type: (str, str, str, bytes, int, str, str) -> bool
    """Verify a per-request signature against the session's public key.

    Returns ``True`` on success; raises :class:`SignatureError` if the
    signature does not verify for the reconstructed canonical string (i.e. any
    of method, path, body, timestamp or nonce was altered).
    """
    verify_key = load_verify_key(session_public_key_b64)
    message = canonical_request(
        method, path, body_bytes, timestamp, nonce
    ).encode("utf-8")
    try:
        verify_key.verify(message, b64decode(signature_b64))
    except (nacl.exceptions.BadSignatureError, ValueError, TypeError) as exc:
        raise SignatureError("request signature invalid") from exc
    return True


# ---------------------------------------------------------------------------
# Replay protection
# ---------------------------------------------------------------------------


def timestamp_fresh(timestamp, now_ts, skew_seconds=DEFAULT_SKEW_SECONDS):
    # type: (int, float, int) -> bool
    """True if ``timestamp`` is within ``skew_seconds`` of ``now_ts``.

    Guards against stale (replayed) and far-future request timestamps.
    """
    try:
        delta = abs(float(now_ts) - float(timestamp))
    except (TypeError, ValueError):
        return False
    return delta <= skew_seconds


class NonceCache(object):
    """Thread-safe, bounded, self-evicting nonce store for replay defence.

    A nonce is fresh only once within the skew window. Entries older than
    ``skew_seconds`` are evicted on every access, so the cache stays bounded by
    the number of distinct nonces seen inside one window — no unbounded growth
    and no external reaper needed.
    """

    def __init__(self, skew_seconds=DEFAULT_SKEW_SECONDS):
        # type: (int) -> None
        self.skew_seconds = skew_seconds
        self._seen = {}  # nonce -> recorded epoch seconds
        self._lock = threading.Lock()

    def _evict(self, now_ts):
        # type: (float) -> None
        # Called under the lock. Drop everything older than the window.
        cutoff = now_ts - self.skew_seconds
        stale = [n for n, ts in self._seen.items() if ts < cutoff]
        for n in stale:
            del self._seen[n]

    def check_and_add(self, nonce, now_ts):
        # type: (str, float) -> bool
        """Record ``nonce`` at ``now_ts``. True if fresh, False if a replay.

        A nonce last recorded more than ``skew_seconds`` ago has already been
        evicted and so is accepted (and re-recorded) again.
        """
        with self._lock:
            self._evict(now_ts)
            if nonce in self._seen:
                return False
            self._seen[nonce] = now_ts
            return True


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _as_signing_key(key):
    # type: (object) -> nacl.signing.SigningKey
    """Accept a KeyPair or a raw SigningKey and return the SigningKey."""
    if isinstance(key, KeyPair):
        return key.signing_key
    return key
