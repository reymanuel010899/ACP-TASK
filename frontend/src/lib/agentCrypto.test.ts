import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { spawn, spawnSync, type ChildProcessWithoutNullStreams } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  DEFAULT_ITERATIONS,
  VaultAuthError,
  b64decode,
  b64encode,
  buildKeyringBlob,
  decryptData,
  encryptData,
  generateDek,
  generateKeypair,
  generateSalt,
  deriveKek,
  pbkdf2DeriveBits,
  terminatePbkdf2Worker,
  unlockKeyringBlob,
  type KeyringBlob,
} from "./agentCrypto";

// Fast iteration count for correctness tests -- mirrors TEST_ITERATIONS in
// tests/vault/test_credential_storage.py. The real 600,000-iteration count
// is exercised separately, in the responsiveness test below.
const TEST_ITERATIONS = 1000;

function bytesEqual(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return false;
  return true;
}

// ---------------------------------------------------------------------------
// Happy path / error path / envelope-shape tests
// ---------------------------------------------------------------------------

describe("buildKeyringBlob / unlockKeyringBlob", () => {
  it("happy path: unlockKeyringBlob returns the original private key and DEK", async () => {
    const { privateKey } = generateKeypair();
    const { blob, dek } = await buildKeyringBlob(
      "correct horse battery staple",
      privateKey,
      TEST_ITERATIONS,
    );

    const unlocked = await unlockKeyringBlob("correct horse battery staple", blob);

    expect(bytesEqual(unlocked.dek, dek)).toBe(true);
    expect(bytesEqual(unlocked.privateKey, privateKey)).toBe(true);
  });

  it("blob shape mirrors vault/crypto.py::build_keyring_blob field-for-field", async () => {
    const { privateKey } = generateKeypair();
    const { blob } = await buildKeyringBlob("pw", privateKey, TEST_ITERATIONS);

    expect(Object.keys(blob).sort()).toEqual(
      [
        "encrypted_dek",
        "encrypted_private_key",
        "kdf",
        "kdf_params",
        "nonce",
        "salt",
      ].sort(),
    );
    expect(blob.kdf).toBe("pbkdf2-sha256");
    expect(blob.kdf_params).toEqual({ iterations: TEST_ITERATIONS });
    // All binary fields are standard (padded) base64 strings, decodable.
    for (const field of ["encrypted_dek", "salt", "nonce", "encrypted_private_key"] as const) {
      expect(() => b64decode(blob[field])).not.toThrow();
    }
  });

  it("error path: wrong password throws VaultAuthError, never returns partial data", async () => {
    const { privateKey } = generateKeypair();
    const { blob } = await buildKeyringBlob("right-password", privateKey, TEST_ITERATIONS);

    let thrown: unknown;
    try {
      await unlockKeyringBlob("wrong-password", blob);
    } catch (err) {
      thrown = err;
    }
    expect(thrown).toBeInstanceOf(VaultAuthError);
    // Distinct error type/name (KTD6's precondition: unified, unambiguous
    // "incorrect password" signal, distinguishable from other bugs).
    expect((thrown as Error).name).toBe("VaultAuthError");
  });

  it("error path: a tampered ciphertext also raises VaultAuthError (AEAD authentication)", async () => {
    const { privateKey } = generateKeypair();
    const { blob } = await buildKeyringBlob("pw", privateKey, TEST_ITERATIONS);
    const tampered: KeyringBlob = {
      ...blob,
      encrypted_private_key: b64encode(
        (() => {
          const bytes = b64decode(blob.encrypted_private_key);
          const copy = bytes.slice();
          copy[copy.length - 1] ^= 0xff; // flip a bit in the ciphertext/tag
          return copy;
        })(),
      ),
    };
    await expect(unlockKeyringBlob("pw", tampered)).rejects.toBeInstanceOf(VaultAuthError);
  });
});

// ---------------------------------------------------------------------------
// SecretBox nonce randomness
// ---------------------------------------------------------------------------

