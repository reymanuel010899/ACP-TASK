"use client";

/**
 * App-wide session state (frontend unit U4) -- the first global client
 * state in this app; nothing else shares state across components today.
 *
 * ---------------------------------------------------------------------------
 * Session lifetime: 30-minute sliding idle window, 12-hour absolute cap
 * ---------------------------------------------------------------------------
 *
 * The server-side session (`services/session/app.py`) is the authority. It
 * has always enforced exactly two cutoffs -- `SESSION_IDLE_TTL_SECONDS`
 * (1800) and `SESSION_ABSOLUTE_TTL_SECONDS` (43200) -- and it slides the
 * idle one on every successful resolve. This provider now mirrors THOSE
 * cutoffs.
 *
 * It previously used `assertion.expires_at` as the session clock instead.
 * That assertion is a one-shot identity proof with a fixed 15-minute TTL
 * (`agentSession.ts::DEFAULT_SESSION_TTL`) that is consumed the moment it is
 * exchanged for a cookie, so every login died after exactly 15 minutes no
 * matter how actively the app was being used, while the cookie it minted sat
 * there valid for another 11+ hours. The assertion is still stored (a future
 * per-request-signing consumer needs the session keypair it binds), but its
 * `expires_at` no longer governs anything.
 *
 * Two independent checks, whichever trips first:
 *
 *   - **Absolute**: `now >= absoluteExpiresAt`, the server's own
 *     `expires_at`. Activity does not extend it.
 *   - **Idle**: `now - lastActivityAt >= idleTtlSeconds`, where
 *     `lastActivityAt` tracks real user interaction (pointer, key, scroll,
 *     tab focus) -- NOT timer ticks, and NOT background network calls.
 *
 * Keeping the server's window in step is the job of {@link probeWebSession},
 * which is fired only from {@link recordActivity} and only every
 * {@link SERVER_TOUCH_INTERVAL_SECONDS}. That throttle is what makes the
 * idle window real: `GET /sessions/current` bumps `last_seen_at` server-side,
 * so polling it on a plain interval would keep an abandoned tab alive
 * forever. A probe that comes back `"expired"` (a genuine 401) ends the
 * session immediately; one that comes back `"unavailable"` (offline, BFF
 * restarting) is ignored, so a network blip never logs anyone out.
 *
 * ---------------------------------------------------------------------------
 * Storage
 * ---------------------------------------------------------------------------
 *
 * `localStorage`, superseding the original KTD4 choice of `sessionStorage`.
 * That choice tied the session to a single tab, so closing the tab signed
 * you out instantly even though the server session was still good -- which
 * flatly contradicts a 30-minute idle window. The stored record holds only
 * the ephemeral session keypair, the assertion, and the public
 * `principal_id`/username; never the password, never the principal's
 * long-term private key (the caller drops that right after
 * `buildSessionAssertion`, mirroring `libs/session.py`'s
 * `SessionContext.from_keyring_unlock` contract). The trade-off accepted
 * here: on a shared machine, the ephemeral session material now rests on
 * disk for the length of the idle window rather than dying with the tab.
 *
 * A `storage` listener keeps every open tab consistent: signing out in one
 * signs out the rest, and activity in one slides the window for all.
 *
 * Follows `ThemeToggle.tsx`'s established pattern: a module-level external
 * store (plain variables + a listener array) read via `useSyncExternalStore`,
 * with `getServerSnapshot` always returning the signed-out shape so
 * SSR/first-paint never depends on browser storage, and all storage access
 * wrapped in defensive `try/catch` (private browsing, disabled storage,
 * corrupted JSON -- none of these should ever throw past this module).
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
import {
  clearStoredWebSessionMetadata,
  normalizeIdleTtlSeconds,
  probeWebSession,
} from "./agentSession";

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
  /**
   * The signed claims vouching this session key may act for `principalId`.
   * Retained for that future signing consumer; its own `expires_at` is the
   * identity proof's, NOT this session's -- see the file header.
   */
  assertion: SessionAssertion;
  /** Epoch seconds. The server's absolute cutoff (12h); activity never extends it. */
  absoluteExpiresAt: number;
  /** The server's sliding idle window, seconds (30 min), as reported by the session service. */
  idleTtlSeconds: number;
  /** Epoch seconds of the last real user interaction. Slides the idle window. */
  lastActivityAt: number;
}

