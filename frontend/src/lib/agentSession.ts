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

/**
 * Lifetime of the signed *identity proof*, seconds. Mirrors
 * libs/signing.py::DEFAULT_SESSION_TTL.
 *
 * This is NOT how long a login lasts. The assertion is a one-shot proof
 * consumed by `POST /sessions` (the session service records its fingerprint
 * in `consumed_identity_proofs` and refuses to replay it); 15 minutes only
 * has to cover minting it and handing it over. Once exchanged, how long the
 * user stays signed in is owned entirely by the server-side session -- a
 * 30-minute sliding idle window and a 12-hour absolute cap, both configured
 * in `services/session/app.py` and reported back as `idle_ttl_seconds` /
 * `expires_at` on {@link WebSession}.
 *
 * `SessionProvider.tsx` used to treat this constant as the session clock,
 * which is why every login died after exactly 15 minutes regardless of what
 * the user was doing. It no longer reads it.
 */
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
  /** Epoch seconds -- the server's ABSOLUTE cutoff (12h), unaffected by activity. */
  expires_at: number;
  /** The server's sliding idle window in seconds (30 min). Served, never assumed. */
  idle_ttl_seconds: number;
}

export const WEB_SESSION_CSRF_STORAGE_KEY = "tessera-csrf";
export const WEB_SESSION_EXPIRY_STORAGE_KEY = "tessera-session-expires-at";

/**
 * Fallback idle window, seconds, mirroring `services/session/app.py`'s
 * `SESSION_IDLE_TTL_SECONDS` default.
 *
 * The server reports its real value as `idle_ttl_seconds` and that always
 * wins. This exists purely so a session service that predates that field
 * degrades to the correct default instead of poisoning the session with an
 * `undefined` window -- which `JSON.stringify` then drops entirely, leaving
 * a stored record that fails validation and signs the user out on every
 * single page load. Never treat a missing field from an older backend as a
 * reason to fail closed on something this visible.
 */
export const DEFAULT_IDLE_TTL_SECONDS = 1800;

/** Coerce a server-reported idle window into a usable number of seconds. */
export function normalizeIdleTtlSeconds(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0
    ? value
    : DEFAULT_IDLE_TTL_SECONDS;
}

/**
 * `localStorage`, not `sessionStorage`: the HttpOnly session cookie already
 * outlives the tab that created it (12h absolute), so keeping this metadata
 * per-tab meant a closed tab stranded a still-valid server session with no
 * CSRF token to ever revoke it. Kept in the same storage as
 * `SessionProvider.tsx`'s own session record so the two can never disagree
 * about whether a session exists.
 */
function metadataStore(): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

/** The stored CSRF token for the active web session, if any. */
export function readStoredCsrfToken(): string | null {
  try {
    return metadataStore()?.getItem(WEB_SESSION_CSRF_STORAGE_KEY) ?? null;
  } catch {
    return null;
  }
}

function persistWebSessionMetadata(session: WebSession): void {
  try {
    const store = metadataStore();
    if (!store) return;
    store.setItem(WEB_SESSION_CSRF_STORAGE_KEY, session.csrf_token);
    store.setItem(WEB_SESSION_EXPIRY_STORAGE_KEY, String(session.expires_at));
  } catch {
    // The HttpOnly cookie remains authoritative. Callers surface that CSRF
    // recovery is unavailable if browser storage is disabled.
  }
}

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
  const raw = (await response.json()) as WebSession;
  // Normalized at the boundary so no caller ever sees an absent idle window.
  const session: WebSession = {
    ...raw,
    idle_ttl_seconds: normalizeIdleTtlSeconds(raw.idle_ttl_seconds),
  };
  persistWebSessionMetadata(session);
  return session;
}

/**
 * Outcome of asking the session service whether the cookie session is still
 * good: the refreshed session, `"expired"` when the server has positively
 * rejected it (401 -- idle window elapsed, absolute cap hit, or revoked), or
 * `"unavailable"` when the question could not be answered at all.
 *
 * The third case is load-bearing: a network blip, an offline laptop or a
 * restarting BFF must NOT be read as "you are logged out". Callers treat
 * `"unavailable"` as "keep whatever you had and ask again later", so only a
 * real server verdict ever ends a session early.
 */
export type WebSessionProbe = WebSession | "expired" | "unavailable";

/**
 * Re-read the server-side session. This is also what SLIDES its idle window:
 * `GET /sessions/current` bumps `last_seen_at` on every successful resolve
 * (see `services/session/repository.py::resolve`), so this must only ever be
 * called in response to genuine user activity -- calling it on a bare timer
 * would keep an abandoned tab logged in forever, which is precisely the
 * behavior the 30-minute idle window exists to prevent.
 */
export async function probeWebSession(): Promise<WebSessionProbe> {
  let response: Response;
  try {
    response = await fetch("/api/session", {
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
    });
  } catch {
    return "unavailable";
  }
  if (response.status === 401) return "expired";
  if (!response.ok) return "unavailable";
  try {
    const session = (await response.json()) as WebSession;
    // `GET /sessions/current` does not re-issue the CSRF token, so preserve
    // the one minted at login rather than overwriting it with `undefined`.
    if (typeof session.expires_at !== "number") return "unavailable";
    try {
      metadataStore()?.setItem(
        WEB_SESSION_EXPIRY_STORAGE_KEY,
        String(session.expires_at),
      );
    } catch {
      // Non-fatal: the in-memory copy still drives this tab's clock.
    }
    return { ...session, idle_ttl_seconds: normalizeIdleTtlSeconds(session.idle_ttl_seconds) };
  } catch {
    return "unavailable";
  }
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
  try {
    const store = metadataStore();
    if (!store) return;
    store.removeItem(WEB_SESSION_CSRF_STORAGE_KEY);
    store.removeItem(WEB_SESSION_EXPIRY_STORAGE_KEY);
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
