import { getConciergeUrl } from "@/lib/backendConfig";
type Ctx = { params: Promise<{ workflow_id: string }> };
export async function GET(request: Request, { params }: Ctx) {
  const { workflow_id } = await params; const headers = new Headers(); const cookie = request.headers.get("cookie"); if (cookie) headers.set("Cookie", cookie);
  try { const upstream = await fetch(`${getConciergeUrl()}/workflows/${encodeURIComponent(workflow_id)}`, { headers, cache: "no-store" }); return new Response(await upstream.arrayBuffer(), { status: upstream.status, headers: { "Content-Type": upstream.headers.get("content-type") ?? "application/json", "Cache-Control": "no-store" } }); }
  catch { return Response.json({ error: "Workflow service unavailable" }, { status: 502 }); }
}
