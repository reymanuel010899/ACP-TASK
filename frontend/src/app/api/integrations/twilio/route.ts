import { getOAuthUrl } from "@/lib/backendConfig";

async function proxy(request: Request, method: "GET" | "POST") {
  const headers = new Headers();
  const cookie = request.headers.get("cookie");
  const csrf = request.headers.get("x-csrf-token");
  if (cookie) headers.set("Cookie", cookie);
  if (csrf) headers.set("X-CSRF-Token", csrf);
  let body: BodyInit | undefined;
  if (method === "POST") {
    headers.set("Content-Type", "application/json");
    const supplied = (await request.json()) as Record<string, unknown>;
    body = JSON.stringify({ ...supplied, provider: "twilio" });
  }
  try {
    const path = method === "GET" ? "/oauth/account?provider=twilio" : "/oauth/account/connect";
    const upstream = await fetch(`${getOAuthUrl()}${path}`, { method, headers, body, cache: "no-store" });
    return new Response(await upstream.arrayBuffer(), {
      status: upstream.status,
      headers: { "Content-Type": upstream.headers.get("content-type") ?? "application/json", "Cache-Control": "no-store" },
    });
  } catch {
    return Response.json({ error: "OAuth service unavailable" }, { status: 502 });
  }
}

export function GET(request: Request) { return proxy(request, "GET"); }
export function POST(request: Request) { return proxy(request, "POST"); }
