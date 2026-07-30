// @vitest-environment jsdom
//
// Supplements the U4 file list: the plan's "SessionProvider's clock-based
// check firing past expires_at clears state and redirects to /login" test
// scenario exercises SessionProvider itself, not LoginForm, so it lives in
// its own file rather than being force-fit into LoginForm.test.tsx.
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

function makeSession(ttlSeconds: number): StoredSession {
  const principal = generateKeypair();
  const session = generateKeypair();
  const principalId = b64encode(principal.publicKey);
  const sessionPublicKeyB64 = b64encode(session.publicKey);
  const assertion = buildSessionAssertion(
    principalId,
    principal.privateKey,
    sessionPublicKeyB64,
    ttlSeconds,
  );
  return {
    principalId,
    username: "alice",
    sessionPublicKey: sessionPublicKeyB64,
    sessionPrivateKey: b64encode(session.privateKey),
    assertion,
  };
}

function Harness() {
  const { session, notice, setSession } = useSession();
  return (
    <div>
      <div data-testid="session-state">{session ? "signed-in" : "signed-out"}</div>
      <div data-testid="notice-state">{notice ?? "none"}</div>
      <button type="button" onClick={() => setSession(makeSession(900))}>
        sign-in-far-future
      </button>
      <button
        type="button"
        onClick={() => setSession(makeSession(5))}
      >
        sign-in-near-expiry
      </button>
    </div>
  );
}

beforeEach(() => {
  pathnameValue = "/";
  pushMock.mockClear();
  replaceMock.mockClear();
  window.sessionStorage.clear();
  __resetSessionStoreForTests();
  const fetchMock = vi.fn(async () => {
    throw new Error("no network call should happen during the expiry check");
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("SessionProvider expiry", () => {
  it("integration: the clock-based check clears state and redirects to /login once expires_at passes, with no network call", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });

    render(
      <SessionProvider>
        <Harness />
      </SessionProvider>,
    );

    act(() => {
      screen.getByRole("button", { name: "sign-in-near-expiry" }).click();
    });
    expect(screen.getByTestId("session-state")).toHaveTextContent("signed-in");
    expect(replaceMock).not.toHaveBeenCalled();

    // Advance well past the 5-second expiry and past the provider's 10s
    // polling interval, so the clock-based check is guaranteed to have run.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });

    await waitFor(() => {
      expect(screen.getByTestId("session-state")).toHaveTextContent("signed-out");
    });
    expect(screen.getByTestId("notice-state")).toHaveTextContent("expired");
    expect(replaceMock).toHaveBeenCalledWith("/login");

    // The Approach note is explicit: expiry is enforced by comparing the
    // client clock to expires_at, NOT by a signed-call 401 -- no fetch
    // should ever have been triggered by this flow.
    expect(globalThis.fetch).not.toHaveBeenCalled();
  }, 15_000);

  it("a session far from expiry is left untouched by the interval check", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });

    render(
      <SessionProvider>
        <Harness />
      </SessionProvider>,
    );

    act(() => {
      screen.getByRole("button", { name: "sign-in-far-future" }).click();
    });
    expect(screen.getByTestId("session-state")).toHaveTextContent("signed-in");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });

    expect(screen.getByTestId("session-state")).toHaveTextContent("signed-in");
    expect(replaceMock).not.toHaveBeenCalled();
  }, 15_000);

  it("does not redirect when the expiry already happened while sitting on /login itself", async () => {
    pathnameValue = "/login";
    vi.useFakeTimers({ shouldAdvanceTime: true });

    render(
      <SessionProvider>
        <Harness />
      </SessionProvider>,
    );

    act(() => {
      screen.getByRole("button", { name: "sign-in-near-expiry" }).click();
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });

    await waitFor(() => {
      expect(screen.getByTestId("session-state")).toHaveTextContent("signed-out");
    });
    // Already on /login -- no redundant navigation.
    expect(replaceMock).not.toHaveBeenCalled();
  }, 15_000);
});
