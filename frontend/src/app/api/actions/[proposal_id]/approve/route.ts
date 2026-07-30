import { getActionBrokerUrl } from "@/lib/backendConfig";

type Ctx = { params: Promise<{ proposal_id: string }> };

export async function POST(request: Request, { params }: Ctx): Promise<Response> {
  const { proposal_id: proposalId } = await params;
  const headers = new Headers({
    "Content-Type": request.headers.get("content-type") ?? "application/json",
  });
  const cookie = request.headers.get("cookie");
  const csrf = request.headers.get("x-csrf-token");
  if (cookie) headers.set("Cookie", cookie);
  if (csrf) headers.set("X-CSRF-Token", csrf);

  try {
    const upstream = await fetch(
      `${getActionBrokerUrl()}/actions/${encodeURIComponent(proposalId)}/approve`,
      {
        method: "POST",
        headers,
        body: await request.arrayBuffer(),
        cache: "no-store",
      },
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
      { error: "Action broker unavailable" },
      { status: 502, headers: { "Cache-Control": "no-store" } },
    );
  }
}
