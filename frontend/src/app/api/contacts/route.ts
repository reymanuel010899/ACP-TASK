import { getConciergeUrl } from "@/lib/backendConfig";

export async function GET(request: Request): Promise<Response> {
  const branchId = new URL(request.url).searchParams.get("branchId");
  if (!branchId) {
    return Response.json({ error: "branchId is required" }, { status: 422 });
  }
  const headers = new Headers();
  const cookie = request.headers.get("cookie");
  if (cookie) headers.set("Cookie", cookie);
  try {
    const upstream = await fetch(
      `${getConciergeUrl()}/contacts?branchId=${encodeURIComponent(branchId)}`,
      { headers, cache: "no-store" },
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

export async function POST(request: Request): Promise<Response> {
  const headers = new Headers({ "Content-Type": "application/json" });
  for (const name of ["cookie", "x-csrf-token"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  try {
    const upstream = await fetch(`${getConciergeUrl()}/contacts`, {
      method: "POST",
      headers,
      body: await request.arrayBuffer(),
      cache: "no-store",
    });
    return new Response(await upstream.arrayBuffer(), {
      status: upstream.status,
      headers: { "Content-Type": upstream.headers.get("content-type") ?? "application/json" },
    });
  } catch {
    return Response.json({ error: "Directory service unavailable" }, { status: 502 });
  }
}
