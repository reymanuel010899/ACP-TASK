import { getConciergeUrl } from "@/lib/backendConfig";

export async function PATCH(
  request: Request,
  context: { params: Promise<{ contactId: string }> },
): Promise<Response> {
  const declaredLength = Number(request.headers.get("content-length") ?? 0);
  if (!Number.isFinite(declaredLength) || declaredLength < 0) {
    return Response.json({ error: "invalid Content-Length" }, { status: 400 });
  }
  if (declaredLength > 32 * 1024) {
    return Response.json({ error: "contact edit is too large" }, { status: 413 });
  }
  const { contactId } = await context.params;
  const headers = new Headers({ "Content-Type": "application/json" });
  for (const name of ["cookie", "x-csrf-token"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  try {
    const body = await request.arrayBuffer();
    if (body.byteLength > 32 * 1024) {
      return Response.json({ error: "contact edit is too large" }, { status: 413 });
    }
    const upstream = await fetch(
      `${getConciergeUrl()}/contacts/${encodeURIComponent(contactId)}`,
      {
        method: "PATCH",
        headers,
        body,
        cache: "no-store",
      },
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
      { error: "Directory service unavailable" },
      { status: 502, headers: { "Cache-Control": "no-store" } },
    );
  }
}
