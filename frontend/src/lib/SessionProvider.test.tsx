// @vitest-environment jsdom
//
// Covers SessionProvider's session-lifetime rules: a 30-minute sliding idle
// window and a 12-hour absolute cap, mirroring the server-side session
// service (`services/session/app.py`). These replaced the original
// "assertion.expires_at is the session clock" behavior, which capped every
// login at a flat 15 minutes regardless of activity -- the regression that
// test is guarded by is "the old assertion TTL no longer expires anything"
// below.
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";

import SessionProvider, {
  useSession,
  __resetSessionStoreForTests,
  type StoredSession,
} from "./SessionProvider";
import { generateKeypair, b64encode } from "./agentCrypto";
import { buildSessionAssertion } from "./agentSession";

const pushMock = vi.fn();
const replaceMock = vi.fn();
let pathnameValue = "/";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, replace: replaceMock }),
  usePathname: () => pathnameValue,
}));

const SESSION_STORAGE_KEY = "agenttrust-session";
const IDLE_TTL = 1800;
const ABSOLUTE_TTL = 43_200;

function nowSeconds(): number {
  return Math.floor(Date.now() / 1000);
}

/**
 * `assertionTtl` is deliberately independent of the session's own cutoffs --
 * that separation is the whole point of this unit's change.
 */
function makeSession(
  overrides: Partial<Pick<StoredSession, "absoluteExpiresAt" | "idleTtlSeconds" | "lastActivityAt">> = {},
  assertionTtl = 900,
): StoredSession {
  const principal = generateKeypair();
  const session = generateKeypair();
  const principalId = b64encode(principal.publicKey);
  const sessionPublicKeyB64 = b64encode(session.publicKey);
  const assertion = buildSessionAssertion(
    principalId,
    principal.privateKey,
    sessionPublicKeyB64,
    assertionTtl,
  );
  return {
    principalId,
    username: "alice",
    sessionPublicKey: sessionPublicKeyB64,
    sessionPrivateKey: b64encode(session.privateKey),
    assertion,
    absoluteExpiresAt: overrides.absoluteExpiresAt ?? nowSeconds() + ABSOLUTE_TTL,
    idleTtlSeconds: overrides.idleTtlSeconds ?? IDLE_TTL,
    lastActivityAt: overrides.lastActivityAt ?? nowSeconds(),
  };
}

/** A live session response from `GET|POST /api/session`. */
function okSessionResponse(expiresAt = nowSeconds() + ABSOLUTE_TTL) {
  return new Response(
    JSON.stringify({
      principal_id: "whatever",
      csrf_token: "csrf",
      expires_at: expiresAt,
      idle_ttl_seconds: IDLE_TTL,
    }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
}

let sessionToSet: StoredSession = makeSession();

function Harness() {
  const { session, notice, setSession } = useSession();
  return (
    <div>
      <div data-testid="session-state">{session ? "signed-in" : "signed-out"}</div>
      <div data-testid="notice-state">{notice ?? "none"}</div>
      <button type="button" onClick={() => setSession(sessionToSet)}>
        sign-in
      </button>
    </div>
  );
}

function renderProvider() {
  return render(
    <SessionProvider>
      <Harness />
    </SessionProvider>,
  );
}

async function signIn(session: StoredSession) {
  sessionToSet = session;
  await act(async () => {
    screen.getByRole("button", { name: "sign-in" }).click();
  });
}

/** Simulate real user interaction, the only thing that slides the idle window. */
async function interact() {
  await act(async () => {
    window.dispatchEvent(new Event("pointerdown"));
  });
}

beforeEach(() => {
  pathnameValue = "/";
  pushMock.mockClear();
  replaceMock.mockClear();
  window.localStorage.clear();
  window.sessionStorage.clear();
  __resetSessionStoreForTests();
  vi.stubGlobal("fetch", vi.fn(async () => okSessionResponse()));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("SessionProvider idle window", () => {
  it("integration: 30 minutes with no interaction expires the session and redirects to /login", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderProvider();
    await signIn(makeSession({ idleTtlSeconds: 60 }));
    expect(screen.getByTestId("session-state")).toHaveTextContent("signed-in");

    // Timer ticks are not activity -- only real interaction is.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(90_000);
    });

    await waitFor(() => {
      expect(screen.getByTestId("session-state")).toHaveTextContent("signed-out");
    });
    expect(screen.getByTestId("notice-state")).toHaveTextContent("expired");
    expect(replaceMock).toHaveBeenCalledWith("/login");
  }, 15_000);

  it("regression: interaction slides the window, so a session outlives the assertion's old 15-minute TTL", async () => {
    // This is the exact bug that made every login die after 15 minutes: the
    // assertion below still expires at 900s, and that must no longer matter.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderProvider();
    await signIn(makeSession({ idleTtlSeconds: IDLE_TTL }, 900));

    // 25 minutes of steady use, well past the assertion's expiry.
    for (let minute = 0; minute < 25; minute++) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(60_000);
      });
      await interact();
    }

    expect(screen.getByTestId("session-state")).toHaveTextContent("signed-in");
    expect(replaceMock).not.toHaveBeenCalled();
  }, 30_000);

  it("interaction refreshes the server's idle window, throttled rather than on every event", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderProvider();
    await signIn(makeSession());

    // A burst of interaction right after signing in must not produce a
    // request per event.
    await interact();
    await interact();
    await interact();
    expect(globalThis.fetch).not.toHaveBeenCalled();

    // Past the throttle interval, the next interaction does refresh it.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(301_000);
    });
    await interact();

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledTimes(1);
    });
    expect(String((globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0][0])).toBe(
      "/api/session",
    );
  }, 15_000);
});

