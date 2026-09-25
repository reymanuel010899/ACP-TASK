import { getConciergeUrl } from "@/lib/backendConfig";

type Ctx = { params: Promise<{ conversation_id: string; effect_id: string }> };

export async function POST(request: Request, { params }: Ctx): Promise<Response> {
  const { conversation_id, effect_id } = await params;
  const headers = new Headers({
    "Content-Type": request.headers.get("content-type") ?? "application/json",
  });
  // The session cookie and CSRF token are the whole authorisation story here;
  // this route decides nothing on its own.
  for (const name of ["cookie", "x-csrf-token"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  try {
    const upstream = await fetch(
      `${getConciergeUrl()}/conversations/${encodeURIComponent(conversation_id)}` +
        `/effects/${encodeURIComponent(effect_id)}`,
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
    // A failed proxy hop says nothing about whether the effect ran, so it must
    // not read as a decision the server accepted.
    return Response.json(
      { state: "retryable_failure", recovery: { action: "retry" } },
      { status: 502 },
    );
  }
}
