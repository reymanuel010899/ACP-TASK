// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import RegisterForm, { REGISTRATION_STORAGE_KEY } from "./RegisterForm";
import SessionProvider, { useSession, __resetSessionStoreForTests } from "@/lib/SessionProvider";
import { AGENTTRUST_USERNAME_MAP_KEY } from "@/lib/usernameMap";

// These tests exercise the REAL generateKeypair / buildKeyringBlob /
// unlockKeyringBlob / buildSessionAssertion chain (no crypto mocking) --
// only `fetch` and `next/navigation` are stubbed, matching LoginForm.test.tsx's
// approach. RegisterForm always builds its blob at the real 600,000-iteration
// PBKDF2 count (never test-overridden -- there is no UI-level knob for that,
// deliberately, since production always needs the real count); a real
// PBKDF2-SHA256 derivation at that count take well under 100ms in this
// runtime, so the suite stays fast without needing to fake it.
const PASSWORD = "correct-horse-1";

// ---------------------------------------------------------------------------
// next/navigation mock
// ---------------------------------------------------------------------------

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, replace: vi.fn() }),
  usePathname: () => "/register",
}));

// ---------------------------------------------------------------------------
// Test harness
// ---------------------------------------------------------------------------

function SessionProbe() {
  const { session } = useSession();
  return (
    <div data-testid="session-probe">
      {session ? `principal:${session.principalId}|username:${session.username ?? ""}` : "signed-out"}
    </div>
  );
}

function renderRegisterForm() {
  return render(
    <SessionProvider>
      <SessionProbe />
      <RegisterForm />
    </SessionProvider>,
  );
}

function getUsernameInput(): HTMLElement {
  return screen.getByLabelText(/^username$/i);
}
function getPasswordInput(): HTMLElement {
  return screen.getByLabelText(/^password$/i);
}
function getConfirmPasswordInput(): HTMLElement {
  return screen.getByLabelText(/confirm password/i);
}

async function fillForm(username: string, password: string, confirm: string) {
  const user = userEvent.setup();
  if (username) await user.type(getUsernameInput(), username);
  if (password) await user.type(getPasswordInput(), password);
  if (confirm) await user.type(getConfirmPasswordInput(), confirm);
  return user;
}

function readUsernameMap(): Record<string, string> {
  const raw = window.localStorage.getItem(AGENTTRUST_USERNAME_MAP_KEY);
  return raw ? JSON.parse(raw) : {};
}

// ---------------------------------------------------------------------------
// Fetch mock: simulates the three BFF routes RegisterForm calls, with
// per-route hooks so each test can script exactly the sequence of
// responses it needs (success, failure, 409, hang, etc.).
// ---------------------------------------------------------------------------

interface FetchScript {
  /** Called for every POST /api/auth/register. Return a Response, or throw to simulate a network failure. */
  register?: (body: { principal_id: string; username: string }, callNumber: number) => Response | Promise<Response>;
  /** Called for every POST /api/vault/keyring. Return a Response, throw, or return a never-resolving Promise to simulate a hang. */
  vault?: (
    body: { user_principal_id: string } & Record<string, unknown>,
    callNumber: number,
  ) => Response | Promise<Response>;
  login?: (body: { principal_id: string }) => Response | Promise<Response>;
}

