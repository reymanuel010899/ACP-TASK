// POST /api/agents/[id]/start -> runner: mint api-key, spawn provider, self-register
import { ownerHeaders, proxyRunner } from "@/lib/runnerProxy";

export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }): Promise<Response> {
  const { id } = await params;
  return proxyRunner(`/agents/${encodeURIComponent(id)}/start`, { method: "POST", headers: ownerHeaders(req) });
}
