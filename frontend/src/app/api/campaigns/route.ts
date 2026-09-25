import { getConciergeUrl } from "@/lib/backendConfig";

export async function GET(request: Request): Promise<Response> {
  const headers = new Headers();
  const cookie = request.headers.get("cookie");
  if (cookie) headers.set("Cookie", cookie);
  try {
    const upstream = await fetch(`${getConciergeUrl()}/campaigns`, {
      headers, cache: "no-store",
    });
    return new Response(await upstream.arrayBuffer(), {
      status: upstream.status,
      headers: { "Content-Type": upstream.headers.get("content-type") ?? "application/json", "Cache-Control": "no-store" },
    });
  } catch {
    return Response.json({ error: "Campaign service unavailable" }, { status: 502 });
  }
}
