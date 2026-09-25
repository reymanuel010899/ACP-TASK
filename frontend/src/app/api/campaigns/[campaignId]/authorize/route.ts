import { getConciergeUrl } from "@/lib/backendConfig";

export async function POST(request: Request, context: { params: Promise<{ campaignId: string }> }): Promise<Response> {
  const { campaignId } = await context.params;
  const headers = new Headers({ "Content-Type": "application/json" });
  for (const name of ["cookie", "x-csrf-token"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  try {
    const upstream = await fetch(`${getConciergeUrl()}/campaigns/${encodeURIComponent(campaignId)}/authorize`, {
      method: "POST", headers, body: await request.arrayBuffer(), cache: "no-store",
    });
    return new Response(await upstream.arrayBuffer(), {
      status: upstream.status,
      headers: { "Content-Type": upstream.headers.get("content-type") ?? "application/json", "Cache-Control": "no-store" },
    });
  } catch {
    return Response.json({ error: "Campaign service unavailable" }, { status: 502 });
  }
}
