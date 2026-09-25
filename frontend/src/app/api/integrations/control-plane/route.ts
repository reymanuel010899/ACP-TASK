import { getOAuthUrl } from "@/lib/backendConfig";

// The tenant is never a parameter here. It comes from the session cookie the
// OAuth service resolves, so there is no field a caller could set to reach
// another account's switches.

export async function GET(request: Request): Promise<Response> {
  const headers = new Headers();
  const cookie = request.headers.get("cookie");
  if (cookie) headers.set("Cookie", cookie);
  try {
    const upstream = await fetch(`${getOAuthUrl()}/oauth/control-plane`, {
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

export async function POST(request: Request): Promise<Response> {
  const headers = new Headers({
    "Content-Type": request.headers.get("content-type") ?? "application/json",
  });
  const cookie = request.headers.get("cookie");
  const csrf = request.headers.get("x-csrf-token");
  if (cookie) headers.set("Cookie", cookie);
  if (csrf) headers.set("X-CSRF-Token", csrf);
  try {
    const upstream = await fetch(`${getOAuthUrl()}/oauth/control-plane`, {
      method: "POST",
      headers,
      body: await request.arrayBuffer(),
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
