import { getOAuthUrl } from "@/lib/backendConfig";

async function proxy(request: Request, method: "GET" | "DELETE"): Promise<Response> {
  const headers = new Headers();
  const cookie = request.headers.get("cookie");
  const csrf = request.headers.get("x-csrf-token");
  if (cookie) headers.set("Cookie", cookie);
  if (csrf) headers.set("X-CSRF-Token", csrf);

  let upstream: Response;
  try {
    upstream = await fetch(`${getOAuthUrl()}/oauth/google`, {
      method,
      headers,
      cache: "no-store",
    });
  } catch {
    return Response.json(
      { error: "OAuth service unavailable" },
      { status: 502, headers: { "Cache-Control": "no-store" } },
    );
  }
  return new Response(await upstream.arrayBuffer(), {
    status: upstream.status,
    headers: {
      "Content-Type": upstream.headers.get("content-type") ?? "application/json",
      "Cache-Control": "no-store",
    },
  });
}

export function GET(request: Request): Promise<Response> {
  return proxy(request, "GET");
}

export function DELETE(request: Request): Promise<Response> {
  return proxy(request, "DELETE");
}
