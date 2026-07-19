"""Shared request-authentication middleware (unit U15).

The single centralization point every AgentTrust service calls to AUTHENTICATE
an inbound request. It runs the full two-link verification chain from
``libs/signing.py`` against a principal public key resolved from the Registry
authority endpoint (``GET /principals/{id}/public_key``, U14), with a
short-TTL public-key cache and a shared :class:`~libs.signing.NonceCache` for
replay defence.

The keystone property is **opt-in backward compatibility**: when
``require_signatures`` is off the authenticator is a pure NO-OP pass-through —
no Registry call, no headers required, no error. Services can therefore adopt
:class:`RequestAuthenticator` before the ecosystem has fully rolled over to
signed requests and flip the flag on per deployment.

The authenticator never decides *authorization*: it returns the verified
``principal_id`` (WHO the caller is) or a 401 error (auth failed). Deciding
whether that principal MAY perform the action — including any 403
identity-mismatch check — is the calling service's job.

See ``spec/RFC-0005-request-authentication.md`` for the wire contract.
"""

import base64
import collections
import json
import os
import time
from typing import Callable, Optional, Tuple
from urllib.parse import quote

import requests

from libs.signing import (
    DEFAULT_SKEW_SECONDS,
    ExpiredError,
    NonceCache,
    SigningError,
    sign_request,
    timestamp_fresh,
    verify_request_signature,
    verify_session_assertion,
)


# ---------------------------------------------------------------------------
# Auth header names (str -> str; safe for http.server)
# ---------------------------------------------------------------------------

HEADER_PRINCIPAL = "X-AT-Principal"
HEADER_SESSION = "X-AT-Session"
HEADER_SESSION_PUB = "X-AT-Session-Pub"
HEADER_SIGNATURE = "X-AT-Signature"
HEADER_TIMESTAMP = "X-AT-Timestamp"
HEADER_NONCE = "X-AT-Nonce"

# Short TTL for the resolved-public-key cache. Principals rotate rarely; a
# minute keeps the Registry off the hot path without pinning stale keys long.
DEFAULT_PUBKEY_CACHE_TTL = 60

DEFAULT_HTTP_TIMEOUT = 3.0


# ---------------------------------------------------------------------------
# Error value (a small tuple carrying an HTTP status + message)
# ---------------------------------------------------------------------------

AuthError = collections.namedtuple("AuthError", ["status", "message"])


def _err(message, status=401):
    # type: (str, int) -> AuthError
    return AuthError(status=status, message=message)


# ---------------------------------------------------------------------------
# Client-side header construction (for U20's signing clients)
# ---------------------------------------------------------------------------


def build_auth_headers(principal_id, session_assertion, session_signing_key,
                       method, path, body_bytes, now_ts, nonce=None):
    # type: (str, dict, object, str, str, bytes, float, Optional[str]) -> dict
    """Produce the str->str auth header set for one signed request.

    ``session_assertion`` is a dict as returned by
    :func:`libs.signing.build_session_assertion`; ``session_signing_key`` is
    the private half of the session key that assertion vouches for (a
    ``KeyPair`` or raw ``SigningKey``). A random ``nonce`` is generated when
    not supplied; ``timestamp`` is ``int(now_ts)`` so it survives the
    header/string round-trip byte-for-byte.
    """
    if nonce is None:
        nonce = os.urandom(16).hex()
    timestamp = int(now_ts)
    signature_b64 = sign_request(
        session_signing_key, method, path, body_bytes, timestamp, nonce
    )
    session_pub = ""
    if isinstance(session_assertion, dict):
        session_pub = session_assertion.get("session_public_key") or ""
    session_json = json.dumps(
        session_assertion, sort_keys=True, separators=(",", ":")
    )
    return {
        HEADER_PRINCIPAL: str(principal_id),
        HEADER_SESSION: session_json,
        HEADER_SESSION_PUB: str(session_pub),
        HEADER_SIGNATURE: str(signature_b64),
        HEADER_TIMESTAMP: str(timestamp),
        HEADER_NONCE: str(nonce),
    }


# ---------------------------------------------------------------------------
# The authenticator
# ---------------------------------------------------------------------------


