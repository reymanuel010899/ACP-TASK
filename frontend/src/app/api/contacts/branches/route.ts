import { getConciergeUrl } from "@/lib/backendConfig";

function forwardedHeaders(request: Request): Headers {
  const headers = new Headers({
    "Content-Type": request.headers.get("content-type") ?? "application/json",
  });
  for (const name of ["cookie", "x-csrf-token"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  return headers;
}

async function proxy(request: Request, method: "GET" | "POST") {
  try {
    const upstream = await fetch(`${getConciergeUrl()}/contacts/branches`, {
      method,
      headers: forwardedHeaders(request),
      body: method === "POST" ? await request.arrayBuffer() : undefined,
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
    return Response.json(
      { error: "Directory service unavailable" },
      { status: 502, headers: { "Cache-Control": "no-store" } },
    );
  }
}

export function GET(request: Request) {
  return proxy(request, "GET");
}

export function POST(request: Request) {
  return proxy(request, "POST");
}
