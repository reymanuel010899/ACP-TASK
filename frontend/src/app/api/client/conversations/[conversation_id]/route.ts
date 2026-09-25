import { getConciergeUrl } from "@/lib/backendConfig";

type Ctx = { params: Promise<{ conversation_id: string }> };

export async function GET(request: Request, { params }: Ctx): Promise<Response> {
  const { conversation_id } = await params;
  const headers = new Headers();
  const cookie = request.headers.get("cookie");
  if (cookie) headers.set("Cookie", cookie);
  try {
    const upstream = await fetch(
      `${getConciergeUrl()}/conversations/${encodeURIComponent(conversation_id)}`,
      { method: "GET", headers, cache: "no-store" },
    );
    return new Response(await upstream.arrayBuffer(), {
      status: upstream.status,
      headers: {
        "Content-Type": upstream.headers.get("content-type") ?? "application/json",
        "Cache-Control": "no-store",
      },
    });
  } catch {
    return Response.json(
      { state: "retryable_failure", recovery: { action: "retry" } },
      { status: 502 },
    );
  }
}
