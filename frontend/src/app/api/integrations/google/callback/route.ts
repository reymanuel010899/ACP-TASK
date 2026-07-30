import { getOAuthUrl } from "@/lib/backendConfig";

type CallbackResult = {
  result?: string;
  return_to?: string;
};

function safeReturnTarget(value: unknown, requestUrl: URL): URL | null {
  if (typeof value !== "string" || !value.startsWith("/") || value.startsWith("//")) {
    return null;
  }
  const target = new URL(value, requestUrl.origin);
  return target.origin === requestUrl.origin ? target : null;
}

export async function GET(request: Request): Promise<Response> {
  const requestUrl = new URL(request.url);
  const callbackQuery = new URLSearchParams();
  for (const field of ["code", "state", "error"] as const) {
    const value = requestUrl.searchParams.get(field);
    if (value) callbackQuery.set(field, value);
  }

  const headers = new Headers();
  const cookie = request.headers.get("cookie");
  if (cookie) headers.set("Cookie", cookie);

  let upstream: Response;
  try {
    upstream = await fetch(
      `${getOAuthUrl()}/oauth/google/callback?${callbackQuery.toString()}`,
      { method: "GET", headers, cache: "no-store" },
    );
  } catch {
    return Response.json(
      { error: "OAuth service unavailable" },
      { status: 502, headers: { "Cache-Control": "no-store" } },
    );
  }

  const raw = await upstream.arrayBuffer();
  if (!upstream.ok) {
    const target = new URL("/integrations", requestUrl.origin);
    target.searchParams.set("google", "callback-failed");
    return new Response(null, {
      status: 303,
      headers: {
        Location: target.toString(),
        "Cache-Control": "no-store",
      },
    });
  }

  let result: CallbackResult;
  try {
    result = JSON.parse(new TextDecoder().decode(raw)) as CallbackResult;
  } catch {
    return Response.json(
      { error: "OAuth service returned an invalid result" },
      { status: 502, headers: { "Cache-Control": "no-store" } },
    );
  }
  const target = safeReturnTarget(result.return_to, requestUrl);
  if (!target || (result.result !== "connected" && result.result !== "denied")) {
    return Response.json(
      { error: "OAuth service returned an unsafe result" },
      { status: 502, headers: { "Cache-Control": "no-store" } },
    );
  }
  target.searchParams.set("google", result.result);
  return new Response(null, {
    status: 303,
    headers: {
      Location: target.toString(),
      "Cache-Control": "no-store",
    },
  });
}
