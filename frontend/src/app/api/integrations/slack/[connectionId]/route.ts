import { getOAuthUrl } from "@/lib/backendConfig";

export async function DELETE(
  request: Request,
  { params }: { params: Promise<{ connectionId: string }> },
): Promise<Response> {
  const { connectionId } = await params;
  const headers = new Headers();
  const cookie = request.headers.get("cookie");
  const csrf = request.headers.get("x-csrf-token");
  if (cookie) headers.set("Cookie", cookie);
  if (csrf) headers.set("X-CSRF-Token", csrf);
  try {
    const upstream = await fetch(`${getOAuthUrl()}/oauth/slack/${encodeURIComponent(connectionId)}`, {
      method: "DELETE",
      headers,
      cache: "no-store",
    });
    return new Response(await upstream.arrayBuffer(), {
      status: upstream.status,
      headers: {
        "Content-Type": upstream.headers.get("content-type") ?? "application/json",
        "Cache-Control": "no-store",
      },
    });
  } catch {
    return Response.json({ error: "OAuth service unavailable" }, { status: 502, headers: { "Cache-Control": "no-store" } });
  }
}
