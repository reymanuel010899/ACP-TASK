import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { GET, POST } from "./route";

// A hardcoded, known-to-contain-a-literal-`/` standard-base64 string, so the
// "principal_id with a `/`" scenario is GUARANTEED rather than left to
// chance random generation (per the plan's explicit instruction). This is
// exactly the shape a real ed25519 public key takes when base64-encoded:
// 32 raw bytes -> 44 base64 chars, and roughly half of all such keys
// contain at least one `/`.
const PRINCIPAL_ID_WITH_SLASH = "ab/cdEFGH12345678ijklMNOPQRstuvWXYZ0+9==";

// ---------------------------------------------------------------------------
// Unit-level tests: mock/absent upstream, no real Vault needed.
// ---------------------------------------------------------------------------

describe("GET /api/vault/keyring -- unit (no real Vault)", () => {
  it("error path: missing 'principal_id' query parameter returns 400, never reaches the network", async () => {
    const request = new Request("http://bff.local/api/vault/keyring");
    const response = await GET(request);
    expect(response.status).toBe(400);
    const body = await response.json();
    expect(body.error).toMatch(/principal_id/);
  });

  it("error path: an unreachable Vault returns a distinct 502 {error} shape, not a crash", async () => {
    const originalVaultUrl = process.env.VAULT_URL;
    process.env.VAULT_URL = "http://127.0.0.1:1"; // reserved/unroutable port

    try {
      const request = new Request(
        "http://bff.local/api/vault/keyring?principal_id=" + encodeURIComponent("whoever"),
      );
      const response = await GET(request);
      expect(response.status).toBe(502);
      const body = await response.json();
      expect(typeof body.error).toBe("string");
      expect(body.error.length).toBeGreaterThan(0);
    } finally {
      if (originalVaultUrl === undefined) delete process.env.VAULT_URL;
      else process.env.VAULT_URL = originalVaultUrl;
    }
  });
});

describe("POST /api/vault/keyring -- unit (mocked upstream)", () => {
  it("error path: an unreachable Vault returns a distinct 502 {error} shape, not a crash", async () => {
    const originalVaultUrl = process.env.VAULT_URL;
    process.env.VAULT_URL = "http://127.0.0.1:1"; // reserved/unroutable port

    try {
      const request = new Request("http://bff.local/api/vault/keyring", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_principal_id: "whoever" }),
      });
      const response = await POST(request);
      expect(response.status).toBe(502);
      const body = await response.json();
      expect(typeof body.error).toBe("string");
      expect(body.error.length).toBeGreaterThan(0);
    } finally {
      if (originalVaultUrl === undefined) delete process.env.VAULT_URL;
      else process.env.VAULT_URL = originalVaultUrl;
    }
  });
});

// ---------------------------------------------------------------------------
// Integration tests against a real vault.app server.
// ---------------------------------------------------------------------------

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const REPO_ROOT = path.resolve(__dirname, "..", "..", "..", "..", "..", "..");
const PYTHON_BIN = path.join(REPO_ROOT, ".venv", "bin", "python");
const VAULT_SERVER_SCRIPT = path.join(
  REPO_ROOT,
  "frontend",
  "scripts",
  "cross-lang",
  "vault_test_server.py",
);

const PYTHON_AVAILABLE = existsSync(PYTHON_BIN);
if (!PYTHON_AVAILABLE) {
  console.warn(
    `[keyring/route.test.ts] Skipping real-Vault integration tests: no Python venv found at ${PYTHON_BIN}. ` +
      "Manual verification: run `python -m venv .venv && .venv/bin/pip install -r requirements.txt` " +
      "at the repo root, then re-run `npm run test` in frontend/.",
  );
}

async function startVault(): Promise<{
  process: ChildProcessWithoutNullStreams;
  baseUrl: string;
}> {
  const proc = spawn(PYTHON_BIN, [VAULT_SERVER_SCRIPT], { cwd: REPO_ROOT });
  const baseUrl = await new Promise<string>((resolve, reject) => {
    let buffered = "";
    const onData = (chunk: Buffer) => {
      buffered += chunk.toString("utf-8");
      const newlineIndex = buffered.indexOf("\n");
      if (newlineIndex === -1) return;
      const line = buffered.slice(0, newlineIndex);
      proc.stdout.off("data", onData);
      try {
        const parsed = JSON.parse(line) as { host: string; port: number };
        resolve(`http://${parsed.host}:${parsed.port}`);
      } catch (err) {
        reject(err);
      }
    };
    proc.stdout.on("data", onData);
    proc.once("error", reject);
    setTimeout(() => reject(new Error("vault_test_server.py did not start in time")), 10_000);
  });
  return { process: proc, baseUrl };
}

const SAMPLE_KEYRING_FIELDS = {
  encrypted_dek: "ZGVr", // "dek" base64 -- opaque bytes as far as this proxy is concerned
  salt: "c2FsdA==",
  nonce: "bm9uY2U=",
  kdf: "pbkdf2-sha256",
  kdf_params: { iterations: 1000 },
  encrypted_private_key: "cHJpdmtleQ==",
};

