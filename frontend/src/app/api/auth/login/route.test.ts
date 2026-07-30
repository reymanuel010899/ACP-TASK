import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { POST } from "./route";

// ---------------------------------------------------------------------------
// Unit-level tests: mock/absent upstream, no real backend needed. These
// cover the proxy's own logic (byte forwarding, status/body passthrough,
// the synthesized 502 on network failure). `backendConfig.ts`'s URLs are
// read lazily (per-call, not cached at module-import time), so mutating
// `process.env` right before the call is enough -- no module-cache-busting
// tricks needed.
// ---------------------------------------------------------------------------

describe("POST /api/auth/login -- unit (mocked upstream)", () => {
  it("error path: an unreachable Registry returns a distinct 502 {error} shape, not a crash", async () => {
    const originalRegistryUrl = process.env.REGISTRY_URL;
    // Port 1 is a reserved/unroutable port: connection is refused immediately
    // rather than a real service ever answering there.
    process.env.REGISTRY_URL = "http://127.0.0.1:1";

    try {
      const request = new Request("http://bff.local/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ principal_id: "whoever" }),
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
});

// ---------------------------------------------------------------------------
// Integration tests against a real registry.app server (same pattern as
// agentCrypto.test.ts's / agentSession.test.ts's cross-language suites):
// this is the "cleanest testable shape" available since Next.js's Route
// Handlers are plain exported functions over the Web Request/Response
// APIs -- no framework test harness is needed, just a real Registry to
// proxy to.
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
    `[login/route.test.ts] Skipping real-Registry integration tests: no Python venv found at ${PYTHON_BIN}. ` +
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

describe.skipIf(!PYTHON_AVAILABLE)("POST /api/auth/login -- integration against a live registry.app", () => {
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

  it("happy path: an existing principal logs in and gets the Registry's response forwarded unchanged", async () => {
    const principalId = "integration-test-principal-" + Date.now();
    const registerResp = await fetch(`${registryBaseUrl}/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ principal_id: principalId, username: "alice" }),
    });
    expect(registerResp.status).toBe(200);

    const request = new Request("http://bff.local/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ principal_id: principalId }),
    });
    const response = await POST(request);
    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body.status).toBe("ok");
    expect(body.principal_id).toBe(principalId);
    expect(body).toHaveProperty("reputation");
    expect(body).toHaveProperty("user");
  });

  it("error path: an unknown principal_id returns the Registry's 404 passed through, not swallowed", async () => {
    const request = new Request("http://bff.local/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ principal_id: "no-such-principal-" + Date.now() }),
    });
    const response = await POST(request);
    expect(response.status).toBe(404);
    const body = await response.json();
    expect(body.error).toBe("principal not found");
  });

  it("error path: a malformed body (missing principal_id) returns the Registry's 422 passed through", async () => {
    const request = new Request("http://bff.local/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    const response = await POST(request);
    expect(response.status).toBe(422);
    const body = await response.json();
    expect(typeof body.error).toBe("string");
  });
});
