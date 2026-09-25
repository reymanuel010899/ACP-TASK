// GET /api/auth/resolve?username=... -- resolve a persisted Registry username
// to the public principal_id required to retrieve and unlock its keyring.

import { getRegistryUrl } from "@/lib/backendConfig";

export async function GET(request: Request): Promise<Response> {
  const username = new URL(request.url).searchParams.get("username");
  if (!username) {
    return Response.json({ error: "username is required" }, { status: 400 });
  }

  let upstream: Response;
  try {
    upstream = await fetch(
      `${getRegistryUrl()}/auth/resolve?username=${encodeURIComponent(username)}`,
    );
  } catch (err) {
    return Response.json(
      { error: `Registry did not respond: ${err instanceof Error ? err.message : String(err)}` },
      { status: 502 },
    );
  }

  return new Response(await upstream.arrayBuffer(), {
    status: upstream.status,
    headers: {
      "Content-Type": upstream.headers.get("content-type") ?? "application/json",
    },
  });
}
