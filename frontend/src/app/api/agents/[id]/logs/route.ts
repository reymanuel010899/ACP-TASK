// GET /api/agents/[id]/logs[?tail=N] -> runner: recent captured process logs
import { proxyRunner } from "@/lib/runnerProxy";

export async function GET(req: Request, { params }: { params: Promise<{ id: string }> }): Promise<Response> {
  const { id } = await params;
  const tail = new URL(req.url).searchParams.get("tail") ?? "200";
  return proxyRunner(`/agents/${encodeURIComponent(id)}/logs?tail=${encodeURIComponent(tail)}`);
}
