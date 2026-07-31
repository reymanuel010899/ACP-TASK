import { getConciergeUrl } from "@/lib/backendConfig";

type Ctx = { params: Promise<{ conversation_id: string }> };

export async function POST(request: Request, { params }: Ctx): Promise<Response> {
  const { conversation_id } = await params;
  const headers = new Headers({
    "Content-Type": request.headers.get("content-type") ?? "application/json",
  });
  for (const name of ["cookie", "x-csrf-token"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  try {
    const upstream = await fetch(
      `${getConciergeUrl()}/conversations/${encodeURIComponent(conversation_id)}/close`,
      { method: "POST", headers, body: await request.arrayBuffer(), cache: "no-store" },
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
