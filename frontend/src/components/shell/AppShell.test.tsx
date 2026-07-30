// @vitest-environment jsdom
//
// Frontend unit U5: AppShell is the session gate for every route it wraps
// (R7). These tests exercise that gate directly against a real
// SessionProvider (only `next/navigation` is mocked), mirroring the pattern
// established by LoginForm.test.tsx / SessionProvider.test.tsx.
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";

import AppShell from "./AppShell";
import SessionProvider, { useSession, __resetSessionStoreForTests, type StoredSession } from "@/lib/SessionProvider";
import { generateKeypair, b64encode } from "@/lib/agentCrypto";
import { buildSessionAssertion } from "@/lib/agentSession";

const pushMock = vi.fn();
const replaceMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, replace: replaceMock }),
  usePathname: () => "/",
}));

function makeSession(ttlSeconds = 900): StoredSession {
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

function SignInButton() {
  const { setSession } = useSession();
  return (
    <button type="button" onClick={() => setSession(makeSession())}>
      sign-in
    </button>
  );
}

function renderShell() {
  return render(
    <SessionProvider>
      <SignInButton />
      <AppShell active="dashboard">
        <div data-testid="protected-content">secret dashboard content</div>
      </AppShell>
    </SessionProvider>,
  );
}

beforeEach(() => {
  pushMock.mockClear();
  replaceMock.mockClear();
  window.sessionStorage.clear();
  __resetSessionStoreForTests();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("AppShell session gate", () => {
  it("redirects to /login and renders nothing when there is no active session", async () => {
    renderShell();

    expect(screen.queryByTestId("protected-content")).not.toBeInTheDocument();
    expect(replaceMock).toHaveBeenCalledWith("/login");
  });

  it("renders the shell content once a session is established, with no redirect", async () => {
    renderShell();
    // The initial mount (no session yet) already redirected once, as covered
    // by the previous test -- clear that call so this test only asserts on
    // what happens after signing in.
    replaceMock.mockClear();

    await act(async () => {
      screen.getByRole("button", { name: "sign-in" }).click();
    });

    expect(screen.getByTestId("protected-content")).toBeInTheDocument();
    expect(replaceMock).not.toHaveBeenCalledWith("/login");
  });
});