describe("SessionProvider absolute cap", () => {
  it("expires at the absolute cutoff no matter how active the user is", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderProvider();
    await signIn(makeSession({ absoluteExpiresAt: nowSeconds() + 5 }));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });
    await interact();

    await waitFor(() => {
      expect(screen.getByTestId("session-state")).toHaveTextContent("signed-out");
    });
    expect(screen.getByTestId("notice-state")).toHaveTextContent("expired");
  }, 15_000);

  it("does not redirect when the expiry happened while already sitting on /login", async () => {
    pathnameValue = "/login";
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderProvider();
    await signIn(makeSession({ idleTtlSeconds: 5 }));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });

    await waitFor(() => {
      expect(screen.getByTestId("session-state")).toHaveTextContent("signed-out");
    });
    expect(replaceMock).not.toHaveBeenCalled();
  }, 15_000);
});

describe("SessionProvider server agreement", () => {
  it("a 401 from the session service ends the session immediately", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ error: "authentication required" }), { status: 401 })),
    );
    renderProvider();
    await signIn(makeSession());

    await act(async () => {
      await vi.advanceTimersByTimeAsync(301_000);
    });
    await interact();

    await waitFor(() => {
      expect(screen.getByTestId("session-state")).toHaveTextContent("signed-out");
    });
    expect(screen.getByTestId("notice-state")).toHaveTextContent("expired");
  }, 15_000);

  it("edge case: an unreachable session service does NOT sign the user out", async () => {
    // Offline laptops and BFF restarts must not read as "logged out" -- only
    // a real server verdict ends a session early.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("network down");
      }),
    );
    renderProvider();
    await signIn(makeSession());

    await act(async () => {
      await vi.advanceTimersByTimeAsync(301_000);
    });
    await interact();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_000);
    });

    expect(screen.getByTestId("session-state")).toHaveTextContent("signed-in");
    expect(replaceMock).not.toHaveBeenCalled();
  }, 15_000);
});

describe("SessionProvider storage", () => {
  it("integration: a session survives closing and reopening the tab", async () => {
    // localStorage, not sessionStorage -- the point of the storage change.
    window.localStorage.setItem(
      SESSION_STORAGE_KEY,
      JSON.stringify(makeSession({ lastActivityAt: nowSeconds() - 60 })),
    );

    renderProvider();

    await waitFor(() => {
      expect(screen.getByTestId("session-state")).toHaveTextContent("signed-in");
    });
    expect(replaceMock).not.toHaveBeenCalled();
  }, 15_000);

  it("a stored session that aged past its idle window is not restored", async () => {
    window.localStorage.setItem(
      SESSION_STORAGE_KEY,
      JSON.stringify(makeSession({ lastActivityAt: nowSeconds() - (IDLE_TTL + 60) })),
    );

    renderProvider();

    await waitFor(() => {
      expect(screen.getByTestId("session-state")).toHaveTextContent("signed-out");
    });
    expect(screen.getByTestId("notice-state")).toHaveTextContent("expired");
  }, 15_000);

  it("regression: a record missing idleTtlSeconds still restores, defaulted rather than discarded", async () => {
    // A session service too old to report `idle_ttl_seconds` produced
    // `idleTtlSeconds: undefined`, which JSON.stringify drops. When this
    // field was required, every stored record failed validation and every
    // full page load -- notably every OAuth return -- bounced to /login.
    const record = makeSession() as Partial<StoredSession>;
    delete record.idleTtlSeconds;
    window.localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(record));

    renderProvider();

    await waitFor(() => {
      expect(screen.getByTestId("session-state")).toHaveTextContent("signed-in");
    });
    expect(replaceMock).not.toHaveBeenCalled();
  }, 15_000);

  it("edge case: a record written before the idle/absolute fields existed is discarded, not aged blindly", async () => {
    const legacy = makeSession() as Partial<StoredSession>;
    delete legacy.absoluteExpiresAt;
    delete legacy.idleTtlSeconds;
    delete legacy.lastActivityAt;
    window.localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(legacy));

    renderProvider();

    expect(screen.getByTestId("session-state")).toHaveTextContent("signed-out");
  }, 15_000);

  it("signing out in another tab signs this one out too", async () => {
    renderProvider();
    await signIn(makeSession());
    expect(screen.getByTestId("session-state")).toHaveTextContent("signed-in");

    // What another tab's clearSession() leaves behind.
    window.localStorage.removeItem(SESSION_STORAGE_KEY);
    await act(async () => {
      window.dispatchEvent(
        new StorageEvent("storage", { key: SESSION_STORAGE_KEY, newValue: null }),
      );
    });

    expect(screen.getByTestId("session-state")).toHaveTextContent("signed-out");
  }, 15_000);
});