describe("secretbox nonce freshness", () => {
  it("two encryptions of the same plaintext under the same key produce different ciphertext/nonce", () => {
    const key = generateDek();
    const plaintext = new TextEncoder().encode("same plaintext, encrypted twice");

    const a = encryptData(plaintext, key);
    const b = encryptData(plaintext, key);

    expect(bytesEqual(a.nonce, b.nonce)).toBe(false);
    expect(bytesEqual(a.ciphertext, b.ciphertext)).toBe(false);

    // Both remain independently decryptable.
    expect(bytesEqual(decryptData(a.ciphertext, a.nonce, key), plaintext)).toBe(true);
    expect(bytesEqual(decryptData(b.ciphertext, b.nonce, key), plaintext)).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// PBKDF2 (600,000 iterations) does not block the event loop
// ---------------------------------------------------------------------------

describe("deriveKek responsiveness at the real 600,000-iteration count", () => {
  it("keeps a concurrent timer ticking throughout the derivation (event loop not blocked)", async () => {
    let ticks = 0;
    const timer = setInterval(() => {
      ticks++;
    }, 5);

    const salt = generateSalt();
    const start = Date.now();
    const kek = await deriveKek("a reasonably long master password", salt, DEFAULT_ITERATIONS);
    const elapsedMs = Date.now() - start;

    clearInterval(timer);

    expect(kek.length).toBe(32);
    // The derivation must take long enough for the assertion below to be
    // meaningful (otherwise "the timer ticked" proves nothing).
    expect(elapsedMs).toBeGreaterThan(15);
    // The timer kept firing *during* the derivation -- proof the JS event
    // loop was never blocked by the 600,000-iteration PBKDF2 call. In this
    // Node/Vitest environment there is no `Worker` global (see note below),
    // so this exercises the non-worker fallback path in deriveKek, which
    // calls the same WebCrypto `crypto.subtle.deriveBits` primitive the
    // real Web Worker (pbkdf2.worker.ts) also calls. WebCrypto's PBKDF2
    // implementation itself runs off the JS thread (Node's libuv
    // threadpool in this environment; a browser's own internal threading
    // in production), so responsiveness is preserved either way.
    expect(ticks).toBeGreaterThan(0);
  }, 20_000);
});

// ---------------------------------------------------------------------------
// Web Worker dispatch protocol (mocked Worker global -- see note below)
// ---------------------------------------------------------------------------

/**
 * jsdom/Node have no real, executable `Worker` implementation, so there is
 * no way to run pbkdf2.worker.ts inside a Vitest test as an actual OS
 * thread. What CAN be verified here, honestly, is that agentCrypto.ts's
 * dispatch code (message protocol, requestId matching, listener cleanup)
 * behaves correctly when a `Worker` global exists and speaks the expected
 * message shape -- i.e. the same protocol pbkdf2.worker.ts implements. This
 * mock worker computes the real PBKDF2 result (via the same
 * `pbkdf2DeriveBits` pbkdf2.worker.ts calls), so the resolved value is
 * checked for correctness too, not just that a message round-tripped.
 */
class MockPbkdf2Worker {
  private listeners: { message: Array<(e: { data: unknown }) => void>; error: Array<(e: unknown) => void> } = {
    message: [],
    error: [],
  };

  addEventListener(type: "message" | "error", cb: (e: never) => void): void {
    (this.listeners[type] as Array<(e: never) => void>).push(cb);
  }

  removeEventListener(type: "message" | "error", cb: (e: never) => void): void {
    this.listeners[type] = (this.listeners[type] as Array<(e: never) => void>).filter(
      (l) => l !== cb,
    ) as never;
  }

  postMessage(data: {
    requestId: number;
    password: Uint8Array;
    salt: Uint8Array;
    iterations: number;
    keyLengthBytes: number;
  }): void {
    pbkdf2DeriveBits(data.password, data.salt, data.iterations, data.keyLengthBytes)
      .then((result) => {
        for (const cb of this.listeners.message) {
          cb({ data: { requestId: data.requestId, ok: true, result } });
        }
      })
      .catch((err: unknown) => {
        for (const cb of this.listeners.message) {
          cb({ data: { requestId: data.requestId, ok: false, error: String(err) } });
        }
      });
  }

  terminate(): void {
    /* no-op */
  }
}

describe("PBKDF2 Worker dispatch protocol", () => {
  it("dispatches through the Worker message protocol and resolves with the correct KEK", async () => {
    const originalWorker = (globalThis as Record<string, unknown>).Worker;
    const originalWindow = (globalThis as Record<string, unknown>).window;
    (globalThis as Record<string, unknown>).window = {};
    (globalThis as Record<string, unknown>).Worker = MockPbkdf2Worker;

    try {
      const salt = generateSalt();
      const viaWorkerPath = await deriveKek("worker-dispatch-password", salt, TEST_ITERATIONS);
      const direct = await pbkdf2DeriveBits(
        new TextEncoder().encode("worker-dispatch-password"),
        salt,
        TEST_ITERATIONS,
        32,
      );
      expect(bytesEqual(viaWorkerPath, direct)).toBe(true);
    } finally {
      terminatePbkdf2Worker();
      if (originalWorker === undefined) delete (globalThis as Record<string, unknown>).Worker;
      else (globalThis as Record<string, unknown>).Worker = originalWorker;
      if (originalWindow === undefined) delete (globalThis as Record<string, unknown>).window;
      else (globalThis as Record<string, unknown>).window = originalWindow;
    }
  });
});

// ---------------------------------------------------------------------------
// Cross-language round trip against a live vault.app server
// ---------------------------------------------------------------------------

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const REPO_ROOT = path.resolve(__dirname, "..", "..", "..");
const PYTHON_BIN = path.join(REPO_ROOT, ".venv", "bin", "python");
const VAULT_SERVER_SCRIPT = path.join(REPO_ROOT, "frontend", "scripts", "cross-lang", "vault_test_server.py");
const BRIDGE_SCRIPT = path.join(REPO_ROOT, "frontend", "scripts", "cross-lang", "vault_crypto_bridge.py");

const CROSS_LANG_AVAILABLE = existsSync(PYTHON_BIN);
if (!CROSS_LANG_AVAILABLE) {
  console.warn(
    `[agentCrypto.test.ts] Skipping cross-language round trip: no Python venv found at ${PYTHON_BIN}. ` +
      "Manual verification: run `python -m venv .venv && .venv/bin/pip install -r requirements.txt` " +
      "at the repo root, then re-run `npm run test` in frontend/.",
  );
}

function runBridge(
  command: "build" | "unlock",
  payload: unknown,
): { stdout: string; status: number | null } {
  const result = spawnSync(PYTHON_BIN, [BRIDGE_SCRIPT, command], {
    input: JSON.stringify(payload),
    encoding: "utf-8",
    cwd: REPO_ROOT,
  });
  if (result.error) {
    throw result.error;
  }
  // stdout is a single clean JSON line; stderr may carry unrelated warnings
  // (e.g. urllib3's OpenSSL notice) that are not part of the contract here.
  return { stdout: result.stdout.trim(), status: result.status };
}

describe.skipIf(!CROSS_LANG_AVAILABLE)("cross-language round trip vs. a live vault.app server", () => {
  let serverProcess: ChildProcessWithoutNullStreams;
  let baseUrl: string;

  beforeAll(async () => {
    serverProcess = spawn(PYTHON_BIN, [VAULT_SERVER_SCRIPT], { cwd: REPO_ROOT });
    baseUrl = await new Promise<string>((resolve, reject) => {
      let buffered = "";
      const onData = (chunk: Buffer) => {
        buffered += chunk.toString("utf-8");
        const newlineIndex = buffered.indexOf("\n");
        if (newlineIndex === -1) return;
        const line = buffered.slice(0, newlineIndex);
        serverProcess.stdout.off("data", onData);
        try {
          const parsed = JSON.parse(line) as { host: string; port: number };
          resolve(`http://${parsed.host}:${parsed.port}`);
        } catch (err) {
          reject(err);
        }
      };
      serverProcess.stdout.on("data", onData);
      serverProcess.once("error", reject);
      setTimeout(() => reject(new Error("vault_test_server.py did not start in time")), 10_000);
    });
  }, 15_000);

  afterAll(() => {
    serverProcess?.kill("SIGTERM");
  });

  it("TS builds the keyring blob; libs/vault_client.py fetches and unlocks it", async () => {
    const password = "cross-lang-pw-1";
    const { privateKey } = generateKeypair();
    const principalId = "ed25519_ts_build_py_unlock";

    const { blob, dek } = await buildKeyringBlob(password, privateKey, TEST_ITERATIONS);

    const storeResp = await fetch(`${baseUrl}/keyring`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...blob, user_principal_id: principalId }),
    });
    expect(storeResp.status).toBe(200);

    const { stdout, status } = runBridge("unlock", {
      password,
      base_url: baseUrl,
      principal_id: principalId,
    });
    expect(status).toBe(0);
    const result = JSON.parse(stdout) as { dek_b64: string; private_key_b64: string };

    expect(result.dek_b64).toBe(b64encode(dek));
    expect(result.private_key_b64).toBe(b64encode(privateKey));
  });

  it("Python (vault/crypto.py) builds the keyring blob; TS fetches and unlocks it", async () => {
    const password = "cross-lang-pw-2";
    const { privateKey: originalPrivateKey } = generateKeypair();
    const principalId = "ed25519_py_build_ts_unlock";

    const { stdout, status } = runBridge("build", {
      password,
      private_key_b64: b64encode(originalPrivateKey),
      iterations: TEST_ITERATIONS,
    });
    expect(status).toBe(0);
    const built = JSON.parse(stdout) as { blob: KeyringBlob; dek_b64: string };

    const storeResp = await fetch(`${baseUrl}/keyring`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...built.blob, user_principal_id: principalId }),
    });
    expect(storeResp.status).toBe(200);

    const fetchResp = await fetch(`${baseUrl}/keyring/${principalId}`);
    expect(fetchResp.status).toBe(200);
    const fetchedBlob = (await fetchResp.json()) as KeyringBlob;

    const unlocked = await unlockKeyringBlob(password, fetchedBlob);

    expect(b64encode(unlocked.dek)).toBe(built.dek_b64);
    expect(b64encode(unlocked.privateKey)).toBe(b64encode(originalPrivateKey));
  });
});
