// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import LoginForm from "./LoginForm";
import SessionProvider, { useSession, __resetSessionStoreForTests } from "@/lib/SessionProvider";
import { AGENTTRUST_USERNAME_MAP_KEY } from "@/lib/usernameMap";
import { buildKeyringBlob, generateKeypair, b64encode, type KeyringBlob } from "@/lib/agentCrypto";

// Fast KDF iteration count for test speed -- mirrors TEST_ITERATIONS in
// agentCrypto.test.ts. These tests exercise the REAL unlockKeyringBlob /
// buildKeyringBlob / buildSessionAssertion chain (no crypto mocking); only
// `fetch` and `next/navigation` are stubbed, so a passing test is real proof
// the login flow works end to end against realistic (if fast-KDF) material.
const TEST_ITERATIONS = 1000;
const PASSWORD = "correct horse battery staple";

// ---------------------------------------------------------------------------
// next/navigation mock
// ---------------------------------------------------------------------------

const pushMock = vi.fn();
const replaceMock = vi.fn();
const pathnameValue = "/login";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, replace: replaceMock }),
  usePathname: () => pathnameValue,
}));

// ---------------------------------------------------------------------------
// Test harness: renders LoginForm inside a real SessionProvider, plus a
// probe that surfaces the current session state in the DOM so assertions
// don't need to reach into React internals.
// ---------------------------------------------------------------------------

function SessionProbe() {
  const { session } = useSession();
  return (
    <div data-testid="session-probe">
      {session ? `principal:${session.principalId}|username:${session.username ?? ""}` : "signed-out"}
    </div>
  );
}

function renderLoginForm() {
  return render(
    <SessionProvider>
      <SessionProbe />
      <LoginForm />
    </SessionProvider>,
  );
}

function getIdentifierInput(): HTMLElement {
  return screen.getByLabelText(/username|principal id/i);
}

function getPasswordInput(): HTMLElement {
  return screen.getByLabelText(/^password$/i);
}

async function fillAndSubmit(identifier: string, password: string) {
  const user = userEvent.setup();
  const identifierInput = getIdentifierInput();
  const passwordInput = getPasswordInput();
  await user.clear(identifierInput);
  if (identifier) await user.type(identifierInput, identifier);
  await user.clear(passwordInput);
  if (password) await user.type(passwordInput, password);
  await user.click(screen.getByRole("button", { name: /sign in|try again/i }));
  return user;
}

interface Fixture {
  principalIdB64: string;
  blob: KeyringBlob;
}

async function makeFixture(): Promise<Fixture> {
  const { privateKey, publicKey } = generateKeypair();
  const { blob } = await buildKeyringBlob(PASSWORD, privateKey, TEST_ITERATIONS);
  return { principalIdB64: b64encode(publicKey), blob };
}

