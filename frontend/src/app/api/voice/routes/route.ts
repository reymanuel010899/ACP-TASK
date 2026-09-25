import { getOAuthUrl } from "@/lib/backendConfig";

async function proxy(request: Request, method: "GET" | "POST") {
  const headers = new Headers();
  const cookie = request.headers.get("cookie");
  const csrf = request.headers.get("x-csrf-token");
  if (cookie) headers.set("Cookie", cookie);
  if (csrf) headers.set("X-CSRF-Token", csrf);
  if (method === "POST") headers.set("Content-Type", "application/json");
  try {
    const upstream = await fetch(`${getOAuthUrl()}/oauth/voice/routes`, {
      method, headers, body: method === "POST" ? await request.arrayBuffer() : undefined, cache: "no-store",
    });
    return new Response(await upstream.arrayBuffer(), { status: upstream.status,
      headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } });
  } catch {
    return Response.json({ error: "Voice configuration service unavailable" }, { status: 502 });
  }
}

export function GET(request: Request) { return proxy(request, "GET"); }
export function POST(request: Request) { return proxy(request, "POST"); }
