// POST /api/client/request  -> the floating client console's message to the
// LLM concierge orchestrator (`web/concierge.py` wrapping `agents/orchestrator`).
//
// Thin proxy, server-side only (R4). The concierge does the intelligent work:
// it turns the natural-language message into intent (Claude when
// ANTHROPIC_API_KEY is set, else an offline rule brain), discovers candidate
// agents, negotiates terms, gates spend, executes over the signed rails, and
// replies. The browser never reaches the concierge directly.

import { getConciergeUrl } from "@/lib/backendConfig";

export async function POST(request: Request): Promise<Response> {
  const body = await request.text();
  const headers = new Headers({ "Content-Type": "application/json" });
  const cookie = request.headers.get("cookie");
  if (cookie) headers.set("Cookie", cookie);
  try {
    const upstream = await fetch(`${getConciergeUrl()}/concierge`, {
      method: "POST",
      cache: "no-store",
      headers,
      body,
    });
    const text = await upstream.text();
    return new Response(text, {
      status: upstream.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch (err) {
    return Response.json(
      { status: "failed", reply: `El concierge no respondió: ${err instanceof Error ? err.message : String(err)}` },
      { status: 502 },
    );
  }
}