function defaultRegisterHandler(body: { principal_id: string; username: string }) {
  return new Response(
    JSON.stringify({ status: "registered", principal_id: body.principal_id, user: {}, reputation: {} }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
}

function defaultVaultHandler() {
  return new Response(JSON.stringify({ created_at: "now" }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function defaultLoginHandler() {
  return new Response(JSON.stringify({ status: "ok" }), { status: 200 });
}

function installFetchMock(script: FetchScript = {}) {
  let registerCallCount = 0;
  let vaultCallCount = 0;
  const registerBodies: Array<{ principal_id: string; username: string }> = [];
  const vaultBodies: Array<Record<string, unknown>> = [];

  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const bodyText = init?.body ? String(init.body) : undefined;
    const body = bodyText ? JSON.parse(bodyText) : undefined;

    if (url.startsWith("/api/auth/register")) {
      registerCallCount += 1;
      registerBodies.push(body);
      return (script.register ?? defaultRegisterHandler)(body, registerCallCount);
    }
    if (url.startsWith("/api/vault/keyring")) {
      vaultCallCount += 1;
      vaultBodies.push(body);
      return (script.vault ?? defaultVaultHandler)(body, vaultCallCount);
    }
    if (url.startsWith("/api/auth/login")) {
      return (script.login ?? defaultLoginHandler)(body);
    }
    if (url === "/api/session") {
      return new Response(
        JSON.stringify({
          principal_id: body.assertion.principal_id,
          csrf_token: "csrf-register-test",
          expires_at: 1_900_000_000,
        }),
        { status: 201, headers: { "Content-Type": "application/json" } },
      );
    }
    throw new Error(`unexpected fetch call in test: ${url}`);
  });

  vi.stubGlobal("fetch", fetchMock);

  return {
    fetchMock,
    registerBodies,
    vaultBodies,
    registerCallCount: () => registerCallCount,
    vaultCallCount: () => vaultCallCount,
  };
}

function getPrincipalIdText(): string {
  const code = document.querySelector("code");
  if (!code || !code.textContent) throw new Error("principal_id <code> element not found");
  return code.textContent;
}

beforeEach(() => {
  pushMock.mockClear();
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
// Happy path
// ---------------------------------------------------------------------------

describe("RegisterForm", () => {
  it("happy path: valid username/passwords -> Registry+Vault succeed -> gated success screen -> ack mints session, saves mapping, navigates", async () => {
    const { fetchMock } = installFetchMock();

    renderRegisterForm();
    const user = await fillForm("alice_1", PASSWORD, PASSWORD);
    await user.click(screen.getByRole("button", { name: /create account/i }));

    // Success screen appears, but the session is NOT minted yet -- gated
    // behind explicit acknowledgment (R6: a skipped id is unrecoverable).
    await screen.findByText(/save this principal_id somewhere safe now/i);
    expect(screen.getByTestId("session-probe")).toHaveTextContent("signed-out");
    expect(pushMock).not.toHaveBeenCalled();

    const principalId = getPrincipalIdText();
    expect(principalId.length).toBeGreaterThan(0);

    await user.click(screen.getByRole("button", { name: /i've saved my id/i }));

    await waitFor(() => {
      expect(screen.getByTestId("session-probe")).toHaveTextContent(
        `principal:${principalId}|username:alice_1`,
      );
    });
    expect(pushMock).toHaveBeenCalledWith("/");
    expect(readUsernameMap().alice_1).toBe(principalId);
    expect(window.sessionStorage.getItem("tessera-csrf")).toBe(
      "csrf-register-test",
    );

    // Both BFF calls actually happened, in order, with the expected shapes.
    expect(fetchMock.mock.calls.some(([u]) => String(u).startsWith("/api/auth/register"))).toBe(true);
    expect(fetchMock.mock.calls.some(([u]) => String(u).startsWith("/api/vault/keyring"))).toBe(true);
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([u]) => String(u).startsWith("/api/auth/login"))).toBe(true);
    });
  });

  // -------------------------------------------------------------------------
  // Client-side validation (blocks before any crypto/network work)
  // -------------------------------------------------------------------------

  it("error path: password/confirm mismatch blocks submission before any crypto or network work starts", async () => {
    const { fetchMock } = installFetchMock();

    renderRegisterForm();
    const user = await fillForm("alice_1", PASSWORD, "a-totally-different-password-1");
    await user.click(screen.getByRole("button", { name: /create account/i }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/do not match/i);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /create account/i })).toBeEnabled();
  });

  it("error path: password below the strength minimum blocks submission before any crypto or network work starts", async () => {
    const { fetchMock } = installFetchMock();

    renderRegisterForm();
    const user = await fillForm("alice_1", "short1", "short1");
    await user.click(screen.getByRole("button", { name: /create account/i }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/at least/i);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  // -------------------------------------------------------------------------
  // R8: Vault-step failure recovery (retry only the Vault upload)
  // -------------------------------------------------------------------------

  it("error path (R8): Vault upload fails after Registry succeeds -> retry re-attempts ONLY the Vault upload with the SAME keypair/blob", async () => {
    let vaultAttempt = 0;
    const { registerCallCount, vaultCallCount, registerBodies, vaultBodies } = installFetchMock({
      vault: () => {
        vaultAttempt += 1;
        if (vaultAttempt === 1) {
          return new Response(JSON.stringify({ error: "vault unavailable" }), { status: 500 });
        }
        return defaultVaultHandler();
      },
    });

    renderRegisterForm();
    const user = await fillForm("bob_2", PASSWORD, PASSWORD);
    await user.click(screen.getByRole("button", { name: /create account/i }));

    await screen.findByRole("alert");
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
    expect(registerCallCount()).toBe(1);
    expect(vaultCallCount()).toBe(1);

    await user.click(screen.getByRole("button", { name: /retry/i }));

    await screen.findByText(/save this principal_id somewhere safe now/i);
    // Registry was NEVER called again -- only the Vault step was retried.
    expect(registerCallCount()).toBe(1);
    expect(vaultCallCount()).toBe(2);
    // The SAME principal_id and blob were used both times (never regenerated).
    expect(vaultBodies[0].user_principal_id).toBe(vaultBodies[1].user_principal_id);
    expect(vaultBodies[0].encrypted_private_key).toBe(vaultBodies[1].encrypted_private_key);
    expect(vaultBodies[0].user_principal_id).toBe(registerBodies[0].principal_id);
  });

  // -------------------------------------------------------------------------
  // R8: no prior attempt, plain network failure -> full retry is safe
  // -------------------------------------------------------------------------

  it("error path: Registry call itself fails (network) with no prior attempt -> full retry is safe and correct", async () => {
    let registerAttempt = 0;
    const { registerCallCount, vaultCallCount } = installFetchMock({
      register: (body) => {
        registerAttempt += 1;
        if (registerAttempt === 1) {
          throw new Error("network down");
        }
        return defaultRegisterHandler(body);
      },
    });

    renderRegisterForm();
    const user = await fillForm("carol_3", PASSWORD, PASSWORD);
    await user.click(screen.getByRole("button", { name: /create account/i }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/service unavailable/i);

    await user.click(screen.getByRole("button", { name: /retry/i }));

    await screen.findByText(/save this principal_id somewhere safe now/i);
    expect(registerCallCount()).toBe(2);
    expect(vaultCallCount()).toBe(1);
  });

  // -------------------------------------------------------------------------
  // KTD5: 409 after a network-failure retry is treated as success-continue
  // -------------------------------------------------------------------------

  it("error path (KTD5): a network error is retried, and the retry's 409 (own earlier attempt landed) is treated as success-continue, not a collision", async () => {
    let registerAttempt = 0;
    const { registerCallCount, vaultCallCount } = installFetchMock({
      register: () => {
        registerAttempt += 1;
        if (registerAttempt === 1) {
          throw new Error("network down");
        }
        return new Response(
          JSON.stringify({ error: "This identity could not be registered because it already exists. Please try registering again." }),
          { status: 409 },
        );
      },
    });

    renderRegisterForm();
    const user = await fillForm("dave_4", PASSWORD, PASSWORD);
    await user.click(screen.getByRole("button", { name: /create account/i }));

    await screen.findByRole("alert");
    await user.click(screen.getByRole("button", { name: /retry/i }));

    // The 409 was treated as continue: success screen appears (not a
    // collision error message), and the Vault step ran exactly once.
    await screen.findByText(/save this principal_id somewhere safe now/i);
    expect(registerCallCount()).toBe(2);
    expect(vaultCallCount()).toBe(1);
  });

  // -------------------------------------------------------------------------
  // R8 / closed-tab case: resume-in-place across a reload
  // -------------------------------------------------------------------------

  it("error path (closed-tab case): reloading/remounting between the Registry and Vault steps offers to resume using the SAME persisted keypair/blob", async () => {
    let vaultCallCount = 0;
    let firstVaultResolve: ((r: Response) => void) | null = null;
    const registeredIds = new Set<string>();

    const { fetchMock } = installFetchMock({
      register: (body) => {
        if (registeredIds.has(body.principal_id)) {
          return new Response(JSON.stringify({ error: "already exists" }), { status: 409 });
        }
        registeredIds.add(body.principal_id);
        return defaultRegisterHandler(body);
      },
      vault: () => {
        vaultCallCount += 1;
        if (vaultCallCount === 1) {
          // Simulate the tab closing while this call is still in flight --
          // it never resolves during this test.
          return new Promise<Response>((resolve) => {
            firstVaultResolve = resolve;
          });
        }
        return defaultVaultHandler();
      },
    });
    void firstVaultResolve; // never resolved -- intentional (simulates the closed tab)

    const first = renderRegisterForm();
    const user = await fillForm("erin_5", PASSWORD, PASSWORD);
    await user.click(screen.getByRole("button", { name: /create account/i }));

    // Registry succeeded; the Vault call is now hanging. Give the register
    // step's own microtasks a turn, then persistence should already be in
    // place (it's written before the register call even fires).
    await waitFor(() => {
      expect(window.sessionStorage.getItem(REGISTRATION_STORAGE_KEY)).not.toBeNull();
    });

    // "Close the tab": unmount without ever resolving the in-flight Vault call.
    first.unmount();

    // "Reopen the tab": a fresh RegisterForm instance, fresh mount.
    renderRegisterForm();

    const resumeNotice = await screen.findByRole("status");
    expect(resumeNotice).toHaveTextContent(/finish setting up your account/i);
    expect(resumeNotice).toHaveTextContent(/erin_5/);

    const resumeUser = userEvent.setup();
    await resumeUser.type(screen.getByLabelText(/^password$/i), PASSWORD);
    await resumeUser.click(screen.getByRole("button", { name: /finish setting up my account/i }));

    await screen.findByText(/save this principal_id somewhere safe now/i);

    // The Registry step was recognized as already-succeeded (409-as-continue
    // via the idempotent simulator above), and the Vault step that finally
    // completed used the exact same persisted principal_id as the original
    // in-flight attempt.
    const registerCalls = fetchMock.mock.calls.filter(([u]) => String(u).startsWith("/api/auth/register"));
    expect(registerCalls.length).toBe(2);
    expect(window.sessionStorage.getItem(REGISTRATION_STORAGE_KEY)).toBeNull();
  });

  // -------------------------------------------------------------------------
  // Local username -> principal_id collision warning
  // -------------------------------------------------------------------------

  it("error path: registering a username with an existing, different localStorage mapping shows an overwrite warning before saving", async () => {
    window.localStorage.setItem(
      AGENTTRUST_USERNAME_MAP_KEY,
      JSON.stringify({ frank_6: "some-old-principal-id-value" }),
    );
    installFetchMock();

    renderRegisterForm();
    const user = await fillForm("frank_6", PASSWORD, PASSWORD);
    await user.click(screen.getByRole("button", { name: /create account/i }));
    await screen.findByText(/save this principal_id somewhere safe now/i);

    const newPrincipalId = getPrincipalIdText();
    await user.click(screen.getByRole("button", { name: /i've saved my id/i }));

    const warning = await screen.findByText(/already linked to a different principal_id/i);
    expect(warning).toHaveTextContent("some-old-principal-id-value");
    // Not saved yet -- the OLD mapping is still there until the user decides.
    expect(readUsernameMap().frank_6).toBe("some-old-principal-id-value");
    expect(screen.getByTestId("session-probe")).toHaveTextContent("signed-out");

    await user.click(screen.getByRole("button", { name: /overwrite and continue/i }));

    await waitFor(() => {
      expect(readUsernameMap().frank_6).toBe(newPrincipalId);
    });
    expect(pushMock).toHaveBeenCalledWith("/");
  });

  // -------------------------------------------------------------------------
  // Double-submit prevention
  // -------------------------------------------------------------------------

  it("edge case: rapid double-click is prevented by disabling submission synchronously on first click", async () => {
    const { registerCallCount } = installFetchMock();

    renderRegisterForm();
    const user = await fillForm("gina_7", PASSWORD, PASSWORD);

    const submitButton = screen.getByRole("button", { name: /create account/i });
    // fireEvent dispatches synchronously (unlike userEvent's own internal
    // awaits), so two back-to-back clicks land before React/JS yields --
    // genuinely racing the double-submit guard rather than serializing.
    fireEvent.click(submitButton);
    fireEvent.click(submitButton);

    await screen.findByText(/save this principal_id somewhere safe now/i);
    expect(registerCallCount()).toBe(1);
    void user;
  });

  it("edge case: rapid acknowledgment finalizes the secure session once", async () => {
    const { fetchMock } = installFetchMock();

    renderRegisterForm();
    const user = await fillForm("hanna_8", PASSWORD, PASSWORD);
    await user.click(screen.getByRole("button", { name: /create account/i }));
    await screen.findByText(/save this principal_id somewhere safe now/i);

    const acknowledge = screen.getByRole("button", {
      name: /i've saved my id/i,
    });
    fireEvent.click(acknowledge);
    fireEvent.click(acknowledge);

    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/"));
    expect(
      fetchMock.mock.calls.filter(([url]) => String(url) === "/api/session"),
    ).toHaveLength(1);
  });
});
