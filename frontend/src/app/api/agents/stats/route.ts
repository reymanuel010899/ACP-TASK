// GET /api/agents/stats -> runner fleet stats: total + status counts + a real
// per-day cumulative trend (from each agent's created_at) + growth %.

import { proxyRunner } from "@/lib/runnerProxy";

export async function GET(): Promise<Response> {
  return proxyRunner("/agents/stats");
}
