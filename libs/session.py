"""Client-side session context (Phase B.5, unit U20).

The bridge between the U7 keyring-unlock flow, the stateless session model of
:mod:`libs.signing`, and the per-request signing of :mod:`libs.request_auth`.

A :class:`SessionContext` bundles the three things a client needs to sign every
outbound request as a principal:

* the ``principal_id`` (the identity anchor — a base64 ed25519 public key);
* an *ephemeral* session KeyPair, generated locally and never persisted; and
* a stateless ``session_assertion`` (JSON + a detached signature made by the
  *principal's* long-term key) vouching that this session key may act for the
  principal until it expires.

The principal's long-term signing key is used ONCE — to sign the assertion at
:meth:`SessionContext.create` — and can then be discarded by the caller. Every
subsequent request is signed by the short-lived session key, so the principal
secret need not linger in memory. :meth:`SessionContext.from_keyring_unlock`
makes that explicit: it unlocks the Vault keyring (U7), derives the principal
key from the recovered private-key bytes, mints the session, and drops the
principal key on return.

Service client libraries (``VaultClient``, ``P2PClient``,
``AgentCoordinator``, ...) accept an optional ``session`` and call
:meth:`auth_headers` before each request, so signing is transparent: the same
call site works signed or unsigned depending only on whether a session was
supplied.
"""

import time

from libs import request_auth, signing


class SessionContext(object):
    """A signed session a client uses to authenticate requests as a principal.

    Construct with :meth:`create` (from a principal signing key) or
    :meth:`from_keyring_unlock` (from a Vault keyring + password). Then call
    :meth:`auth_headers` to produce the ``X-AT-*`` header set for one request.
    """

    __slots__ = ("principal_id", "session", "assertion")

    def __init__(self, principal_id, session, assertion):
        # type: (str, signing.KeyPair, dict) -> None
        self.principal_id = principal_id
        self.session = session
        self.assertion = assertion

    # -- construction ------------------------------------------------------

    @classmethod
    def create(cls, principal_id, principal_signing_key,
               ttl=signing.DEFAULT_SESSION_TTL, now_ts=None):
        # type: (str, object, int, float) -> SessionContext
        """Mint a session for ``principal_id`` signed by its principal key.

        Generates a fresh ephemeral session keypair locally and has the
        principal key (a :class:`~libs.signing.KeyPair` or raw
        ``nacl.signing.SigningKey``) sign a stateless assertion binding that
        session key to the principal. The principal key is not retained; the
        caller may discard it after this call. ``now_ts`` may be injected for
        deterministic issuance (e.g. an intentionally-past expiry in tests).
        """
        session = signing.generate_keypair()
        assertion = signing.build_session_assertion(
            principal_id,
            principal_signing_key,
            session.public_key_b64(),
            ttl_seconds=ttl,
            now_ts=now_ts,
        )
        return cls(principal_id, session, assertion)

    @classmethod
    def from_keyring_unlock(cls, vault_client, password, principal_id,
                            ttl=signing.DEFAULT_SESSION_TTL, now_ts=None):
        # type: (object, str, str, int, float) -> SessionContext
        """Unlock a Vault keyring (U7) and mint a session from the result.

        Fetches the principal's wrapped keyring blob, unlocks it with
        ``password`` to recover the private-key bytes, reconstructs the
        principal signing key, and issues a fresh session. The recovered
        principal key lives only for the duration of this call and is dropped
        on return — every later request is signed by the session key alone.

        The recovered ``private_key`` bytes are the 32-byte ed25519 seed the
        principal keyring stored (the same bytes as
        :meth:`~libs.signing.KeyPair.signing_key_b64` decodes to), so the
        derived public key equals ``principal_id`` in this MVP.
        """
        blob = vault_client.fetch_keyring(principal_id)
        _dek, private_key = vault_client.unlock_keyring(password, blob)
        principal_key = signing.load_signing_key(signing.b64encode(private_key))
        return cls.create(
            principal_id, principal_key.signing_key, ttl=ttl, now_ts=now_ts
        )

    # -- per-request signing ----------------------------------------------

    def auth_headers(self, method, path, body_bytes, now_ts=None, nonce=None):
        # type: (str, str, bytes, float, str) -> dict
        """The ``X-AT-*`` header set signing one request with this session.

        Signs the EXACT ``body_bytes`` that will go on the wire over
        ``(method, path, body)``; a random ``nonce`` and the current time are
        used unless supplied (both overridable so tests can craft replay or
        expiry cases). Delegates to :func:`libs.request_auth.build_auth_headers`.
        """
        if now_ts is None:
            now_ts = time.time()
        if body_bytes is None:
            body_bytes = b""
        return request_auth.build_auth_headers(
            self.principal_id,
            self.assertion,
            self.session.signing_key,
            method,
            path,
            body_bytes,
            now_ts=now_ts,
            nonce=nonce,
        )
