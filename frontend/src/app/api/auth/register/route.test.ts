import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { POST } from "./route";

// ---------------------------------------------------------------------------
// Unit-level tests: mock/absent upstream, no real Registry needed. These
// cover the proxy's own logic (public_key injection, 409 remapping, the
// synthesized 502 on network failure, malformed-JSON handling) -- same
// pattern as login/route.test.ts and keyring/route.test.ts.
// ---------------------------------------------------------------------------

describe("POST /api/auth/register -- unit (mocked upstream)", () => {
  it("error path: an unreachable Registry returns a distinct 502 {error} shape, not a crash", async () => {
    const originalRegistryUrl = process.env.REGISTRY_URL;
    process.env.REGISTRY_URL = "http://127.0.0.1:1"; // reserved/unroutable port

    try {
      const request = new Request("http://bff.local/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ principal_id: "whoever", username: "alice" }),
      });
      const response = await POST(request);
      expect(response.status).toBe(502);
      const body = await response.json();
      expect(typeof body.error).toBe("string");
      expect(body.error.length).toBeGreaterThan(0);
    } finally {
      if (originalRegistryUrl === undefined) delete process.env.REGISTRY_URL;
      else process.env.REGISTRY_URL = originalRegistryUrl;
    }
  });

  it("error path: a non-JSON body returns a 400 {error} shape, never reaches the network", async () => {
    const originalRegistryUrl = process.env.REGISTRY_URL;
    // Even pointed at an unroutable port, this must fail before any fetch.
    process.env.REGISTRY_URL = "http://127.0.0.1:1";

    try {
      const request = new Request("http://bff.local/api/auth/register", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{not valid json",
      });
      const response = await POST(request);
      expect(response.status).toBe(400);
      const body = await response.json();
      expect(typeof body.error).toBe("string");
    } finally {
      if (originalRegistryUrl === undefined) delete process.env.REGISTRY_URL;
      else process.env.REGISTRY_URL = originalRegistryUrl;
    }
  });
});

// ---------------------------------------------------------------------------
// Integration tests against a real registry.app server (same pattern as
// login/route.test.ts).
// ---------------------------------------------------------------------------

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const REPO_ROOT = path.resolve(__dirname, "..", "..", "..", "..", "..", "..");
const PYTHON_BIN = path.join(REPO_ROOT, ".venv", "bin", "python");
const REGISTRY_SERVER_SCRIPT = path.join(
  REPO_ROOT,
  "frontend",
  "scripts",
  "cross-lang",
  "registry_test_server.py",
);

const PYTHON_AVAILABLE = existsSync(PYTHON_BIN);
if (!PYTHON_AVAILABLE) {
  console.warn(
    `[register/route.test.ts] Skipping real-Registry integration tests: no Python venv found at ${PYTHON_BIN}. ` +
      "Manual verification: run `python -m venv .venv && .venv/bin/pip install -r requirements.txt` " +
      "at the repo root, then re-run `npm run test` in frontend/.",
  );
}

async function startRegistry(): Promise<{
  process: ChildProcessWithoutNullStreams;
  baseUrl: string;
}> {
  const proc = spawn(PYTHON_BIN, [REGISTRY_SERVER_SCRIPT], { cwd: REPO_ROOT });
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
    setTimeout(() => reject(new Error("registry_test_server.py did not start in time")), 10_000);
  });
  return { process: proc, baseUrl };
}

describe.skipIf(!PYTHON_AVAILABLE)("POST /api/auth/register -- integration against a live registry.app", () => {
  let serverProcess: ChildProcessWithoutNullStreams;
  let registryBaseUrl: string;
  let originalRegistryUrl: string | undefined;

  beforeAll(async () => {
    originalRegistryUrl = process.env.REGISTRY_URL;
    const started = await startRegistry();
    serverProcess = started.process;
    registryBaseUrl = started.baseUrl;
    process.env.REGISTRY_URL = registryBaseUrl;
  }, 15_000);

  afterAll(() => {
    serverProcess?.kill("SIGTERM");
    if (originalRegistryUrl === undefined) delete process.env.REGISTRY_URL;
    else process.env.REGISTRY_URL = originalRegistryUrl;
  });

  it("happy path: a fresh principal_id registers and gets the Registry's response forwarded, with public_key injected", async () => {
    const principalId = "integration-test-register-" + Date.now();
    const request = new Request("http://bff.local/api/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ principal_id: principalId, username: "alice" }),
    });
    const response = await POST(request);
    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body.status).toBe("registered");
    expect(body.principal_id).toBe(principalId);
    expect(body).toHaveProperty("reputation");
    expect(body).toHaveProperty("user");

    // Confirm public_key was actually injected and reached the Registry: the
    // Registry's own public-key-resolution endpoint should now resolve it to
    // the principal_id itself (per the MVP convention principal_id ==
    // public_key), proving the augmented body -- not the raw client body --
    // was what got forwarded.
    const pubKeyResp = await fetch(
      `${registryBaseUrl}/principals/${encodeURIComponent(principalId)}/public_key`,
    );
    expect(pubKeyResp.status).toBe(200);
    const pubKeyBody = await pubKeyResp.json();
    expect(pubKeyBody.public_key).toBe(principalId);
  });

  it("error path: a genuine principal_id collision returns a distinct, actionable 409 message (not the raw Registry string)", async () => {
    const principalId = "integration-test-register-dup-" + Date.now();
    const firstRequest = new Request("http://bff.local/api/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ principal_id: principalId, username: "alice" }),
    });
    const firstResponse = await POST(firstRequest);
    expect(firstResponse.status).toBe(200);

    const secondRequest = new Request("http://bff.local/api/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ principal_id: principalId, username: "alice-again" }),
    });
    const secondResponse = await POST(secondRequest);
    expect(secondResponse.status).toBe(409);
    const body = await secondResponse.json();
    expect(typeof body.error).toBe("string");
    // Distinct from the Registry's own raw "principal already registered".
    expect(body.error).not.toBe("principal already registered");
    expect(body.error).toMatch(/try registering again/i);
  });

  it("error path: a missing principal_id returns the Registry's 422 passed through", async () => {
    const request = new Request("http://bff.local/api/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: "alice-no-id" }),
    });
    const response = await POST(request);
    expect(response.status).toBe(422);
    const body = await response.json();
    expect(typeof body.error).toBe("string");
  });
});
