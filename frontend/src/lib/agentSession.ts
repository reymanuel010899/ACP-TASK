/**
 * Session-assertion minting (frontend unit U2).
 *
 * A byte-compatible TypeScript port of `libs/signing.py`'s
 * `build_session_assertion` -- issuing a stateless session assertion signed
 * by the *principal's* long-term ed25519 key.
 *
 * There is no session server and no stored state: the assertion is plain
 * JSON claims `{principal_id, session_public_key, issued_at, expires_at}`
 * plus a detached signature. A verifier (the backend, via
 * `libs/signing.py::verify_session_assertion`) checks the signature against
 * the principal's known public key and the expiry against its own clock.
 *
 * Scope note: this module mints assertions only. It deliberately does NOT
 * implement per-request canonical-string signing or the `X-AT-*` header set
 * from `libs/request_auth.py` -- see the U2 unit's Approach note in the
 * frontend login/register plan for why that was cut (no consumer in this
 * plan calls per-request signing; Registry/Vault run with
 * `require_signatures=False`). That work belongs to the phase-B5
 * session-signature-auth plan, not here.
 */

import { sign } from "./agentCrypto";

// ---------------------------------------------------------------------------
// Constants (mirror libs/signing.py)
// ---------------------------------------------------------------------------

/** Default session lifetime, seconds. Mirrors libs/signing.py::DEFAULT_SESSION_TTL. */
export const DEFAULT_SESSION_TTL = 900; // 15 minutes

// ---------------------------------------------------------------------------
// Errors
// ---------------------------------------------------------------------------

export class SessionAssertionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SessionAssertionError";
  }
}

// ---------------------------------------------------------------------------
// Base64 (mirrors agentCrypto.ts's own helpers -- kept local so this module
// has no hidden coupling to agentCrypto.ts beyond the `sign` primitive it is
// explicitly meant to call into).
// ---------------------------------------------------------------------------

function b64encode(raw: Uint8Array): string {
  if (typeof Buffer !== "undefined") {
    return Buffer.from(raw).toString("base64");
  }
  let binary = "";
  for (let i = 0; i < raw.length; i++) {
    binary += String.fromCharCode(raw[i]);
  }
  return btoa(binary);
}

// ---------------------------------------------------------------------------
// Session assertion shape
// ---------------------------------------------------------------------------

export interface SessionAssertion {
  principal_id: string;
  session_public_key: string;
  issued_at: number;
  expires_at: number;
  signature: string;
}

export interface WebSession {
  principal_id: string;
  csrf_token: string;
  expires_at: number;
}

export const WEB_SESSION_CSRF_STORAGE_KEY = "tessera-csrf";
export const WEB_SESSION_EXPIRY_STORAGE_KEY = "tessera-session-expires-at";

/**
 * Exchange the signed identity assertion for an opaque HttpOnly BFF session.
 * The returned CSRF token may be kept in memory; identity and authentication
 * remain bound exclusively to the server-side session cookie.
 */
export async function establishWebSession(
  assertion: SessionAssertion,
): Promise<WebSession> {
  const response = await fetch("/api/session", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ assertion }),
  });
  if (!response.ok) {
    throw new SessionAssertionError("failed to establish authenticated session");
  }
  const session = (await response.json()) as WebSession;
  try {
    window.sessionStorage.setItem(WEB_SESSION_CSRF_STORAGE_KEY, session.csrf_token);
    window.sessionStorage.setItem(
      WEB_SESSION_EXPIRY_STORAGE_KEY,
      String(session.expires_at),
    );
  } catch {
    // The HttpOnly cookie remains authoritative. Callers surface that CSRF
    // recovery is unavailable if browser session storage is disabled.
  }
  return session;
}

export async function revokeWebSession(csrfToken: string): Promise<void> {
  const response = await fetch("/api/session", {
    method: "DELETE",
    credentials: "same-origin",
    headers: { "X-CSRF-Token": csrfToken },
  });
  if (!response.ok && response.status !== 401) {
    throw new SessionAssertionError("failed to revoke authenticated session");
  }
  clearStoredWebSessionMetadata();
}

