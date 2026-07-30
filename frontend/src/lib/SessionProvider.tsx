"use client";

/**
 * App-wide session state (frontend unit U4) -- the first global client
 * state in this app; nothing else shares state across components today.
 *
 * Backed by `sessionStorage` (KTD4: survives an accidental reload within the
 * 15-minute TTL, isolated per tab, never a persistent cookie or
 * `localStorage`). Stores ONLY the ephemeral session keypair/assertion plus
 * the display `principal_id`/username -- never the password or the
 * long-term principal private key, which is discarded by the caller right
 * after `buildSessionAssertion` mints the session (mirrors the backend's own
 * `SessionContext.from_keyring_unlock` contract in `libs/session.py`: the
 * principal key "lives only for the duration of this call and is dropped on
 * return").
 *
 * Follows `ThemeToggle.tsx`'s established pattern exactly: a module-level
 * external store (plain variables + a listener array) read via
 * `useSyncExternalStore`, with `getServerSnapshot` always returning the
 * signed-out shape so SSR/first-paint never depends on browser storage, and
 * all storage access wrapped in defensive `try/catch` (private browsing,
 * disabled storage, corrupted JSON -- none of these should ever throw past
 * this module).
 *
 * Owns the expiry check (R5): compares the assertion's `expires_at` (epoch
 * seconds) to the client clock on an interval and on tab focus. This is a
 * clock-based check, not a signed-call 401 -- this deployment's
 * `require_signatures=False` default means no per-request signing exists to
 * ever produce that 401 (see `agentSession.ts`'s own scope note). Past
 * expiry: clear the session, set a "expired" notice, and redirect to
 * `/login` -- no silent refresh, since re-authentication needs the password
 * again. A non-blocking warning also surfaces a courtesy ~2 minutes before
 * the hard cutoff (i.e. around the 13-14 minute mark of the 15-minute TTL).
 */

import {
  createContext,
  useContext,
  useEffect,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { usePathname, useRouter } from "next/navigation";
import type { SessionAssertion } from "./agentSession";
import { clearStoredWebSessionMetadata } from "./agentSession";

// ---------------------------------------------------------------------------
// Stored session shape
// ---------------------------------------------------------------------------

export interface StoredSession {
  /** The base64 ed25519 public key that identifies this principal. */
  principalId: string;
  /** Display username, if this login happened via username mode; null on the principal_id (new-device) path. */
  username: string | null;
  /** Base64 public half of the freshly generated, ephemeral session keypair bound by `assertion`. */
  sessionPublicKey: string;
  /**
   * Base64 private half of that same ephemeral session keypair. Kept
   * alongside the assertion for any future per-request-signing consumer
   * (out of this unit's scope -- see `agentSession.ts`'s scope note); never
   * the long-term principal private key.
   */
  sessionPrivateKey: string;
  /** The signed claims vouching this session key may act for `principalId` until `expires_at`. */
  assertion: SessionAssertion;
}

export type SessionNotice = "expired" | null;

const SESSION_STORAGE_KEY = "agenttrust-session";

// ---------------------------------------------------------------------------
// External store (module-level, mirrors ThemeToggle.tsx's `listeners` array)
// ---------------------------------------------------------------------------

interface SessionStoreState {
  session: StoredSession | null;
  notice: SessionNotice;
  /**
   * False only for the SSR/first-hydration placeholder snapshot. Consumers
   * that redirect on "no session" (AppShell's route gate) must wait for this
   * to flip true before treating a null session as a real signed-out state
   * -- otherwise they'd redirect based on the placeholder itself, racing
   * ahead of `SessionProvider`'s own post-hydration correction (whose
   * passive effect, being on an ancestor fiber, always fires AFTER a
   * descendant's, per React's bottom-up effect order).
   */
  hydrated: boolean;
}

const SIGNED_OUT_STATE: SessionStoreState = { session: null, notice: null, hydrated: false };
const CONFIRMED_SIGNED_OUT_STATE: SessionStoreState = { session: null, notice: null, hydrated: true };

let storeState: SessionStoreState = SIGNED_OUT_STATE;
let hydrated = false;
let listeners: Array<() => void> = [];

function notify() {
  for (const l of listeners) l();
}

function subscribe(callback: () => void) {
  listeners.push(callback);
  return () => {
    listeners = listeners.filter((l) => l !== callback);
  };
}

function isStoredSessionShape(value: unknown): value is StoredSession {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.principalId === "string" &&
    candidate.principalId.length > 0 &&
    typeof candidate.sessionPublicKey === "string" &&
    typeof candidate.sessionPrivateKey === "string" &&
    typeof candidate.assertion === "object" &&
    candidate.assertion !== null &&
    typeof (candidate.assertion as { expires_at?: unknown }).expires_at === "number"
  );
}

