"use client";

/**
 * Registration form (frontend unit U7).
 *
 * Flow: username + password + confirm -> validate (format, match, strength)
 * -> generate keypair (`generateKeypair()`, agentCrypto.ts) -> derive+build
 * the wrapped keyring blob (`buildKeyringBlob`) -> persist resume-state to
 * `sessionStorage` (see {@link REGISTRATION_STORAGE_KEY} below) ->
 * `POST /api/auth/register {principal_id, username}` -> `POST
 * /api/vault/keyring {user_principal_id, ...blob fields}` -> clear
 * resume-state -> "save your principal_id" success screen, gated behind an
 * explicit acknowledgment (R6: losing it here is unrecoverable) -> on
 * acknowledgment: check/warn on a local username collision, then write the
 * `username -> principal_id` mapping -> mint an ephemeral session
 * (`buildSessionAssertion`, then `setSession` via `useSession()`) ->
 * best-effort `POST /api/auth/login` ping (mirrors LoginForm's KTD8 pattern)
 * -> navigate to the dashboard (`/`).
 *
 * ---------------------------------------------------------------------------
 * Resume-in-place recovery (R8, KTD5)
 * ---------------------------------------------------------------------------
 *
 * The generated keypair/blob is held in a ref across the two network steps
 * (Registry then Vault), but a ref alone cannot survive a closed tab -- the
 * JS heap is gone. So `{principalId, username, blob}` is ALSO persisted to
 * `sessionStorage` under {@link REGISTRATION_STORAGE_KEY} (deliberately a
 * DIFFERENT key from `SessionProvider.tsx`'s own `"agenttrust-session"` key
 * -- this is an in-progress *registration attempt*, not an established
 * session) for the duration of the in-flight registration only. This is
 * safe to persist: it is ciphertext (the keyring blob) plus a public key
 * (the principal_id), never the plaintext password or the plaintext private
 * key -- the private key only ever exists in this component's in-memory ref.
 * Cleared on success or explicit user abandonment ("Start over").
 *
 * On mount, if a persisted entry is found, the form does NOT silently start
 * over -- it offers to resume ("Finish setting up your account?"). Because
 * the plaintext private key does not survive a reload (by design -- it was
 * never persisted), resuming needs the password re-entered once, to locally
 * unlock the persisted blob (`unlockKeyringBlob`, no network call needed:
 * the blob is already right here) and recover the private key needed later
 * to mint the session. The Registry/Vault steps that follow need only the
 * blob, never the password.
 *
 * `principal_id` is client-generated (a fresh ed25519 keypair per attempt),
 * so a 409 from the Registry is, for all practical purposes, always this
 * client's own earlier attempt having already landed (KTD5) -- by the time
 * ANY register call happens in this flow, the resume-state for that exact
 * `principal_id` has already been written to `sessionStorage` (persist
 * happens before the POST, see above), so "did I already submit this
 * principal_id" is always true by construction here. A 409 is therefore
 * treated as success-continue straight to the Vault step, never as a
 * collision error -- the astronomically-unlikely true external collision
 * (two independently generated 32-byte keys colliding) is accepted as an
 * unresolved edge, exactly as the plan itself characterizes it. "Start
 * over" always mints a brand-new keypair rather than reusing the abandoned
 * one, which is what keeps this reasoning sound across an abandon-then-retry
 * sequence.
 *
 * A retry after a Vault-step failure (Registry already succeeded) re-uses
 * the SAME persisted keypair/blob and calls only the Vault endpoint again --
 * it never re-generates and never re-calls Registry once that step is known
 * to have succeeded.
 */

import { useEffect, useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import {
  VaultAuthError,
  b64encode,
  buildKeyringBlob,
  generateKeypair,
  unlockKeyringBlob,
  type KeyringBlob,
} from "@/lib/agentCrypto";
import { buildSessionAssertion, establishWebSession } from "@/lib/agentSession";
import { useSession } from "@/lib/SessionProvider";
import { AGENTTRUST_USERNAME_MAP_KEY, lookupPrincipalId } from "@/lib/usernameMap";

// ---------------------------------------------------------------------------
// Resume-state storage (sessionStorage) -- distinct key from
// SessionProvider.tsx's own "agenttrust-session".
// ---------------------------------------------------------------------------

/**
 * sessionStorage key for an in-flight registration's resume-state. Holds
 * `{principalId, username, blob}` -- ciphertext plus a public key, never a
 * secret -- for the duration of the registration attempt only. Cleared on
 * success or explicit abandonment ("Start over").
 */
export const REGISTRATION_STORAGE_KEY = "agenttrust-registration-in-progress";

interface InProgressRegistration {
  principalId: string;
  username: string;
  blob: KeyringBlob;
}

function isInProgressRegistrationShape(value: unknown): value is InProgressRegistration {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.principalId === "string" &&
    candidate.principalId.length > 0 &&
    typeof candidate.username === "string" &&
    candidate.username.length > 0 &&
    typeof candidate.blob === "object" &&
    candidate.blob !== null
  );
}