export function clearStoredWebSessionMetadata(): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(WEB_SESSION_CSRF_STORAGE_KEY);
    window.sessionStorage.removeItem(WEB_SESSION_EXPIRY_STORAGE_KEY);
  } catch {
    // Storage unavailable; there is no readable cookie material to clear.
  }
}

/**
 * Canonical byte string the principal signs for a session assertion.
 *
 * Compact, key-sorted JSON of exactly the bound claims -- so both signer and
 * verifier reconstruct identical bytes regardless of dict/object ordering.
 * Mirrors `libs/signing.py::_canonical_session_bytes` field-for-field: keys
 * sorted alphabetically (`expires_at`, `issued_at`, `principal_id`,
 * `session_public_key`), no whitespace (Python's `separators=(",", ":")`,
 * which `JSON.stringify` already matches by default).
 *
 * `principal_id` and `session_public_key` are always base64 (ASCII-only)
 * strings in practice, so JSON string-escaping differences between Python's
 * `ensure_ascii=True` default and JS's `JSON.stringify` never come into
 * play here.
 */
function canonicalSessionBytes(
  principalId: string,
  sessionPublicKeyB64: string,
  issuedAt: number,
  expiresAt: number,
): Uint8Array {
  // Object key insertion order below IS the alphabetical order, so
  // JSON.stringify's (spec-guaranteed) insertion-order serialization of
  // string keys produces the same key order as Python's sort_keys=True.
  const claims = {
    expires_at: expiresAt,
    issued_at: issuedAt,
    principal_id: principalId,
    session_public_key: sessionPublicKeyB64,
  };
  return new TextEncoder().encode(JSON.stringify(claims));
}

/**
 * Issue a stateless session assertion signed by the principal key.
 *
 * `principalPrivateKey` is the principal's 32-byte ed25519 seed (as
 * produced by `agentCrypto.ts::generateKeypair`/`unlockKeyringBlob`).
 * `sessionPublicKeyB64` is the base64 public half of a freshly generated,
 * ephemeral *session* keypair (minted by the caller via
 * `agentCrypto.ts::generateKeypair` -- this module only signs the claims
 * binding it to the principal, it does not generate that keypair itself).
 *
 * `issuedAt`/`expiresAt` are epoch seconds (`int(now_ts)` truncation, same
 * as `libs/signing.py`). `nowTs` defaults to the current time (seconds,
 * fractional) but may be injected for deterministic issuance in tests.
 *
 * Mirrors `libs/signing.py::build_session_assertion` field-for-field.
 * Throws {@link SessionAssertionError} if `principalId`/`sessionPublicKeyB64`
 * are empty, or if `principalPrivateKey` cannot produce a signature (e.g.
 * wrong length).
 */
export function buildSessionAssertion(
  principalId: string,
  principalPrivateKey: Uint8Array,
  sessionPublicKeyB64: string,
  ttlSeconds: number = DEFAULT_SESSION_TTL,
  nowTs: number = Date.now() / 1000,
): SessionAssertion {
  if (!principalId) {
    throw new SessionAssertionError("principal_id must be a non-empty string");
  }
  if (!sessionPublicKeyB64) {
    throw new SessionAssertionError("session_public_key must be a non-empty string");
  }

  const issuedAt = Math.trunc(nowTs);
  const expiresAt = issuedAt + Math.trunc(ttlSeconds);
  const message = canonicalSessionBytes(principalId, sessionPublicKeyB64, issuedAt, expiresAt);

  let signature: Uint8Array;
  try {
    signature = sign(message, principalPrivateKey);
  } catch (err) {
    throw new SessionAssertionError(
      `failed to sign session assertion: ${err instanceof Error ? err.message : String(err)}`,
    );
  }

  return {
    principal_id: principalId,
    session_public_key: sessionPublicKeyB64,
    issued_at: issuedAt,
    expires_at: expiresAt,
    signature: b64encode(signature),
  };
}
