// POST /api/agents/connect -> runner: connect an externally hosted (BYO) agent
// by URL. The runner fetches the agent's published card server-side (no browser
// CORS), validates the trust extension, registers it into the registry so
// requesters discover it, and then only health-checks it — it never launches it.

import { proxyRunner } from "@/lib/runnerProxy";

export async function POST(request: Request): Promise<Response> {
  const body = await request.text();
  return proxyRunner("/agents/connect", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });
}
