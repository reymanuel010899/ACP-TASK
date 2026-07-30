import { getSessionUrl } from "@/lib/backendConfig";

const FORWARDED_HEADERS = ["content-type", "set-cookie"] as const;

async function proxy(request: Request, method: string): Promise<Response> {
  const cookie = request.headers.get("cookie");
  const csrf = request.headers.get("x-csrf-token");
  const headers = new Headers();
  if (cookie) headers.set("Cookie", cookie);
  if (csrf) headers.set("X-CSRF-Token", csrf);
  if (method === "POST") {
    headers.set("Content-Type", request.headers.get("content-type") ?? "application/json");
  }

  let upstream: Response;
  try {
    upstream = await fetch(
      `${getSessionUrl()}${method === "POST" ? "/sessions" : "/sessions/current"}`,
      {
        method,
        headers,
        body: method === "POST" ? await request.arrayBuffer() : undefined,
        cache: "no-store",
      },
    );
  } catch (error) {
    return Response.json(
      { error: `Session service did not respond: ${error instanceof Error ? error.message : String(error)}` },
      { status: 502 },
    );
  }

  const responseHeaders = new Headers({ "Cache-Control": "no-store" });
  for (const name of FORWARDED_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }
  return new Response(await upstream.arrayBuffer(), {
    status: upstream.status,
    headers: responseHeaders,
  });
}

export function POST(request: Request): Promise<Response> {
  return proxy(request, "POST");
}

export function GET(request: Request): Promise<Response> {
  return proxy(request, "GET");
}

export function DELETE(request: Request): Promise<Response> {
  return proxy(request, "DELETE");
}
