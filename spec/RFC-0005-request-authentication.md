# RFC-0005: AgentTrust Request Authentication

- **Status:** Draft
- **Date:** 2026-07-19
- **Depends on:** RFC-0001 (core vocabulary), RFC-0003 (P2P protocol, fail-closed precedent)
- **Implements:** Phase B.5 unit U15 (shared request-authentication middleware)

> The project name **AgentTrust** is a provisional placeholder, as is the
> `agenttrust.example` domain. Both will be replaced before any non-draft
> release; the *structure* of this protocol is what is specified.

The key words MUST, MUST NOT, REQUIRED, SHOULD, SHOULD NOT, and MAY are to be
interpreted as described in RFC 2119.

## 1. Motivation

Through Phase B, services trusted the `principal_id` a caller *claimed* in a
request body. Anyone who knew a principal's id could act as that principal:
there was no proof of possession of the principal's private key. This RFC
closes that no-auth gap with one shared authenticator (`libs/request_auth.py`)
that every service calls to verify WHO a request comes from, built on the
signing primitives of the shared library (U13, `libs/signing.py`) and the
Registry public-key authority (U14).

Two properties are load-bearing:

1. **Centralization.** Exactly one helper runs the verification, so the
   security-critical logic lives — and is reviewed — in one place. Services
   call `authenticate(...)`; they do not re-implement crypto.
2. **Opt-in backward compatibility.** Authentication is gated by a
   `require_signatures` flag. While it is off, the authenticator is a pure
   **no-op pass-through**: no headers are required, the Registry is never
   called, and every request is accepted (returns no principal, no error). A
   deployment can adopt the authenticator before the ecosystem has rolled over
   to signed requests, then flip the flag per service.

## 2. The two-link chain (recap)

Authentication proves possession of a principal's key across two links
(specified in full by U13):

1. **Principal → Session.** A stateless session *assertion* — JSON
   `{principal_id, session_public_key, issued_at, expires_at, signature}` —
   signed by the *principal's* long-term ed25519 key. In this MVP the
   `principal_id` IS the principal's base64 public key (the identity anchor);
   the assertion binds a short-lived *session* public key to it.
2. **Session → Request.** Each request carries a detached signature made by the
   *session's* private key over the canonical string
   `method \n path \n sha256(body) \n timestamp \n nonce`.

The verifier needs only the principal's public key (from the Registry) plus its
own clock; there is no session server and no stored session state.

## 3. Authentication headers

All values are strings (safe for `http.server`). Header-name constants live in
`libs/request_auth.py`.

| Header | Constant | Carries |
| ------ | -------- | ------- |
| `X-AT-Principal` | `HEADER_PRINCIPAL` | claimed `principal_id` (the identity to authenticate) |
| `X-AT-Session` | `HEADER_SESSION` | the session assertion, as raw JSON **or** base64-of-JSON |
| `X-AT-Session-Pub` | `HEADER_SESSION_PUB` | session public key hint (informational; the authoritative value is the one bound inside the assertion) |
| `X-AT-Signature` | `HEADER_SIGNATURE` | base64 per-request signature by the session key |
| `X-AT-Timestamp` | `HEADER_TIMESTAMP` | `int` epoch seconds, as signed |
| `X-AT-Nonce` | `HEADER_NONCE` | unique per-request nonce |

`X-AT-Principal`, `X-AT-Session`, `X-AT-Signature`, `X-AT-Timestamp`, and
`X-AT-Nonce` are REQUIRED when `require_signatures` is on. Clients produce the
set with `build_auth_headers(...)`, which signs the request and generates a
random nonce when one is not supplied.

`X-AT-Session-Pub` is a redundant hint only. Verification (§4, step 6) uses the
`session_public_key` **bound inside the assertion** — the value the principal
signed over — never the header, which an attacker could swap freely.

## 4. Verification — the 7 steps

`authenticate(method, path, body_bytes, headers, now_ts=None)` returns
`(principal_id, None)` on success or `(None, error)` on failure, where `error`
carries an HTTP status (always `401` here) and a message.

1. **Flag check.** If `require_signatures` is False → return `(None, None)`
   immediately. No Registry call, no error. (Backward-compat no-op.)
2. **Extract headers.** Missing any required header → **401**.
3. **Resolve principal key.** Fetch the claimed principal's public key from the
   Registry authority endpoint `GET /principals/{id}/public_key` (U14), cached
   for a short TTL (default 60 s). Unknown principal (404) or a null
   `public_key` → **401**. Registry **unreachable → 401 (FAIL CLOSED)** —
   mirroring the P2P precedent (`_check_p2p_permission` in
   `apps/marketplace/server/app.py` returns 502 on an unreachable Registry);
   here the failure is an *auth* failure, so it surfaces as 401, never as an
   accept.
4. **Verify session assertion.** `verify_session_assertion(assertion, key)` —
   a bad principal signature, or an embedded `principal_id` that does not match
   the resolved key, → **401**.
5. **Check expiry.** A session past its `expires_at` → **401**
   (`ExpiredError`).
6. **Verify request signature.** `verify_request_signature(...)` over the
   canonical `(method, path, body, timestamp, nonce)` using the assertion's
   bound session public key. Any mismatch (tampered body/method/path/timestamp/
   nonce, or wrong key) → **401**.
7. **Freshness + replay.** `timestamp_fresh` rejects a stale/far-future
   timestamp; a shared `NonceCache.check_and_add` rejects a reused nonce within
   the skew window. Either → **401**.

On success the authenticator returns the verified `principal_id`.

Only positive key resolutions are cached; a `None` (unknown principal) is not,
so a principal that registers after a first failed attempt is picked up on its
next request.

## 5. Separation of concerns: auth vs. authorization

The authenticator answers only *WHO* the caller is. It does **not** decide
whether that principal MAY perform the action. In particular, a request whose
verified `principal_id` differs from the identity the operation targets (e.g. a
body claiming to act *as* another principal) is a **403 identity mismatch** —
and raising that 403 is the **calling service's** responsibility, not the
authenticator's. The authenticator's only verdict is 401 (authenticated, or
not).

## 6. Error codes (summary)

| Code | Where | Meaning |
| ---- | ----- | ------- |
| 401 | authenticator | Missing headers, unknown principal / null key, bad session or request signature, expired session, stale timestamp, or replayed nonce — and Registry-unreachable (fail closed) |
| 403 | calling service | Verified principal is not permitted to act as / on the targeted identity (identity mismatch) — out of scope for the authenticator |

## 7. Reference implementation

- Authenticator + client header builder: `libs/request_auth.py`
  (`RequestAuthenticator`, `build_auth_headers`, the `HEADER_*` constants).
- Crypto primitives: `libs/signing.py` (U13, RFC via inline docs).
- Public-key authority: `GET /principals/{id}/public_key` in
  `registry/app.py` (U14).
- Tests: `tests/lib/test_request_auth.py` (real crypto, injected resolver —
  no live Registry).

*Scope note:* This unit ships the shared authenticator and its opt-in flag.
Wiring `require_signatures` on and enforcing it inside the Registry, Vault, P2P
apps, and agent-marketplace endpoints — plus the client-side signing rollout —
is the work of units U16–U20.