function mockFetchForFixture(fixture: Fixture) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url.startsWith("/api/auth/resolve")) {
      return new Response(
        JSON.stringify({ username: "bob", principal_id: fixture.principalIdB64 }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }
    if (url.startsWith("/api/vault/keyring")) {
      const requested = new URL(url, "http://test.local").searchParams.get("principal_id");
      if (requested === fixture.principalIdB64) {
        return new Response(JSON.stringify(fixture.blob), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response(JSON.stringify({ error: "keyring not found" }), { status: 404 });
    }
    if (url.startsWith("/api/auth/login")) {
      return new Response(JSON.stringify({ status: "ok" }), { status: 200 });
    }
    if (url === "/api/session") {
      return new Response(
        JSON.stringify({
          principal_id: fixture.principalIdB64,
          csrf_token: "csrf-login-test",
          expires_at: 1_900_000_000,
          idle_ttl_seconds: 1800,
        }),
        { status: 201, headers: { "Content-Type": "application/json" } },
      );
    }
    throw new Error(`unexpected fetch call in test: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

beforeEach(() => {
  pushMock.mockClear();
  replaceMock.mockClear();
  window.localStorage.clear();
  window.sessionStorage.clear();
  __resetSessionStoreForTests();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// Happy paths
// ---------------------------------------------------------------------------

describe("LoginForm", () => {
  it("happy path: correct username + password (same-device mapping) logs in and lands on the dashboard", async () => {
    const fixture = await makeFixture();
    window.localStorage.setItem(
      AGENTTRUST_USERNAME_MAP_KEY,
      JSON.stringify({ alice: fixture.principalIdB64 }),
    );
    const fetchMock = mockFetchForFixture(fixture);

    renderLoginForm();
    await fillAndSubmit("alice", PASSWORD);

    await waitFor(() => {
      expect(screen.getByTestId("session-probe")).toHaveTextContent(
        `principal:${fixture.principalIdB64}|username:alice`,
      );
    });

    expect(pushMock).toHaveBeenCalledWith("/");
    expect(window.localStorage.getItem("tessera-csrf")).toBe("csrf-login-test");
    expect(window.localStorage.getItem("tessera-session-expires-at")).toBe(
      "1900000000",
    );
    expect(fetchMock.mock.calls.some(([u]) => String(u).startsWith("/api/vault/keyring"))).toBe(true);
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([u]) => String(u).startsWith("/api/auth/login"))).toBe(true);
    });
  });

  it("happy path: correct principal_id + password (new-device toggle) logs in identically", async () => {
    const fixture = await makeFixture();
    // Deliberately no localStorage mapping -- this is the new-device path.
    const fetchMock = mockFetchForFixture(fixture);

    renderLoginForm();
    await userEvent.setup().click(screen.getByRole("button", { name: /use a different device/i }));
    expect(getIdentifierInput().getAttribute("placeholder") ?? "").toMatch(/principal_id/i);

    await fillAndSubmit(fixture.principalIdB64, PASSWORD);

    await waitFor(() => {
      expect(screen.getByTestId("session-probe")).toHaveTextContent(
        `principal:${fixture.principalIdB64}|username:`,
      );
    });
    expect(pushMock).toHaveBeenCalledWith("/");
    expect(fetchMock).toHaveBeenCalled();
  });

  // -------------------------------------------------------------------------
  // Error / edge paths
  // -------------------------------------------------------------------------

  it("error path: wrong password shows the unified 'incorrect password' message and re-enables the form", async () => {
    const fixture = await makeFixture();
    mockFetchForFixture(fixture);

    renderLoginForm();
    await userEvent.setup().click(screen.getByRole("button", { name: /use a different device/i }));
    await fillAndSubmit(fixture.principalIdB64, "definitely the wrong password");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/incorrect password/i);
    // Never a distinct "corrupted" message tier (KTD6).
    expect(alert).not.toHaveTextContent(/corrupt/i);

    // Form re-enables for another attempt: submit button not stuck disabled,
    // still reads "Sign in" (first failure carries a 0s cosmetic cooldown).
    const submitButton = screen.getByRole("button", { name: /sign in/i });
    expect(submitButton).toBeEnabled();
    expect(getIdentifierInput()).toBeEnabled();
    expect(getPasswordInput()).toBeEnabled();

    // No session was ever established.
    expect(screen.getByTestId("session-probe")).toHaveTextContent("signed-out");
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("edge case: rapid repeated failed attempts trigger an increasing, visible cooldown on the submit control", async () => {
    const fixture = await makeFixture();
    mockFetchForFixture(fixture);
    vi.useFakeTimers({ shouldAdvanceTime: true });

    try {
      renderLoginForm();
      await userEvent.setup({ advanceTimers: vi.advanceTimersByTime }).click(
        screen.getByRole("button", { name: /use a different device/i }),
      );

      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });

      // 1st failure: cosmetic cooldown is 0s, immediate retry allowed.
      await user.clear(getIdentifierInput());
      await user.type(getIdentifierInput(), fixture.principalIdB64);
      await user.clear(getPasswordInput());
      await user.type(getPasswordInput(), "wrong-1");
      await user.click(screen.getByRole("button", { name: /sign in/i }));
      await screen.findByRole("alert");
      expect(screen.getByRole("button", { name: /sign in/i })).toBeEnabled();

      // 2nd consecutive failure: a cooldown kicks in with a visible countdown
      // label, and the submit control is disabled for its duration.
      await user.clear(getPasswordInput());
      await user.type(getPasswordInput(), "wrong-2");
      await user.click(screen.getByRole("button", { name: /sign in/i }));
      await screen.findByRole("alert");

      const cooldownButton = await screen.findByRole("button", { name: /try again in \d+s/i });
      expect(cooldownButton).toBeDisabled();

      // The countdown actually counts down and eventually re-enables.
      await vi.advanceTimersByTimeAsync(3000);
      await waitFor(() => {
        expect(screen.getByRole("button", { name: /sign in/i })).toBeEnabled();
      });
    } finally {
      vi.useRealTimers();
    }
  }, 15_000);

  it("resolves a username through the Registry when this device has no local mapping", async () => {
    const fixture = await makeFixture();
    const fetchMock = mockFetchForFixture(fixture);
    // No mapping saved under "bob" -- this device has never seen that username.

    renderLoginForm();
    const user = userEvent.setup();
    await user.type(getIdentifierInput(), "bob");
    await user.type(getPasswordInput(), PASSWORD);
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => {
      expect(screen.getByTestId("session-probe")).toHaveTextContent(
        `principal:${fixture.principalIdB64}|username:bob`,
      );
    });
    expect(pushMock).toHaveBeenCalledWith("/");
    expect(fetchMock.mock.calls.some(([u]) => String(u).startsWith("/api/auth/resolve"))).toBe(true);
  });

  it("repairs a stale local username mapping from the Registry", async () => {
    const fixture = await makeFixture();
    window.localStorage.setItem(
      AGENTTRUST_USERNAME_MAP_KEY,
      JSON.stringify({ bob: "stale-principal" }),
    );
    const fetchMock = mockFetchForFixture(fixture);

    renderLoginForm();
    await fillAndSubmit("bob", PASSWORD);

    await waitFor(() => {
      expect(screen.getByTestId("session-probe")).toHaveTextContent(
        `principal:${fixture.principalIdB64}|username:bob`,
      );
    });
    expect(fetchMock.mock.calls.some(([u]) => String(u).startsWith("/api/auth/resolve"))).toBe(true);
  });

  it("error path: an unknown principal_id (server 404) shows a distinct 'no account found' message", async () => {
    const fixture = await makeFixture();
    mockFetchForFixture(fixture);

    renderLoginForm();
    await userEvent.setup().click(screen.getByRole("button", { name: /use a different device/i }));
    await fillAndSubmit("some-other-principal-id-not-in-vault", PASSWORD);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/no account found/i);
  });
});
