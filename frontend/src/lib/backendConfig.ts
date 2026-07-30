// Server-side-only base URLs for the backend services this Next.js app's
// BFF (backend-for-frontend) Route Handlers proxy to: the Registry
// (`registry/app.py`) and the Vault (`vault/app.py`).
//
// These are consumed exclusively from inside `src/app/api/**/route.ts`
// handlers, which run server-side (Node.js runtime) and are never bundled
// for the browser. That's why this reads plain `process.env.REGISTRY_URL`
// / `process.env.VAULT_URL` rather than `NEXT_PUBLIC_*`: the
// `NEXT_PUBLIC_` prefix exists specifically to inline a value into the
// client JS bundle at build time (see
// `node_modules/next/dist/docs/01-app/02-guides/environment-variables.md`),
// which is neither necessary nor desirable here -- the browser must never
// know or reach these URLs directly (R4).
//
// Mirrors the env-var-driven base URL convention already established in
// `apps/marketplace/src/hooks/useUserSession.ts` (`VITE_REGISTRY_URL`,
// a Vite project's `import.meta.env` mechanism), adapted to Next.js's own
// server-side `process.env` mechanism.
//
// Defaults match each service's own `--port` default so a bare local dev
// setup (`python -m registry.app`, `python -m vault.app`) works with zero
// configuration: `registry/app.py`'s `--port` defaults to 8090,
// `vault/app.py`'s `--port` defaults to 8003.

// Read lazily (as functions, not module-scope constants computed once at
// import time) so each call reflects the current `process.env` -- in
// production these never change mid-process anyway, but this keeps the
// module import-order-independent and trivially testable (route handler
// tests can set `process.env.REGISTRY_URL`/`VAULT_URL` and see the change
// take effect without needing to defeat module caching).

function stripTrailingSlash(url: string): string {
  return url.endsWith("/") ? url.slice(0, -1) : url;
}

export function getRegistryUrl(): string {
  return stripTrailingSlash(process.env.REGISTRY_URL || "http://127.0.0.1:8090");
}

export function getVaultUrl(): string {
  return stripTrailingSlash(process.env.VAULT_URL || "http://127.0.0.1:8003");
}

// The agent runner (`runner/app.py`) — the control-plane backend the console's
// agent lifecycle (create/list/start/stop/restart/logs) proxies to. Server-side
// only, same rationale as above. Default matches `runner/app.py`'s `--port`.
export function getRunnerUrl(): string {
  return stripTrailingSlash(process.env.RUNNER_URL || "http://127.0.0.1:8110");
}

// The orchestrator (`web/app.py`) — the professional requester/client the floating
// client console delegates to. It runs `RequesterAgent.run_competitive()`:
// discovery, competitive negotiation across providers, and the independent
// verification gate. Server-side only. Default matches `web/app.py`'s `--port`.
export function getOrchestratorUrl(): string {
  return stripTrailingSlash(process.env.ORCHESTRATOR_URL || "http://127.0.0.1:8000");
}

// The LLM concierge (`web/concierge.py` wrapping `agents/orchestrator`) — the
// intelligent front door the floating client console talks to. It converses,
// discovers agents, negotiates, gates spend, and executes. Server-side only.
// Default matches `web/concierge.py`'s `--port`.
export function getConciergeUrl(): string {
  return stripTrailingSlash(process.env.CONCIERGE_URL || "http://127.0.0.1:8130");
}

// First-party opaque browser sessions used by OAuth and approval callbacks.
export function getSessionUrl(): string {
  return stripTrailingSlash(process.env.SESSION_URL || "http://127.0.0.1:8120");
}

// Session-bound OAuth transaction service. Provider authorization codes and
// managed credentials stay behind this BFF boundary.
export function getOAuthUrl(): string {
  return stripTrailingSlash(process.env.OAUTH_URL || "http://127.0.0.1:8121");
}

export function getActionBrokerUrl(): string {
  return stripTrailingSlash(process.env.ACTION_BROKER_URL || "http://127.0.0.1:8122");
}
