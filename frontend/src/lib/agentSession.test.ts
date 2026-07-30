import { describe, expect, it } from "vitest";
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { generateKeypair, publicKeyFromPrivate, b64encode } from "./agentCrypto";
import { buildSessionAssertion, DEFAULT_SESSION_TTL, SessionAssertionError } from "./agentSession";

// ---------------------------------------------------------------------------
// Shape / determinism tests (pure TS, no Python needed)
// ---------------------------------------------------------------------------

describe("buildSessionAssertion", () => {
  it("happy path: returns claims + signature mirroring libs/signing.py::build_session_assertion", () => {
    const principal = generateKeypair();
    const session = generateKeypair();
    const principalId = b64encode(principal.publicKey);
    const sessionPublicKeyB64 = b64encode(session.publicKey);
    const nowTs = 1_700_000_000;

    const assertion = buildSessionAssertion(
      principalId,
      principal.privateKey,
      sessionPublicKeyB64,
      DEFAULT_SESSION_TTL,
      nowTs,
    );

    expect(Object.keys(assertion).sort()).toEqual(
      ["expires_at", "issued_at", "principal_id", "session_public_key", "signature"].sort(),
    );
    expect(assertion.principal_id).toBe(principalId);
    expect(assertion.session_public_key).toBe(sessionPublicKeyB64);
    expect(assertion.issued_at).toBe(1_700_000_000);
    expect(typeof assertion.signature).toBe("string");
    expect(assertion.signature.length).toBeGreaterThan(0);
  });

  it("edge case: expires_at is issued_at + DEFAULT_SESSION_TTL (the backend's 15-minute session TTL)", () => {
    const principal = generateKeypair();
    const session = generateKeypair();
    const nowTs = 1_700_000_000;

    const assertion = buildSessionAssertion(
      b64encode(principal.publicKey),
      principal.privateKey,
      b64encode(session.publicKey),
      DEFAULT_SESSION_TTL,
      nowTs,
    );

    expect(assertion.expires_at - assertion.issued_at).toBe(DEFAULT_SESSION_TTL);
    // DEFAULT_SESSION_TTL itself is cross-checked against the live Python
    // constant (not hardcoded from memory) in the cross-language suite below.
  });

  it("issued_at/expires_at truncate a fractional now_ts to whole epoch seconds (Python's int() semantics)", () => {
    const principal = generateKeypair();
    const session = generateKeypair();

    const assertion = buildSessionAssertion(
      b64encode(principal.publicKey),
      principal.privateKey,
      b64encode(session.publicKey),
      DEFAULT_SESSION_TTL,
      1_700_000_000.999,
    );

    expect(assertion.issued_at).toBe(1_700_000_000);
    expect(Number.isInteger(assertion.issued_at)).toBe(true);
    expect(Number.isInteger(assertion.expires_at)).toBe(true);
  });

  it("is deterministic: identical inputs (including now_ts) sign identical bytes and produce identical output", () => {
    const principal = generateKeypair();
    const session = generateKeypair();
    const principalId = b64encode(principal.publicKey);
    const sessionPublicKeyB64 = b64encode(session.publicKey);

    const a = buildSessionAssertion(principalId, principal.privateKey, sessionPublicKeyB64, 900, 1_700_000_000);
    const b = buildSessionAssertion(principalId, principal.privateKey, sessionPublicKeyB64, 900, 1_700_000_000);

    expect(a).toEqual(b);
  });

  it("error path: empty principal_id throws SessionAssertionError", () => {
    const principal = generateKeypair();
    const session = generateKeypair();
    expect(() =>
      buildSessionAssertion("", principal.privateKey, b64encode(session.publicKey)),
    ).toThrow(SessionAssertionError);
  });

  it("error path: empty session_public_key throws SessionAssertionError", () => {
    const principal = generateKeypair();
    expect(() =>
      buildSessionAssertion(b64encode(principal.publicKey), principal.privateKey, ""),
    ).toThrow(SessionAssertionError);
  });

  it("error path: a malformed (wrong-length) private key throws SessionAssertionError, not a raw crypto exception", () => {
    const session = generateKeypair();
    const badKey = new Uint8Array([1, 2, 3]); // not a valid 32-byte ed25519 seed
    let thrown: unknown;
    try {
      buildSessionAssertion("some-principal-id", badKey, b64encode(session.publicKey));
    } catch (err) {
      thrown = err;
    }
    expect(thrown).toBeInstanceOf(SessionAssertionError);
    expect((thrown as Error).name).toBe("SessionAssertionError");
  });
});