export type SessionNotice = "expired" | null;

const SESSION_STORAGE_KEY = "agenttrust-session";

/** How often the cutoff check runs while a tab is open. */
const EXPIRY_CHECK_INTERVAL_MS = 15_000;
/** Courtesy warning lead time, seconds, before whichever cutoff comes first. */
const EXPIRY_WARNING_LEAD_SECONDS = 120;
/**
 * Minimum gap between server-side idle-window refreshes. Well under the
 * 30-minute idle window, so the server's `last_seen_at` never lags client
 * activity enough to expire a session the user is actively using, while
 * still keeping these calls rare.
 */
const SERVER_TOUCH_INTERVAL_SECONDS = 300;
/** Minimum gap between writes of `lastActivityAt` to storage. */
const ACTIVITY_PERSIST_INTERVAL_SECONDS = 30;

function nowSeconds(): number {
  return Math.floor(Date.now() / 1000);
}

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

/**
 * Last real user interaction, epoch seconds. Deliberately NOT part of
 * `storeState`: it updates on every keystroke and scroll, and routing that
 * through the store would re-render the entire app on each one. The cutoff
 * check and the persisted copy both read it from here.
 */
let lastActivityAt = 0;
let lastPersistedActivityAt = 0;
let lastServerTouchAt = 0;

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
    // Records written before the idle/absolute split carry neither of these
    // and cannot be aged correctly, so they read as "no session" and the
    // user signs in once more. Failing closed beats inventing a cutoff.
    //
    // `idleTtlSeconds` is deliberately NOT required: it is the one field the
    // client can safely default (see `normalizeIdleTtlSeconds`). Requiring it
    // meant that a session service too old to report `idle_ttl_seconds` wrote
    // `undefined`, which `JSON.stringify` drops, so every stored record
    // failed this check and every full page load -- notably every OAuth
    // return -- bounced the user to /login.
    typeof candidate.absoluteExpiresAt === "number" &&
    typeof candidate.lastActivityAt === "number"
  );
}

