// @vitest-environment jsdom
//
// Frontend unit U5: UserChip reads the real session instead of hardcoded
// mock text, and its logout action clears the session and redirects to
// /login. Mirrors the SessionProvider.test.tsx / LoginForm.test.tsx pattern
// (real SessionProvider, only next/navigation mocked).
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import UserChip from "./UserChip";
import SessionProvider, { useSession, __resetSessionStoreForTests, type StoredSession } from "@/lib/SessionProvider";
import { generateKeypair, b64encode } from "@/lib/agentCrypto";
import { buildSessionAssertion } from "@/lib/agentSession";

const pushMock = vi.fn();
const replaceMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, replace: replaceMock }),
  usePathname: () => "/",
}));

function makeSession(overrides: Partial<Pick<StoredSession, "principalId" | "username">> = {}): StoredSession {
  const principal = generateKeypair();
  const session = generateKeypair();
  const principalId = overrides.principalId ?? b64encode(principal.publicKey);
  const sessionPublicKeyB64 = b64encode(session.publicKey);
  const assertion = buildSessionAssertion(
    principalId,
    principal.privateKey,
    sessionPublicKeyB64,
    900,
  );
  return {
    principalId,
    username: overrides.username === undefined ? "alice" : overrides.username,
    sessionPublicKey: sessionPublicKeyB64,
    sessionPrivateKey: b64encode(session.privateKey),
    assertion,
  };
}

function SignInButton({ session }: { session: StoredSession }) {
  const { setSession } = useSession();
  return (
    <button type="button" onClick={() => setSession(session)}>
      sign-in
    </button>
  );
}

function renderChip(session: StoredSession) {
  return render(
    <SessionProvider>
      <SignInButton session={session} />
      <UserChip />
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

describe("UserChip", () => {
  it("shows the real session's username once signed in", async () => {
    renderChip(makeSession({ username: "alice" }));

    await act(async () => {
      screen.getByRole("button", { name: "sign-in" }).click();
    });

    expect(screen.getByText("alice")).toBeInTheDocument();
  });

  it("falls back to a truncated principal_id when there is no username (new-device path)", async () => {
    const longPrincipalId = b64encode(generateKeypair().publicKey);
    renderChip(makeSession({ principalId: longPrincipalId, username: null }));

    await act(async () => {
      screen.getByRole("button", { name: "sign-in" }).click();
    });

    expect(screen.queryByText(longPrincipalId)).not.toBeInTheDocument();
    expect(screen.getByText(longPrincipalId.slice(0, 8), { exact: false })).toBeInTheDocument();
  });

  it("logout clears the session and redirects to /login", async () => {
    const user = userEvent.setup();
    window.sessionStorage.setItem("tessera-csrf", "csrf-to-clear");
    window.sessionStorage.setItem("tessera-session-expires-at", "1900000000");
    renderChip(makeSession({ username: "alice" }));

    await act(async () => {
      screen.getByRole("button", { name: "sign-in" }).click();
    });
    expect(screen.getByText("alice")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Log out" }));

    expect(window.sessionStorage.getItem("agenttrust-session")).toBeNull();
    expect(window.sessionStorage.getItem("tessera-csrf")).toBeNull();
    expect(
      window.sessionStorage.getItem("tessera-session-expires-at"),
    ).toBeNull();
    expect(replaceMock).toHaveBeenCalledWith("/login");
  });
});
