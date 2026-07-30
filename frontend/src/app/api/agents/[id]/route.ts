// GET /api/agents/[id]    -> one managed agent (def + runtime)
// DELETE /api/agents/[id] -> stop + remove the definition

import { ownerHeaders, proxyRunner } from "@/lib/runnerProxy";

type Ctx = { params: Promise<{ id: string }> };

export async function GET(_req: Request, { params }: Ctx): Promise<Response> {
  const { id } = await params;
  return proxyRunner(`/agents/${encodeURIComponent(id)}`);
}

export async function DELETE(req: Request, { params }: Ctx): Promise<Response> {
  const { id } = await params;
  return proxyRunner(`/agents/${encodeURIComponent(id)}`, {
    method: "DELETE",
    headers: ownerHeaders(req),
  });
}