function readSessionFromStorage(): StoredSession | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(SESSION_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as unknown;
    return isStoredSessionShape(parsed) ? parsed : null;
  } catch {
    // sessionStorage unavailable (private mode, etc.) or corrupted JSON --
    // treat as signed-out rather than throwing.
    return null;
  }
}

function persistSession(session: StoredSession | null) {
  if (typeof window === "undefined") return;
  try {
    if (session) {
      window.sessionStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(session));
    } else {
      window.sessionStorage.removeItem(SESSION_STORAGE_KEY);
    }
  } catch {
    // sessionStorage unavailable -- in-memory state still applies for the
    // rest of this page's life, it just won't survive a reload.
  }
}

/**
 * Server render (and first client render during hydration) always shows the
 * signed-out shape; `useSyncExternalStore` re-syncs with the real,
 * possibly-signed-in `sessionStorage` state right after mount. Mirrors
 * `ThemeToggle.tsx`'s `getServerSnapshot` exactly.
 */
function getServerSnapshot(): SessionStoreState {
  return SIGNED_OUT_STATE;
}

function getSnapshot(): SessionStoreState {
  if (!hydrated) {
    const session = readSessionFromStorage();
    storeState = session ? { session, notice: null, hydrated: true } : CONFIRMED_SIGNED_OUT_STATE;
    hydrated = true;
  }
  return storeState;
}

function setSessionState(next: StoredSession) {
  storeState = { session: next, notice: null, hydrated: true };
  hydrated = true;
  persistSession(next);
  notify();
}

function clearSessionState(notice: SessionNotice) {
  storeState = { session: null, notice, hydrated: true };
  hydrated = true;
  persistSession(null);
  clearStoredWebSessionMetadata();
  notify();
}

function clearNoticeState() {
  if (!storeState.notice) return;
  storeState = { ...storeState, notice: null };
  notify();
}

/**
 * Test/cleanup use only. `storeState`/`hydrated` are module-level (this
 * store is a true singleton, same as `ThemeToggle.tsx`'s `listeners`
 * pattern), so without this, one test's session/notice would silently leak
 * into the next test in the same file via the cached module state. Mirrors
 * `agentCrypto.ts`'s `terminatePbkdf2Worker()` test-hook pattern. Never
 * call this from application code.
 */
export function __resetSessionStoreForTests(): void {
  storeState = SIGNED_OUT_STATE;
  hydrated = false;
  listeners = [];
}

// ---------------------------------------------------------------------------
// Expiry check
// ---------------------------------------------------------------------------

/** How often the clock-based expiry check runs while a tab is open. */
const EXPIRY_CHECK_INTERVAL_MS = 10_000;
/** Courtesy warning lead time, seconds -- fires around the 13-14 minute mark of the 15-minute TTL. */
const EXPIRY_WARNING_LEAD_SECONDS = 120;