function readInProgressRegistration(): InProgressRegistration | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(REGISTRATION_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as unknown;
    return isInProgressRegistrationShape(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function persistInProgressRegistration(entry: InProgressRegistration) {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(REGISTRATION_STORAGE_KEY, JSON.stringify(entry));
  } catch {
    // sessionStorage unavailable -- the in-memory ref still carries this
    // page's own flow; a closed tab just won't be resumable this time.
  }
}

function clearInProgressRegistration() {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(REGISTRATION_STORAGE_KEY);
  } catch {
    // Nothing to do -- already effectively gone if storage is unavailable.
  }
}

// ---------------------------------------------------------------------------
// Username -> principal_id mapping (write side; usernameMap.ts owns the
// key/shape and the read side, U4). Writes here reuse that EXACT key/shape
// -- flat `{[username]: principalId}` JSON at AGENTTRUST_USERNAME_MAP_KEY --
// so LoginForm's read side keeps working unchanged.
// ---------------------------------------------------------------------------

function saveUsernameMapping(username: string, principalId: string) {
  if (typeof window === "undefined") return;
  try {
    const raw = window.localStorage.getItem(AGENTTRUST_USERNAME_MAP_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : {};
    const map: Record<string, string> =
      typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)
        ? { ...(parsed as Record<string, string>) }
        : {};
    map[username] = principalId;
    window.localStorage.setItem(AGENTTRUST_USERNAME_MAP_KEY, JSON.stringify(map));
  } catch {
    // localStorage unavailable -- the account still exists server-side and
    // the session about to be minted still works this tab; only the
    // "log in with just a username on this device next time" convenience is
    // lost.
  }
}

// ---------------------------------------------------------------------------
// Client-side-only validation (KTD7: never transmitted)
// ---------------------------------------------------------------------------

const USERNAME_PATTERN = /^[A-Za-z0-9_-]{3,32}$/;
const PASSWORD_MIN_LENGTH = 10;

/** 3-32 chars, alphanumeric plus `_`/`-` -- checked before any PBKDF2 work starts (no server-side uniqueness check to wait for; username is a local display label, not a login identifier, KTD1). */
function usernameFormatError(username: string): string | null {
  if (!USERNAME_PATTERN.test(username)) {
    return "Username must be 3-32 characters: letters, numbers, underscores, or hyphens only.";
  }
  return null;
}

/**
 * Minimum-strength check (KTD7): the Vault's `GET /keyring/{id}` has no
 * auth or rate limit, so password strength is the real defense against an
 * offline brute-force of a fetched blob, not just UX polish. Requires a
 * minimum length plus a mix of letters and digits -- intentionally simple
 * (not a full entropy estimator), but enough to block trivially weak
 * passwords before any crypto work starts.
 */
