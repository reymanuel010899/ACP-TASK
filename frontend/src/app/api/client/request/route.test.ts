import { afterEach, expect, it, vi } from "vitest";

import { POST } from "./route";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("forwards the authenticated session cookie to the concierge", async () => {
  const upstreamFetch = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
    const headers = new Headers(init?.headers);
    expect(headers.get("cookie")).toBe("tessera_session=session-1");
    return Response.json({ status: "workflow_preview" });
  });
  vi.stubGlobal("fetch", upstreamFetch);

  const response = await POST(new Request("https://localhost:3000/api/client/request", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Cookie: "tessera_session=session-1",
    },
    body: JSON.stringify({ message: "Lista los canales públicos de Slack" }),
  }));

  expect(response.status).toBe(200);
  expect(upstreamFetch).toHaveBeenCalledOnce();
});
