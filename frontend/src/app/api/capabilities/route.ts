// GET /api/capabilities -> the registry's enriched capability catalog:
// { capabilities: [{ capability_id, name, description, tags, agents:[...] }] }.
// Card-derived context persisted at registration time, so discovery shows what
// each capability DOES and who offers it. Server-side only (R4).

import { getRegistryUrl } from "@/lib/backendConfig";

export async function GET(): Promise<Response> {
  try {
    const upstream = await fetch(`${getRegistryUrl()}/capabilities`, { cache: "no-store" });
    const text = await upstream.text();
    return new Response(text, {
      status: upstream.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch (err) {
    return Response.json(
      { error: `Registry did not respond: ${err instanceof Error ? err.message : String(err)}` },
      { status: 502 },
    );
  }
}
