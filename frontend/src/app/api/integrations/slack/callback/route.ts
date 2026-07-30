import { getOAuthUrl } from "@/lib/backendConfig";

type CallbackResult = { result?: string; return_to?: string };

function safeReturnTarget(value: unknown, requestUrl: URL): URL | null {
  if (typeof value !== "string" || !value.startsWith("/") || value.startsWith("//")) return null;
  const target = new URL(value, requestUrl.origin);
  return target.origin === requestUrl.origin ? target : null;
}

export async function GET(request: Request): Promise<Response> {
  const requestUrl = new URL(request.url);
  const query = new URLSearchParams();
  for (const field of ["code", "state", "error"] as const) {
    const value = requestUrl.searchParams.get(field);
    if (value) query.set(field, value);
  }
  const headers = new Headers();
  const cookie = request.headers.get("cookie");
  if (cookie) headers.set("Cookie", cookie);
  let upstream: Response;
  try {
    upstream = await fetch(`${getOAuthUrl()}/oauth/slack/callback?${query.toString()}`, {
      headers,
      cache: "no-store",
    });
  } catch {
    return Response.json({ error: "OAuth service unavailable" }, { status: 502, headers: { "Cache-Control": "no-store" } });
  }
  if (!upstream.ok) {
    const target = new URL("/integrations?slack=callback-failed", requestUrl.origin);
    return new Response(null, { status: 303, headers: { Location: target.toString(), "Cache-Control": "no-store" } });
  }
  let result: CallbackResult;
  try {
    result = (await upstream.json()) as CallbackResult;
  } catch {
    return Response.json({ error: "OAuth service returned an invalid result" }, { status: 502 });
  }
  const target = safeReturnTarget(result.return_to, requestUrl);
  if (!target || (result.result !== "connected" && result.result !== "denied")) {
    return Response.json({ error: "OAuth service returned an unsafe result" }, { status: 502 });
  }
  target.searchParams.set("slack", result.result);
  return new Response(null, { status: 303, headers: { Location: target.toString(), "Cache-Control": "no-store" } });
}