describe.skipIf(!PYTHON_AVAILABLE)("GET /api/vault/keyring -- integration against a live vault.app", () => {
  let serverProcess: ChildProcessWithoutNullStreams;
  let vaultBaseUrl: string;
  let originalVaultUrl: string | undefined;

  beforeAll(async () => {
    originalVaultUrl = process.env.VAULT_URL;
    const started = await startVault();
    serverProcess = started.process;
    vaultBaseUrl = started.baseUrl;
    process.env.VAULT_URL = vaultBaseUrl;
  }, 15_000);

  afterAll(() => {
    serverProcess?.kill("SIGTERM");
    if (originalVaultUrl === undefined) delete process.env.VAULT_URL;
    else process.env.VAULT_URL = originalVaultUrl;
  });

  it("happy path: an existing keyring is returned unchanged", async () => {
    const principalId = "integration-test-principal-" + Date.now();
    const storeResp = await fetch(`${vaultBaseUrl}/keyring`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_principal_id: principalId, ...SAMPLE_KEYRING_FIELDS }),
    });
    expect(storeResp.status).toBe(200);

    const request = new Request(
      "http://bff.local/api/vault/keyring?principal_id=" + encodeURIComponent(principalId),
    );
    const response = await GET(request);
    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body.user_principal_id).toBe(principalId);
    for (const [field, value] of Object.entries(SAMPLE_KEYRING_FIELDS)) {
      expect(body[field]).toEqual(value);
    }
  });

  it("edge case: a principal_id containing a literal '/' round-trips correctly (the common case)", async () => {
    // Sanity-check the fixture itself actually contains the character under
    // test, so this assertion can't silently pass on a fixture that
    // regressed to not containing a slash.
    expect(PRINCIPAL_ID_WITH_SLASH).toContain("/");

    const storeResp = await fetch(`${vaultBaseUrl}/keyring`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_principal_id: PRINCIPAL_ID_WITH_SLASH,
        ...SAMPLE_KEYRING_FIELDS,
      }),
    });
    expect(storeResp.status).toBe(200);

    const request = new Request(
      "http://bff.local/api/vault/keyring?principal_id=" +
        encodeURIComponent(PRINCIPAL_ID_WITH_SLASH),
    );
    const response = await GET(request);
    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body.user_principal_id).toBe(PRINCIPAL_ID_WITH_SLASH);
  });

  it("error path: an unknown principal_id returns the Vault's 404 passed through, not swallowed", async () => {
    const request = new Request(
      "http://bff.local/api/vault/keyring?principal_id=" +
        encodeURIComponent("no-such-keyring-" + Date.now()),
    );
    const response = await GET(request);
    expect(response.status).toBe(404);
    const body = await response.json();
    expect(body.error).toBe("keyring not found");
  });
});

describe.skipIf(!PYTHON_AVAILABLE)("POST /api/vault/keyring -- integration against a live vault.app", () => {
  let serverProcess: ChildProcessWithoutNullStreams;
  let vaultBaseUrl: string;
  let originalVaultUrl: string | undefined;

  beforeAll(async () => {
    originalVaultUrl = process.env.VAULT_URL;
    const started = await startVault();
    serverProcess = started.process;
    vaultBaseUrl = started.baseUrl;
    process.env.VAULT_URL = vaultBaseUrl;
  }, 15_000);

  afterAll(() => {
    serverProcess?.kill("SIGTERM");
    if (originalVaultUrl === undefined) delete process.env.VAULT_URL;
    else process.env.VAULT_URL = originalVaultUrl;
  });

  it("happy path: a new keyring is stored and the Vault's response forwarded unchanged", async () => {
    const principalId = "integration-test-post-principal-" + Date.now();
    const request = new Request("http://bff.local/api/vault/keyring", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_principal_id: principalId, ...SAMPLE_KEYRING_FIELDS }),
    });
    const response = await POST(request);
    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body.user_principal_id).toBe(principalId);
    expect(typeof body.created_at).toBe("string");

    // Confirm it actually landed in the Vault (not just a 200 from this
    // proxy's own logic): fetch it back via GET.
    const getRequest = new Request(
      "http://bff.local/api/vault/keyring?principal_id=" + encodeURIComponent(principalId),
    );
    const getResponse = await GET(getRequest);
    expect(getResponse.status).toBe(200);
  });

  it("error path: a missing required field returns the Vault's 422 passed through, not swallowed", async () => {
    const principalId = "integration-test-post-missing-field-" + Date.now();
    const incompleteFields: Record<string, unknown> = { ...SAMPLE_KEYRING_FIELDS };
    delete incompleteFields.encrypted_dek;
    const request = new Request("http://bff.local/api/vault/keyring", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_principal_id: principalId, ...incompleteFields }),
    });
    const response = await POST(request);
    expect(response.status).toBe(422);
    const body = await response.json();
    expect(body.error).toBe("missing 'encrypted_dek'");
  });
});
