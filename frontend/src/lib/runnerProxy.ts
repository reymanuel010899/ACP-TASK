// Shared BFF proxy to the agent runner (`runner/app.py`). Server-side only;
// the browser never reaches the runner directly (R4/R7). Byte-forwards the
// runner's JSON response and status; synthesizes a 502 when the runner is
// unreachable — same shape as the registry/vault proxies.

import { getRunnerUrl } from "@/lib/backendConfig";

/** Forward the caller's ownership identity to the runner. The browser sends
 * its session principal as `X-Owner-Principal`; the runner enforces that only
 * an agent's owner may mutate it (403 otherwise). */
export function ownerHeaders(request: Request): Record<string, string> {
  const owner = request.headers.get("x-owner-principal");
  return owner ? { "X-Owner-Principal": owner } : {};
}

export async function proxyRunner(path: string, init?: RequestInit): Promise<Response> {
  let upstream: Response;
  try {
    upstream = await fetch(`${getRunnerUrl()}${path}`, { cache: "no-store", ...init });
  } catch (err) {
    return Response.json(
      { error: `Runner did not respond: ${err instanceof Error ? err.message : String(err)}` },
      { status: 502 },
    );
  }
  const body = await upstream.arrayBuffer();
  return new Response(body, {
    status: upstream.status,
    headers: { "Content-Type": upstream.headers.get("content-type") ?? "application/json" },
  });
}