class RequestAuthenticator(object):
    """Authenticate inbound requests; a no-op when signatures are not required.

    ``authenticate`` returns ``(principal_id, None)`` on success or
    ``(None, AuthError)`` on failure. When ``require_signatures`` is False it
    returns ``(None, None)`` immediately without touching the network — the
    backward-compatible pass-through.

    Tests (and offline callers) may inject ``public_key_resolver`` — a callable
    ``principal_id -> public_key_b64 | None`` that MUST raise when the Registry
    is unreachable — in place of the default HTTP resolver.
    """

    def __init__(self, registry_url, require_signatures=False,
                 http_timeout=DEFAULT_HTTP_TIMEOUT,
                 skew_seconds=DEFAULT_SKEW_SECONDS,
                 pubkey_cache_ttl=DEFAULT_PUBKEY_CACHE_TTL,
                 public_key_resolver=None):
        # type: (str, bool, float, int, int, Optional[Callable[[str], Optional[str]]]) -> None
        self.registry_url = (registry_url or "").rstrip("/")
        self.require_signatures = require_signatures
        self.http_timeout = http_timeout
        self.skew_seconds = skew_seconds
        self.pubkey_cache_ttl = pubkey_cache_ttl
        self._resolver = public_key_resolver or self._http_resolve_public_key
        self._nonce_cache = NonceCache(skew_seconds=skew_seconds)
        self._pubkey_cache = {}  # principal_id -> (public_key_b64, cached_at)

    # -- public API --------------------------------------------------------

    def authenticate(self, method, path, body_bytes, headers, now_ts=None):
        # type: (str, str, bytes, object, Optional[float]) -> Tuple[Optional[str], Optional[AuthError]]
        """Run the 7-step verification. See module/RFC docs for the chain."""
        # Step 1: opt-in flag OFF -> pass-through no-op (no Registry call).
        if not self.require_signatures:
            return (None, None)

        if now_ts is None:
            now_ts = time.time()

        # Step 2: extract the auth headers; missing required ones -> 401.
        h = _lower_headers(headers)
        principal_id = h.get(HEADER_PRINCIPAL.lower())
        session_raw = h.get(HEADER_SESSION.lower())
        signature_b64 = h.get(HEADER_SIGNATURE.lower())
        timestamp_raw = h.get(HEADER_TIMESTAMP.lower())
        nonce = h.get(HEADER_NONCE.lower())

        if not (principal_id and session_raw and signature_b64
                and timestamp_raw and nonce):
            return (None, _err("missing authentication headers"))

        try:
            timestamp = int(timestamp_raw)
        except (TypeError, ValueError):
            return (None, _err("invalid timestamp header"))

        assertion = _parse_assertion(session_raw)
        if not isinstance(assertion, dict):
            return (None, _err("invalid session assertion encoding"))

        # Step 3: resolve the claimed principal's public key (fail closed).
        try:
            principal_public_key = self._resolve_public_key(
                principal_id, now_ts
            )
        except Exception:
            # Registry unreachable / resolver raised -> FAIL CLOSED.
            return (None, _err("registry unreachable resolving principal"))
        if not principal_public_key:
            return (None, _err("unknown principal or no registered public key"))

        # Steps 4 & 5: verify the session assertion (signature + bind + expiry).
        try:
            session_public_key = verify_session_assertion(
                assertion, principal_public_key, now_ts=now_ts
            )
        except ExpiredError:
            return (None, _err("session assertion expired"))
        except SigningError:
            return (None, _err("session assertion invalid"))

        # Step 6: verify the per-request signature with the assertion's
        # session key (the cryptographically bound one, NOT the header hint).
        try:
            verify_request_signature(
                session_public_key, method, path, body_bytes,
                timestamp, nonce, signature_b64,
            )
        except SigningError:
            return (None, _err("request signature invalid"))

        # Step 7: freshness + single-use nonce -> stale / replay -> 401.
        if not timestamp_fresh(timestamp, now_ts, self.skew_seconds):
            return (None, _err("request timestamp stale or skewed"))
        if not self._nonce_cache.check_and_add(nonce, now_ts):
            return (None, _err("nonce replay detected"))

        return (principal_id, None)

    # -- public-key resolution + cache -------------------------------------

    def _resolve_public_key(self, principal_id, now_ts):
        # type: (str, float) -> Optional[str]
        """Resolved public key for ``principal_id``, cached for a short TTL.

        A cached ``None`` (unknown principal) is NOT stored — only positive
        resolutions are cached, so an unknown principal that later registers
        is picked up on its next request. Propagates resolver exceptions so
        the caller can fail closed.
        """
        cached = self._pubkey_cache.get(principal_id)
        if cached is not None:
            value, cached_at = cached
            if now_ts - cached_at < self.pubkey_cache_ttl:
                return value
        value = self._resolver(principal_id)
        if value:
            self._pubkey_cache[principal_id] = (value, now_ts)
        return value

    def _http_resolve_public_key(self, principal_id):
        # type: (str) -> Optional[str]
        """Default resolver: the Registry public-key authority (U14).

        Returns the ``public_key`` (which MAY be null) on 200, ``None`` on 404
        (unknown principal), and RAISES on any transport/other error so the
        authenticator fails closed.
        """
        resp = requests.get(
            "%s/principals/%s/public_key"
            % (self.registry_url, quote(principal_id, safe="")),
            timeout=self.http_timeout,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json().get("public_key")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _lower_headers(headers):
    # type: (object) -> dict
    """Case-insensitive header lookup map (accepts a dict or http.server
    ``Message``)."""
    lower = {}
    try:
        items = headers.items()
    except AttributeError:
        return lower
    for key, value in items:
        if key is not None:
            lower[str(key).lower()] = value
    return lower


def _parse_assertion(raw):
    # type: (object) -> Optional[dict]
    """Parse a session assertion carried as raw JSON or base64-of-JSON."""
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        pass
    try:
        decoded = base64.b64decode(raw.encode("ascii"))
        return json.loads(decoded)
    except Exception:
        return None
