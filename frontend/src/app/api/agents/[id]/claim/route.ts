// POST /api/agents/[id]/claim -> take ownership of an unclaimed (legacy) agent.
// Forwards the caller's session principal; the runner sets it as the owner.

import { ownerHeaders, proxyRunner } from "@/lib/runnerProxy";

export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }): Promise<Response> {
  const { id } = await params;
  return proxyRunner(`/agents/${encodeURIComponent(id)}/claim`, {
    method: "POST",
    headers: ownerHeaders(req),
  });
}
