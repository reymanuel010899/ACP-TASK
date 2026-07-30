// GET /api/agents  -> runner list. Without params: full legacy shape
// ({ agents: [...] }). With ?page=&page_size=&q=: SERVER-side search +
// pagination ({ agents, total, page, page_size, total_pages, stats }) — the
// query string is forwarded verbatim to the runner, which owns the paging.
// POST /api/agents -> runner create-definition (spec only; stopped)
// Repointed from the registry to the RUNNER (U4/KTD3): the console's list and
// status are runner-backed (lifecycle source of truth); the registry stays the
// discovery layer that running agents self-register into.

import { proxyRunner } from "@/lib/runnerProxy";

export async function GET(request: Request): Promise<Response> {
  const { search } = new URL(request.url);
  return proxyRunner(`/agents${search}`);
}

export async function POST(request: Request): Promise<Response> {
  const body = await request.text();
  return proxyRunner("/agents", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });
}