// ---------------------------------------------------------------------------
// Cross-language proof: a TS-minted assertion verifies against the real
// libs/signing.py::verify_session_assertion (not a hand-rolled TS
// re-implementation of what Python expects).
// ---------------------------------------------------------------------------

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const REPO_ROOT = path.resolve(__dirname, "..", "..", "..");
const PYTHON_BIN = path.join(REPO_ROOT, ".venv", "bin", "python");
const BRIDGE_SCRIPT = path.join(REPO_ROOT, "frontend", "scripts", "cross-lang", "signing_bridge.py");

const CROSS_LANG_AVAILABLE = existsSync(PYTHON_BIN);
if (!CROSS_LANG_AVAILABLE) {
  console.warn(
    `[agentSession.test.ts] Skipping cross-language round trip: no Python venv found at ${PYTHON_BIN}. ` +
      "Manual verification: run `python -m venv .venv && .venv/bin/pip install -r requirements.txt` " +
      "at the repo root, then re-run `npm run test` in frontend/.",
  );
}

function runBridge(command: "verify" | "constants", payload: unknown): { stdout: string; status: number | null } {
  const result = spawnSync(PYTHON_BIN, [BRIDGE_SCRIPT, command], {
    input: JSON.stringify(payload),
    encoding: "utf-8",
    cwd: REPO_ROOT,
  });
  if (result.error) {
    throw result.error;
  }
  return { stdout: result.stdout.trim(), status: result.status };
}

describe.skipIf(!CROSS_LANG_AVAILABLE)("cross-language round trip vs. libs/signing.py", () => {
  it("a TS-minted assertion verifies via libs.signing.verify_session_assertion", () => {
    const principal = generateKeypair();
    const session = generateKeypair();
    const principalId = b64encode(principal.publicKey);
    const sessionPublicKeyB64 = b64encode(session.publicKey);
    const nowTs = 1_700_000_000;

    const assertion = buildSessionAssertion(
      principalId,
      principal.privateKey,
      sessionPublicKeyB64,
      DEFAULT_SESSION_TTL,
      nowTs,
    );

    const { stdout, status } = runBridge("verify", {
      assertion,
      principal_public_key_b64: principalId,
      now_ts: nowTs + 1, // one second after issuance -- well inside the TTL window
    });

    expect(status).toBe(0);
    const result = JSON.parse(stdout) as { session_public_key?: string; error?: string };
    expect(result.error).toBeUndefined();
    expect(result.session_public_key).toBe(sessionPublicKeyB64);
  });

  it("libs.signing.verify_session_assertion rejects a TS-minted assertion once past expires_at", () => {
    const principal = generateKeypair();
    const session = generateKeypair();
    const principalId = b64encode(principal.publicKey);
    const sessionPublicKeyB64 = b64encode(session.publicKey);
    const nowTs = 1_700_000_000;

    const assertion = buildSessionAssertion(
      principalId,
      principal.privateKey,
      sessionPublicKeyB64,
      DEFAULT_SESSION_TTL,
      nowTs,
    );

    const { stdout, status } = runBridge("verify", {
      assertion,
      principal_public_key_b64: principalId,
      now_ts: nowTs + DEFAULT_SESSION_TTL + 1, // one second past expiry
    });

    expect(status).not.toBe(0);
    const result = JSON.parse(stdout) as { error?: string };
    expect(result.error).toMatch(/ExpiredError/);
  });

  it("libs.signing.verify_session_assertion rejects a tampered claim (signature no longer matches)", () => {
    const principal = generateKeypair();
    const session = generateKeypair();
    const principalId = b64encode(principal.publicKey);
    const sessionPublicKeyB64 = b64encode(session.publicKey);
    const nowTs = 1_700_000_000;

    const assertion = buildSessionAssertion(
      principalId,
      principal.privateKey,
      sessionPublicKeyB64,
      DEFAULT_SESSION_TTL,
      nowTs,
    );
    const tampered = { ...assertion, expires_at: assertion.expires_at + 3600 };

    const { stdout, status } = runBridge("verify", {
      assertion: tampered,
      principal_public_key_b64: principalId,
      now_ts: nowTs + 1,
    });

    expect(status).not.toBe(0);
    const result = JSON.parse(stdout) as { error?: string };
    expect(result.error).toMatch(/SignatureError/);
  });

  it("DEFAULT_SESSION_TTL matches the live libs/signing.py::DEFAULT_SESSION_TTL constant", () => {
    const { stdout, status } = runBridge("constants", {});
    expect(status).toBe(0);
    const result = JSON.parse(stdout) as { default_session_ttl: number };
    expect(DEFAULT_SESSION_TTL).toBe(result.default_session_ttl);
  });
});

describe("sanity: agentCrypto's keypair helpers agree with each other", () => {
  it("publicKeyFromPrivate derives the same public key generateKeypair returned", () => {
    const { privateKey, publicKey } = generateKeypair();
    expect(b64encode(publicKeyFromPrivate(privateKey))).toBe(b64encode(publicKey));
  });
});
