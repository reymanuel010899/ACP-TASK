"use client";

/**
 * Login form (frontend unit U4).
 *
 * A single identifier field that defaults to "username" mode; toggling
 * "use a different device" relabels the SAME field to "principal_id" mode
 * (placeholder/validation swap accordingly) rather than revealing a second
 * field. If a username has no local `principal_id` mapping on this device,
 * the field auto-switches into "principal_id" mode with inline copy
 * explaining why, rather than a bare error.
 *
 * Flow: identifier + password -> (username mode) look up `principal_id` via
 * `usernameMap.ts` -> `GET /api/vault/keyring?principal_id=...` (U3) ->
 * `unlockKeyringBlob` (U1, agentCrypto.ts) -> on success, mint an ephemeral
 * session keypair + `buildSessionAssertion` (U2, agentSession.ts) -> store
 * via `SessionProvider` -> best-effort, non-blocking `POST /api/auth/login`
 * -> navigate to the dashboard.
 *
 * The password is captured into a local variable (`capturedPassword`) once,
 * before the PBKDF2 work starts, rather than re-read from the controlled
 * input mid-computation (the Approach note's explicit instruction) -- the
 * input is also disabled for the duration via the `loading` flag, but this
 * is defense-in-depth against that value ever silently drifting mid-flight.
 *
 * Wrong password and a corrupted blob are cryptographically indistinguishable
 * (`VaultAuthError` either way) -- both surface the same unified "incorrect
 * password" message (KTD6), never a separate "corrupted" tier.
 *
 * Repeated failed unlock attempts add an increasing, purely cosmetic
 * client-side delay before the next attempt is allowed (KTD9) -- the Vault's
 * `GET /keyring/{id}` has no server-side rate limit, so this is
 * defense-in-depth only, not real protection.
 */

import { useEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import {
  VaultAuthError,
  b64encode,
  generateKeypair,
  unlockKeyringBlob,
  type KeyringBlob,
} from "@/lib/agentCrypto";
import { buildSessionAssertion, establishWebSession } from "@/lib/agentSession";
import { useSession } from "@/lib/SessionProvider";
import { lookupPrincipalId } from "@/lib/usernameMap";

type IdentifierMode = "username" | "principal_id";

/**
 * Cosmetic, increasing delay (seconds) before the next attempt is allowed,
 * keyed by how many consecutive failures have happened so far. The first
 * failure allows an immediate retry; each one after that doubles the wait,
 * capped at 16s. Purely a UI speed bump (KTD9) -- never real rate limiting.
 */
function cooldownSecondsForFailureCount(failureCount: number): number {
  if (failureCount <= 1) return 0;
  return Math.min(2 ** (failureCount - 1), 16);
}

const inputClasses =
  "box-border w-full rounded-[10px] border border-[var(--ag-card-border)] bg-[var(--ag-input-bg)] px-[14px] py-[10px] text-[14px] text-[var(--ag-text)] outline-none focus:border-[var(--ag-purple)] disabled:opacity-60";

export default function LoginForm() {
  const router = useRouter();
  const { setSession } = useSession();

  const [mode, setMode] = useState<IdentifierMode>("username");
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [switchNotice, setSwitchNotice] = useState<string | null>(null);
  // Only the setter is used here -- consumed via the functional-update form
  // in registerFailure() below, so the count itself never needs to be read
  // in this component's render.
  const [, setFailureCount] = useState(0);
  const [cooldownSeconds, setCooldownSeconds] = useState(0);

  // Cosmetic cooldown countdown, ticking every second while active.
  useEffect(() => {
    if (cooldownSeconds <= 0) return;
    const timer = setInterval(() => {
      setCooldownSeconds((s) => Math.max(0, s - 1));
    }, 1000);
    return () => clearInterval(timer);
  }, [cooldownSeconds]);

  function toggleMode() {
    setMode((current) => (current === "username" ? "principal_id" : "username"));
    setIdentifier("");
    setSwitchNotice(null);
    setErrorMessage(null);
  }

  function registerFailure() {
    setFailureCount((count) => {
      const next = count + 1;
      setCooldownSeconds(cooldownSecondsForFailureCount(next));
      return next;
    });
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (loading || cooldownSeconds > 0) return;

    setErrorMessage(null);
    setSwitchNotice(null);

    const capturedIdentifier = identifier.trim();
    // Captured once, up front -- the PBKDF2 work below never re-reads the
    // controlled `password` input mid-computation.
    const capturedPassword = password;

    if (!capturedIdentifier || !capturedPassword) {
      setErrorMessage(
        mode === "username"
          ? "Enter your username and password."
          : "Enter your principal_id and password.",
      );
      return;
    }

    let principalId: string;
    if (mode === "username") {
      const mapped = lookupPrincipalId(capturedIdentifier);
      if (!mapped) {
        // Auto-switch rather than a bare error -- this device simply has no
        // record of that username, which is a normal "new device" case.
        setMode("principal_id");
        setIdentifier("");
        setSwitchNotice(
          `"${capturedIdentifier}" isn't recognized on this device -- enter your principal_id instead.`,
        );
        return;
      }
      principalId = mapped;
    } else {
      principalId = capturedIdentifier;
    }

    setLoading(true);
    try {
      let response: Response;
      try {
        response = await fetch(`/api/vault/keyring?principal_id=${encodeURIComponent(principalId)}`);
      } catch {
        setErrorMessage("Service unavailable. Please try again in a moment.");
        return;
      }

      if (response.status === 404) {
        setErrorMessage("No account found for that principal_id.");
        registerFailure();
        return;
      }
      if (!response.ok) {
        setErrorMessage("Service unavailable. Please try again in a moment.");
        return;
      }

      const blob = (await response.json()) as KeyringBlob;

      let privateKey: Uint8Array;
      try {
        const unlocked = await unlockKeyringBlob(capturedPassword, blob);
        privateKey = unlocked.privateKey;
      } catch (err) {
        // Unified message (KTD6): wrong password and a corrupted blob both
        // raise VaultAuthError and are cryptographically indistinguishable.
        setErrorMessage(
          err instanceof VaultAuthError
            ? "Incorrect password. Please try again."
            : "Something went wrong unlocking your account. Please try again.",
        );
        registerFailure();
        return;
      }

      const sessionKeypair = generateKeypair();
      const sessionPublicKeyB64 = b64encode(sessionKeypair.publicKey);
      const assertion = buildSessionAssertion(principalId, privateKey, sessionPublicKeyB64);
      try {
        await establishWebSession(assertion);
      } catch {
        setErrorMessage("Could not establish a secure session. Please try again.");
        return;
      }

      setSession({
        principalId,
        username: mode === "username" ? capturedIdentifier : null,
        sessionPublicKey: sessionPublicKeyB64,
        sessionPrivateKey: b64encode(sessionKeypair.privateKey),
        assertion,
      });
      setFailureCount(0);
      setCooldownSeconds(0);

      // Best-effort, non-blocking (KTD8): a failure here never blocks a
      // successful login. Deliberately not awaited.
      fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ principal_id: principalId }),
      }).catch(() => {
        // Registry existence-check/last_active bump only -- ignore failures.
      });

      router.push("/");
    } finally {
      setLoading(false);
    }
  }

  const identifierLabel = mode === "username" ? "Username" : "Principal ID";
  const identifierPlaceholder =
    mode === "username" ? "yourusername" : "Paste your principal_id (base64 public key)";
  const submitDisabled = loading || cooldownSeconds > 0;

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-[16px]" noValidate>
      <fieldset disabled={loading} className="flex flex-col gap-[16px] border-0 p-0 m-0 min-w-0">
        <div className="flex flex-col gap-[6px]">
          <label htmlFor="login-identifier" className="text-[12px] font-medium text-[var(--ag-text-secondary)]">
            {identifierLabel}
          </label>
          <input
            id="login-identifier"
            name="identifier"
            type="text"
            autoComplete={mode === "username" ? "username" : "off"}
            placeholder={identifierPlaceholder}
            value={identifier}
            onChange={(e) => setIdentifier(e.target.value)}
            className={inputClasses}
          />
          {switchNotice && (
            <p role="status" className="text-[12px] text-[var(--ag-orange)]">
              {switchNotice}
            </p>
          )}
          <button
            type="button"
            onClick={toggleMode}
            className="w-fit border-0 bg-transparent p-0 text-[12px] text-[var(--ag-purple-light)] underline cursor-pointer"
          >
            {mode === "username" ? "Use a different device" : "Use my username instead"}
          </button>
        </div>

        <div className="flex flex-col gap-[6px]">
          <label htmlFor="login-password" className="text-[12px] font-medium text-[var(--ag-text-secondary)]">
            Password
          </label>
          <input
            id="login-password"
            name="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className={inputClasses}
          />
        </div>

        {errorMessage && (
          <p role="alert" className="text-[13px] text-[var(--ag-red)]">
            {errorMessage}
          </p>
        )}

        <button
          type="submit"
          disabled={submitDisabled}
          className="w-full rounded-[10px] bg-[var(--ag-purple)] px-[14px] py-[10px] text-[14px] font-semibold text-white cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed"
        >
          {loading
            ? "Signing in..."
            : cooldownSeconds > 0
              ? `Try again in ${cooldownSeconds}s`
              : "Sign in"}
        </button>
      </fieldset>
    </form>
  );
}
