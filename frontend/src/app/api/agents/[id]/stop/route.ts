// POST /api/agents/[id]/stop -> runner: terminate the agent process
import { ownerHeaders, proxyRunner } from "@/lib/runnerProxy";

export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }): Promise<Response> {
  const { id } = await params;
  return proxyRunner(`/agents/${encodeURIComponent(id)}/stop`, { method: "POST", headers: ownerHeaders(req) });
}