function secondsRemaining(session: StoredSession | null): number | null {
  if (!session) return null;
  return session.assertion.expires_at - Date.now() / 1000;
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

interface SessionContextValue {
  session: StoredSession | null;
  notice: SessionNotice;
  /**
   * False only for the SSR/first-hydration placeholder snapshot -- see
   * {@link SessionStoreState.hydrated}. Route guards (AppShell) must treat a
   * null `session` as "still checking", not "signed out", until this flips
   * true.
   */
  isHydrated: boolean;
  /** True once the active session is within the courtesy warning window and hasn't been dismissed. */
  isExpiringSoon: boolean;
  setSession: (session: StoredSession) => void;
  /** Explicit logout -- clears the session with no "expired" notice. */
  clearSession: () => void;
  clearNotice: () => void;
  dismissExpiryWarning: () => void;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export default function SessionProvider({ children }: { children: ReactNode }) {
  const store = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const router = useRouter();
  const pathname = usePathname();

  const { session, notice, hydrated: isHydrated } = store;

  const [warningDismissed, setWarningDismissed] = useState(false);
  const [isExpiringSoon, setIsExpiringSoon] = useState(false);

  // A newly established session should never inherit a stale dismissal from
  // a previous one -- reset the courtesy-warning state whenever the session
  // object itself changes (new login, or cleared). This is the "adjusting
  // state when a prop changes" pattern React's own docs recommend doing
  // during render (via a ref-like `useState` comparison) rather than in a
  // `useEffect`, which would cause an extra cascading render for what is
  // otherwise a synchronous derivation.
  const [lastSeenSession, setLastSeenSession] = useState(session);
  if (session !== lastSeenSession) {
    setLastSeenSession(session);
    setWarningDismissed(false);
    setIsExpiringSoon(false);
  }

  // The clock-based expiry check itself: on an interval and on tab focus,
  // per the plan's Approach. Always reads the CURRENT store state (not a
  // stale closure over `session`), so this effect only needs to run once.
  useEffect(() => {
    function checkExpiry() {
      const current = getSnapshot().session;
      const remaining = secondsRemaining(current);
      if (remaining === null) {
        return;
      }
      if (remaining <= 0) {
        clearSessionState("expired");
        return;
      }
      setIsExpiringSoon(remaining <= EXPIRY_WARNING_LEAD_SECONDS);
    }

    checkExpiry();
    const interval = setInterval(checkExpiry, EXPIRY_CHECK_INTERVAL_MS);
    window.addEventListener("focus", checkExpiry);
    return () => {
      clearInterval(interval);
      window.removeEventListener("focus", checkExpiry);
    };
  }, []);

  // Redirect to /login once an "expired" notice appears -- but only as a
  // reaction to the expiry transition itself, not a general "no session ->
  // redirect" route guard (that's a later unit's job, gating AppShell
  // routes). Skip the push if already on /login to avoid a redundant
  // navigation.
  useEffect(() => {
    if (notice === "expired" && pathname !== "/login") {
      router.replace("/login");
    }
  }, [notice, pathname, router]);

  const value: SessionContextValue = {
    session,
    notice,
    isHydrated,
    isExpiringSoon: isExpiringSoon && !warningDismissed,
    setSession: setSessionState,
    clearSession: () => clearSessionState(null),
    clearNotice: clearNoticeState,
    dismissExpiryWarning: () => setWarningDismissed(true),
  };

  return (
    <SessionContext.Provider value={value}>
      {children}
      {value.isExpiringSoon && (
        <div
          role="status"
          className="fixed bottom-[20px] right-[20px] z-50 max-w-[320px] box-border flex flex-row items-center gap-[12px] rounded-[12px] border border-[var(--ag-card-border)] bg-[var(--ag-card)] px-[16px] py-[12px] text-[13px] text-[var(--ag-text)] shadow-lg"
        >
          <span>Your session is about to expire. Save your work.</span>
          <button
            type="button"
            onClick={value.dismissExpiryWarning}
            className="shrink-0 border-0 bg-transparent p-0 text-[12px] text-[var(--ag-text-secondary)] underline cursor-pointer"
          >
            Dismiss
          </button>
        </div>
      )}
    </SessionContext.Provider>
  );
}

export function useSession(): SessionContextValue {
  const ctx = useContext(SessionContext);
  if (!ctx) {
    throw new Error("useSession must be used within a SessionProvider");
  }
  return ctx;
}