function passwordStrengthError(password: string): string | null {
  if (password.length < PASSWORD_MIN_LENGTH) {
    return `Password must be at least ${PASSWORD_MIN_LENGTH} characters.`;
  }
  if (!/[A-Za-z]/.test(password) || !/[0-9]/.test(password)) {
    return "Password must include both letters and numbers.";
  }
  return null;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

type Stage =
  | "form"
  | "resume-prompt"
  | "submitting"
  | "error-resume"
  | "success"
  | "username-collision";

const inputClasses =
  "box-border w-full rounded-[10px] border border-[var(--ag-card-border)] bg-[var(--ag-input-bg)] px-[14px] py-[10px] text-[14px] text-[var(--ag-text)] outline-none focus:border-[var(--ag-purple)] disabled:opacity-60";

const primaryButtonClasses =
  "w-full rounded-[10px] bg-[var(--ag-purple)] px-[14px] py-[10px] text-[14px] font-semibold text-white cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed";

const secondaryButtonClasses =
  "w-full rounded-[10px] border border-[var(--ag-card-border)] bg-transparent px-[14px] py-[10px] text-[14px] font-semibold text-[var(--ag-text)] cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed";

export default function RegisterForm() {
  const router = useRouter();
  const { setSession } = useSession();

  // Guards against a rapid double-click starting two submissions -- a ref
  // (synchronous, unlike state) checked at the very top of the handler,
  // before any async work or even the first `setState` call.
  const submittingRef = useRef(false);
  const finalizingRef = useRef(false);

  // Detecting an in-flight registration left behind by a closed tab/reload
  // must NOT happen in the `useState` lazy initializer: that initializer
  // runs during the server render too (where `sessionStorage` doesn't
  // exist), and would run again as the *first* client render during
  // hydration -- reading the real, possibly-populated `sessionStorage`
  // there produces a client tree that disagrees with the server-rendered
  // HTML (a hydration mismatch). Both renders must start identical
  // ("form"/null), so the read is deferred to an Effect (client-only,
  // post-hydration), accepting the one extra render pass this requires.
  const [resumeCandidate, setResumeCandidate] = useState<InProgressRegistration | null>(null);
  const [stage, setStage] = useState<Stage>("form");

  useEffect(() => {
    const candidate = readInProgressRegistration();
    if (candidate) {
      // This post-hydration storage read intentionally changes the initial
      // form into its recovery prompt; doing it during render would mismatch
      // the server HTML.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setResumeCandidate(candidate);
      setStage("resume-prompt");
    }
  }, []);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [resumePassword, setResumePassword] = useState("");
  const [principalId, setPrincipalId] = useState<string | null>(null);
  const [copyStatus, setCopyStatus] = useState<"idle" | "copied">("idle");
  const [collisionExistingId, setCollisionExistingId] = useState<string | null>(null);
  // Mirrors usernameRef.current for the one spot that needs to RENDER it
  // (the username-collision warning) -- refs must never be read during
  // render, only state may be.
  const [displayUsername, setDisplayUsername] = useState("");

  // In-memory-only state that must never be persisted: the private key, and
  // whether the Registry step is already known to have succeeded (so a
  // Vault-step retry never repeats it).
  const privateKeyRef = useRef<Uint8Array | null>(null);
  const usernameRef = useRef<string>("");
  const principalIdRef = useRef<string | null>(null);
  const blobRef = useRef<KeyringBlob | null>(null);
  const registrySucceededRef = useRef(false);

  function resetToFreshForm() {
    submittingRef.current = false;
    registrySucceededRef.current = false;
    privateKeyRef.current = null;
    principalIdRef.current = null;
    blobRef.current = null;
    usernameRef.current = "";
    setResumeCandidate(null);
    setResumePassword("");
    setErrorMessage(null);
    setPrincipalId(null);
    setDisplayUsername("");
    setStage("form");
  }

  function abandonResume() {
    clearInProgressRegistration();
    resetToFreshForm();
  }

  // ---------------------------------------------------------------------
  // Registry + Vault steps
  // ---------------------------------------------------------------------

  /** Returns "ok" (including a 409, per KTD5) or an error message string. */
  async function submitToRegistry(id: string, name: string): Promise<"ok" | string> {
    let response: Response;
    try {
      response = await fetch("/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ principal_id: id, username: name }),
      });
    } catch {
      return "Service unavailable. Please try again in a moment.";
    }

    if (response.ok) return "ok";
    if (response.status === 409) {
      // Per KTD5: by the time any register call happens in this flow, the
      // resume-state for this exact principal_id has already been persisted
      // (see runRegistration below) -- so this is this client's own earlier
      // attempt having already landed, not a genuine collision.
      return "ok";
    }

    const body = (await response.json().catch(() => null)) as { error?: string } | null;
    return body?.error || "Registration failed. Please try again.";
  }

  /** Returns "ok" or an error message string. */
  async function submitToVault(id: string, blob: KeyringBlob): Promise<"ok" | string> {
    let response: Response;
    try {
      response = await fetch("/api/vault/keyring", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_principal_id: id, ...blob }),
      });
    } catch {
      return "Service unavailable. Please try again in a moment.";
    }

    if (response.ok) return "ok";
    const body = (await response.json().catch(() => null)) as { error?: string } | null;
    return body?.error || "Could not finish setting up your vault. Please try again.";
  }

  /**
   * Orchestrates the Registry-then-Vault sequence for the currently tracked
   * principal_id/username/blob (in the refs). Safe to call repeatedly as a
   * retry: skips the Registry call entirely once `registrySucceededRef` is
   * true, so a Vault-only failure's retry re-attempts ONLY the Vault upload,
   * never regenerates and never re-submits to the Registry.
   */
  async function runRegistration() {
    const id = principalIdRef.current;
    const name = usernameRef.current;
    const blob = blobRef.current;
    if (!id || !name || !blob) return;

    setStage("submitting");
    setErrorMessage(null);

    if (!registrySucceededRef.current) {
      const registryResult = await submitToRegistry(id, name);
      if (registryResult !== "ok") {
        setErrorMessage(registryResult);
        setStage("error-resume");
        return;
      }
      registrySucceededRef.current = true;
    }

    const vaultResult = await submitToVault(id, blob);
    if (vaultResult !== "ok") {
      setErrorMessage(vaultResult);
      setStage("error-resume");
      return;
    }

    clearInProgressRegistration();
    setPrincipalId(id);
    setStage("success");
  }

  // ---------------------------------------------------------------------
  // Initial submit (fresh form)
  // ---------------------------------------------------------------------

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submittingRef.current) return;

    setErrorMessage(null);

    const trimmedUsername = username.trim();
    const capturedPassword = password;
    const capturedConfirm = confirmPassword;

    const usernameError = usernameFormatError(trimmedUsername);
    if (usernameError) {
      setErrorMessage(usernameError);
      return;
    }
    if (capturedPassword !== capturedConfirm) {
      setErrorMessage("Password and confirmation do not match.");
      return;
    }
    const strengthError = passwordStrengthError(capturedPassword);
    if (strengthError) {
      setErrorMessage(strengthError);
      return;
    }

    // Everything past this point is real work (crypto + network) -- lock
    // out a second submission synchronously, before any of it starts.
    submittingRef.current = true;
    setStage("submitting");

    try {
      const { privateKey, publicKey } = generateKeypair();
      const id = b64encode(publicKey);
      const { blob } = await buildKeyringBlob(capturedPassword, privateKey);

      privateKeyRef.current = privateKey;
      principalIdRef.current = id;
      usernameRef.current = trimmedUsername;
      setDisplayUsername(trimmedUsername);
      blobRef.current = blob;
      registrySucceededRef.current = false;

      // Persist BEFORE calling Registry (KTD5): this is what makes a closed
      // tab recoverable, and what makes a 409 on this exact principal_id
      // always resolvable as "my own attempt" once the register call fires.
      persistInProgressRegistration({ principalId: id, username: trimmedUsername, blob });

      await runRegistration();
    } catch (err) {
      setErrorMessage(
        err instanceof Error ? err.message : "Something went wrong. Please try again.",
      );
      setStage("form");
    } finally {
      // Reset regardless of outcome (success/error-resume/thrown) -- without
      // this, an error-resume outcome (which returns normally, not via
      // throw) would leave the guard stuck true forever and silently no-op
      // every future Retry click.
      submittingRef.current = false;
    }
  }

  // ---------------------------------------------------------------------
  // Retry (after an error) -- reuses the SAME persisted keypair/blob.
  // ---------------------------------------------------------------------

  async function handleRetry() {
    if (submittingRef.current) return;
    submittingRef.current = true;
    try {
      await runRegistration();
    } finally {
      submittingRef.current = false;
    }
  }

  // ---------------------------------------------------------------------
  // Resume (closed-tab case) -- unlock the persisted blob locally with a
  // re-entered password to recover the private key, then continue.
  // ---------------------------------------------------------------------

  async function handleResumeSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submittingRef.current || !resumeCandidate) return;

    const capturedPassword = resumePassword;
    setErrorMessage(null);
    submittingRef.current = true;
    setStage("submitting");

    try {
      const unlocked = await unlockKeyringBlob(capturedPassword, resumeCandidate.blob);
      privateKeyRef.current = unlocked.privateKey;
      principalIdRef.current = resumeCandidate.principalId;
      usernameRef.current = resumeCandidate.username;
      setDisplayUsername(resumeCandidate.username);
      blobRef.current = resumeCandidate.blob;
      // We cannot know from here alone whether the earlier attempt's
      // Registry call landed -- `runRegistration`'s 409-as-continue handling
      // (KTD5) makes re-submitting it safe either way.
      registrySucceededRef.current = false;

      await runRegistration();
    } catch (err) {
      setStage("resume-prompt");
      setErrorMessage(
        err instanceof VaultAuthError
          ? "Incorrect password. Please try again."
          : "Something went wrong resuming your registration. Please try again.",
      );
    } finally {
      submittingRef.current = false;
    }
  }

  // ---------------------------------------------------------------------
  // Success screen acknowledgment -> collision check -> mapping -> session
  // ---------------------------------------------------------------------

  async function finalizeRegistration(saveMapping: boolean) {
    if (finalizingRef.current) return;
    const id = principalIdRef.current;
    const name = usernameRef.current;
    const privateKey = privateKeyRef.current;
    if (!id || !name || !privateKey) return;
    finalizingRef.current = true;

    if (saveMapping) {
      saveUsernameMapping(name, id);
    }

    const sessionKeypair = generateKeypair();
    const sessionPublicKeyB64 = b64encode(sessionKeypair.publicKey);
    const assertion = buildSessionAssertion(id, privateKey, sessionPublicKeyB64);
    try {
      await establishWebSession(assertion);
    } catch {
      finalizingRef.current = false;
      setErrorMessage("Could not establish a secure session. Please try again.");
      return;
    }

    setSession({
      principalId: id,
      username: name,
      sessionPublicKey: sessionPublicKeyB64,
      sessionPrivateKey: b64encode(sessionKeypair.privateKey),
      assertion,
    });

    // Best-effort, non-blocking (mirrors LoginForm's KTD8 pattern).
    fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ principal_id: id }),
    }).catch(() => {
      // Registry existence-check/last_active bump only -- ignore failures.
    });

    router.push("/");
  }

  function handleAcknowledge() {
    const id = principalIdRef.current;
    const name = usernameRef.current;
    if (!id || !name) return;

    // Before writing the mapping, check for an existing, DIFFERENT mapping
    // under this username on this device -- warn rather than silently
    // stranding that old identity's local mapping (e.g. a user who lost a
    // password re-registering under the same remembered username).
    const existing = lookupPrincipalId(name);
    if (existing && existing !== id) {
      setCollisionExistingId(existing);
      setStage("username-collision");
      return;
    }

    void finalizeRegistration(true);
  }

  function handleCollisionOverwrite() {
    void finalizeRegistration(true);
  }

  function handleCollisionSkip() {
    void finalizeRegistration(false);
  }

  async function handleCopyPrincipalId() {
    if (!principalId) return;
    try {
      await navigator.clipboard.writeText(principalId);
      setCopyStatus("copied");
      setTimeout(() => setCopyStatus("idle"), 2000);
    } catch {
      // Clipboard API unavailable/denied -- the id is still selectable text
      // on screen, so this is a soft failure, not blocking.
    }
  }

  // ---------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------

  if (stage === "success" || stage === "username-collision") {
    return (
      <div className="flex flex-col gap-[16px]">
        <div className="flex flex-col gap-[6px]">
          <p className="text-[13px] text-[var(--ag-text-secondary)]">Your principal_id</p>
          <div className="flex items-center gap-[8px] rounded-[10px] border border-[var(--ag-card-border)] bg-[var(--ag-input-bg)] px-[12px] py-[10px]">
            <code className="flex-1 break-all text-[13px] text-[var(--ag-text)]">
              {principalId}
            </code>
            <button
              type="button"
              onClick={handleCopyPrincipalId}
              className="shrink-0 cursor-pointer rounded-[8px] border border-[var(--ag-card-border)] bg-transparent px-[10px] py-[6px] text-[12px] text-[var(--ag-text)]"
            >
              {copyStatus === "copied" ? "Copied" : "Copy"}
            </button>
          </div>
        </div>

        <div
          role="alert"
          className="rounded-[10px] border border-[var(--ag-red)] bg-[var(--ag-red)]/10 px-[12px] py-[10px] text-[13px] text-[var(--ag-text)]"
        >
          Save this principal_id somewhere safe now. There is no password-recovery
          mechanism: if you lose both your password and this id, your identity is
          gone permanently -- no one can recover it for you.
        </div>

        {stage === "username-collision" ? (
          <div className="flex flex-col gap-[10px]">
            <p role="alert" className="text-[13px] text-[var(--ag-orange)]">
              &quot;{displayUsername}&quot; is already linked to a different principal_id (
              {collisionExistingId}) on this device. Overwriting means logging in with
              that username on this device will use this NEW identity instead --
              you&apos;d need the old principal_id to reach the old one again.
            </p>
            <button
              type="button"
              onClick={handleCollisionOverwrite}
              className={primaryButtonClasses}
            >
              Overwrite and continue
            </button>
            <button
              type="button"
              onClick={handleCollisionSkip}
              className={secondaryButtonClasses}
            >
              Continue without saving
            </button>
          </div>
        ) : (
          <button type="button" onClick={handleAcknowledge} className={primaryButtonClasses}>
            I&apos;ve saved my ID -- continue
          </button>
        )}
      </div>
    );
  }

  if (stage === "resume-prompt" && resumeCandidate) {
    return (
      <form onSubmit={handleResumeSubmit} className="flex flex-col gap-[16px]" noValidate>
        <div
          role="status"
          className="rounded-[10px] border border-[var(--ag-card-border)] bg-[var(--ag-input-bg)] px-[12px] py-[10px] text-[13px] text-[var(--ag-text)]"
        >
          Finish setting up your account? We found an in-progress registration for
          &quot;{resumeCandidate.username}&quot; on this device.
        </div>

        <div className="flex flex-col gap-[6px]">
          <label
            htmlFor="resume-password"
            className="text-[12px] font-medium text-[var(--ag-text-secondary)]"
          >
            Password
          </label>
          <input
            id="resume-password"
            name="password"
            type="password"
            autoComplete="new-password"
            value={resumePassword}
            onChange={(e) => setResumePassword(e.target.value)}
            className={inputClasses}
          />
        </div>

        {errorMessage && (
          <p role="alert" className="text-[13px] text-[var(--ag-red)]">
            {errorMessage}
          </p>
        )}

        <button type="submit" className={primaryButtonClasses}>
          Finish setting up my account
        </button>
        <button type="button" onClick={abandonResume} className={secondaryButtonClasses}>
          Start over with a new identity
        </button>
      </form>
    );
  }

  if (stage === "error-resume") {
    return (
      <div className="flex flex-col gap-[16px]">
        {errorMessage && (
          <p role="alert" className="text-[13px] text-[var(--ag-red)]">
            {errorMessage}
          </p>
        )}
        <button type="button" onClick={handleRetry} className={primaryButtonClasses}>
          Retry
        </button>
        <button type="button" onClick={abandonResume} className={secondaryButtonClasses}>
          Start over with a new identity
        </button>
      </div>
    );
  }

  const submitting = stage === "submitting";

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-[16px]" noValidate>
      <fieldset disabled={submitting} className="flex flex-col gap-[16px] border-0 p-0 m-0 min-w-0">
        <div className="flex flex-col gap-[6px]">
          <label htmlFor="register-username" className="text-[12px] font-medium text-[var(--ag-text-secondary)]">
            Username
          </label>
          <input
            id="register-username"
            name="username"
            type="text"
            autoComplete="username"
            placeholder="yourusername"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className={inputClasses}
          />
        </div>

        <div className="flex flex-col gap-[6px]">
          <label htmlFor="register-password" className="text-[12px] font-medium text-[var(--ag-text-secondary)]">
            Password
          </label>
          <input
            id="register-password"
            name="password"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className={inputClasses}
          />
        </div>

        <div className="flex flex-col gap-[6px]">
          <label htmlFor="register-confirm-password" className="text-[12px] font-medium text-[var(--ag-text-secondary)]">
            Confirm password
          </label>
          <input
            id="register-confirm-password"
            name="confirmPassword"
            type="password"
            autoComplete="new-password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            className={inputClasses}
          />
        </div>

        {errorMessage && (
          <p role="alert" className="text-[13px] text-[var(--ag-red)]">
            {errorMessage}
          </p>
        )}

        <button type="submit" disabled={submitting} className={primaryButtonClasses}>
          {submitting ? "Creating your account..." : "Create account"}
        </button>
      </fieldset>
    </form>
  );
}
