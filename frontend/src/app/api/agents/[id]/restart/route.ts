// POST /api/agents/[id]/restart -> runner: stop then start (same keys-dir)
import { ownerHeaders, proxyRunner } from "@/lib/runnerProxy";

export async function POST(req: Request, { params }: { params: Promise<{ id: string }> }): Promise<Response> {
  const { id } = await params;
  return proxyRunner(`/agents/${encodeURIComponent(id)}/restart`, { method: "POST", headers: ownerHeaders(req) });
}
