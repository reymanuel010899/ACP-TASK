import { getConciergeUrl } from "@/lib/backendConfig";
type Ctx = { params: Promise<{ workflow_id: string }> };
export async function POST(request: Request, { params }: Ctx) {
  const { workflow_id } = await params; const headers = new Headers({ "Content-Type": request.headers.get("content-type") ?? "application/json" });
  for (const name of ["cookie", "x-csrf-token"]) { const value = request.headers.get(name); if (value) headers.set(name, value); }
  try { const upstream = await fetch(`${getConciergeUrl()}/workflows/${encodeURIComponent(workflow_id)}/retry`, { method: "POST", headers, body: await request.arrayBuffer(), cache: "no-store" }); return new Response(await upstream.arrayBuffer(), { status: upstream.status, headers: { "Content-Type": upstream.headers.get("content-type") ?? "application/json", "Cache-Control": "no-store" } }); }
  catch { return Response.json({ error: "Workflow service unavailable" }, { status: 502 }); }
}