function storage(): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function readSessionFromStorage(): StoredSession | null {
  try {
    const raw = storage()?.getItem(SESSION_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as unknown;
    if (!isStoredSessionShape(parsed)) return null;
    return {
      ...parsed,
      idleTtlSeconds: normalizeIdleTtlSeconds(parsed.idleTtlSeconds),
    };
  } catch {
    // Storage unavailable (private mode, etc.) or corrupted JSON -- treat as
    // signed-out rather than throwing.
    return null;
  }
}

function persistSession(session: StoredSession | null) {
  try {
    const store = storage();
    if (!store) return;
    if (session) {
      store.setItem(SESSION_STORAGE_KEY, JSON.stringify(session));
    } else {
      store.removeItem(SESSION_STORAGE_KEY);
    }
  } catch {
    // Storage unavailable -- in-memory state still applies for the rest of
    // this page's life, it just won't survive a reload.
  }
}

/**
 * Write the session out, always stamping the CURRENT `lastActivityAt`.
 *
 * The module-level `lastActivityAt` is the single source of truth for the
 * idle window; the copy inside `storeState.session` is only a serialization
 * detail and is allowed to go stale in memory. Routing every write through
 * here is what stops an unrelated persist (an adopted server expiry, say)
 * from silently rolling the stored window back to whenever the session
 * object was last replaced.
 */
function persistSessionWithActivity(session: StoredSession) {
  persistSession({ ...session, lastActivityAt });
}

/**
 * Server render (and first client render during hydration) always shows the
 * signed-out shape; `useSyncExternalStore` re-syncs with the real,
 * possibly-signed-in stored state right after mount. Mirrors
 * `ThemeToggle.tsx`'s `getServerSnapshot` exactly.
 */
function getServerSnapshot(): SessionStoreState {
  return SIGNED_OUT_STATE;
}

function getSnapshot(): SessionStoreState {
  if (!hydrated) {
    const session = readSessionFromStorage();
    if (session) {
      storeState = { session, notice: null, hydrated: true };
      // Resume the window where the last tab left it, rather than treating a
      // reopened tab as fresh activity -- otherwise closing and reopening
      // would reset the idle clock indefinitely.
      lastActivityAt = session.lastActivityAt;
      lastPersistedActivityAt = session.lastActivityAt;
    } else {
      storeState = CONFIRMED_SIGNED_OUT_STATE;
    }
    hydrated = true;
  }
  return storeState;
}

function setSessionState(next: StoredSession) {
  storeState = { session: next, notice: null, hydrated: true };
  hydrated = true;
  lastActivityAt = next.lastActivityAt;
  lastPersistedActivityAt = next.lastActivityAt;
  lastServerTouchAt = next.lastActivityAt;
  persistSession(next);
  notify();
}

function clearSessionState(notice: SessionNotice) {
  storeState = { session: null, notice, hydrated: true };
  hydrated = true;
  lastActivityAt = 0;
  lastPersistedActivityAt = 0;
  lastServerTouchAt = 0;
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
 * Adopt a refreshed absolute cutoff from the server. The server owns
 * `expires_at`; this keeps a long-lived tab honest if it ever changes (a
 * re-issued session, a reconfigured TTL) instead of trusting the value
 * captured at login forever.
 */
function adoptServerExpiry(absoluteExpiresAt: number, idleTtlSeconds: number) {
  const current = storeState.session;
  if (!current) return;
  if (
    current.absoluteExpiresAt === absoluteExpiresAt &&
    current.idleTtlSeconds === idleTtlSeconds
  ) {
    return;
  }
  const next = { ...current, absoluteExpiresAt, idleTtlSeconds };
  storeState = { ...storeState, session: next };
  persistSessionWithActivity(next);
  notify();
}

/**
 * Test/cleanup use only. The module-level state below makes this store a
 * true singleton (same as `ThemeToggle.tsx`'s `listeners` pattern), so
 * without this, one test's session/notice/activity would silently leak into
 * the next test in the same file via the cached module state. Mirrors
 * `agentCrypto.ts`'s `terminatePbkdf2Worker()` test-hook pattern. Never call
 * this from application code.
 */
export function __resetSessionStoreForTests(): void {
  storeState = SIGNED_OUT_STATE;
  hydrated = false;
  listeners = [];
  lastActivityAt = 0;
  lastPersistedActivityAt = 0;
  lastServerTouchAt = 0;
}

// ---------------------------------------------------------------------------
// Cutoff evaluation
// ---------------------------------------------------------------------------

/**
 * Seconds until this session ends, taking whichever cutoff comes first, or
 * `null` when there is no session. Zero or negative means it has ended.
 */
function secondsRemaining(session: StoredSession | null, now: number): number | null {
  if (!session) return null;
  const untilAbsolute = session.absoluteExpiresAt - now;
  const untilIdle = session.idleTtlSeconds - (now - lastActivityAt);
  return Math.min(untilAbsolute, untilIdle);
}

/**
 * Record genuine user interaction: slide the local idle window, persist it
 * (throttled), and periodically slide the SERVER's window to match. Returns
 * nothing and never throws -- it runs on high-frequency DOM events.
 */
function recordActivity(onExpired: () => void) {
  if (!storeState.session) return;
  const now = nowSeconds();
  lastActivityAt = now;

  if (now - lastPersistedActivityAt >= ACTIVITY_PERSIST_INTERVAL_SECONDS) {
    lastPersistedActivityAt = now;
    // Written straight to storage, leaving the store untouched: no consumer
    // renders `lastActivityAt`, so replacing the snapshot here would churn
    // `useSyncExternalStore`'s identity check and re-render the whole app
    // every 30 seconds for nothing.
    persistSessionWithActivity(storeState.session);
  }

  if (now - lastServerTouchAt >= SERVER_TOUCH_INTERVAL_SECONDS) {
    lastServerTouchAt = now;
    void probeWebSession().then((probe) => {
      if (probe === "expired") {
        onExpired();
      } else if (probe !== "unavailable") {
        adoptServerExpiry(probe.expires_at, probe.idle_ttl_seconds);
      }
      // "unavailable" -- offline or BFF hiccup. Keep the session; the next
      // activity retries, and the local cutoffs still bound it.
    });
  }
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

/** DOM events that count as the user still being here. */
const ACTIVITY_EVENTS = ["pointerdown", "keydown", "wheel", "scroll", "touchstart"] as const;

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

  // The cutoff check, activity tracking, and cross-tab sync. Always reads the
  // CURRENT store state (not a stale closure over `session`), so this effect
  // only needs to run once.
  useEffect(() => {
    function expire() {
      if (getSnapshot().session) {
        clearSessionState("expired");
      }
    }

    function checkExpiry() {
      const remaining = secondsRemaining(getSnapshot().session, nowSeconds());
      if (remaining === null) return;
      if (remaining <= 0) {
        expire();
        return;
      }
      setIsExpiringSoon(remaining <= EXPIRY_WARNING_LEAD_SECONDS);
    }

    function handleActivity() {
      // Cutoffs first: reopening a tab after the idle window elapsed must end
      // the session, not renew it on the very interaction that revealed it.
      checkExpiry();
      recordActivity(expire);
    }

    function handleFocus() {
      handleActivity();
    }

    function handleVisibility() {
      if (document.visibilityState === "visible") handleActivity();
    }

    /**
     * Another tab changed the shared record: re-read it so this tab sees the
     * same session, the same slid idle window, and the same sign-out.
     */
    function handleStorage(event: StorageEvent) {
      if (event.key !== null && event.key !== SESSION_STORAGE_KEY) return;
      const next = readSessionFromStorage();
      if (!next) {
        if (getSnapshot().session) clearSessionState(null);
        return;
      }
      lastActivityAt = Math.max(lastActivityAt, next.lastActivityAt);
      lastPersistedActivityAt = lastActivityAt;
      storeState = { session: next, notice: null, hydrated: true };
      hydrated = true;
      notify();
    }

    // A tab restored from storage may have been away long enough to have
    // aged out; settle that before anything renders against it, then let the
    // server have the final say on the cookie it cannot see from here.
    checkExpiry();
    if (getSnapshot().session) {
      lastServerTouchAt = nowSeconds();
      void probeWebSession().then((probe) => {
        if (probe === "expired") {
          expire();
        } else if (probe !== "unavailable") {
          adoptServerExpiry(probe.expires_at, probe.idle_ttl_seconds);
        }
      });
    }

    const interval = setInterval(checkExpiry, EXPIRY_CHECK_INTERVAL_MS);
    for (const name of ACTIVITY_EVENTS) {
      window.addEventListener(name, handleActivity, { passive: true });
    }
    window.addEventListener("focus", handleFocus);
    window.addEventListener("storage", handleStorage);
    document.addEventListener("visibilitychange", handleVisibility);
    return () => {
      clearInterval(interval);
      for (const name of ACTIVITY_EVENTS) {
        window.removeEventListener(name, handleActivity);
      }
      window.removeEventListener("focus", handleFocus);
      window.removeEventListener("storage", handleStorage);
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, []);

  // Redirect to /login once an "expired" notice appears -- but only as a
  // reaction to the expiry transition itself, not a general "no session ->
  // redirect" route guard (that's AppShell's job, gating protected routes).
  // Skip the push if already on /login to avoid a redundant navigation.
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
