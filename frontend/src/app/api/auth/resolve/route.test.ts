import { afterEach, describe, expect, it, vi } from "vitest";

import { GET } from "./route";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("GET /api/auth/resolve", () => {
  it("forwards an encoded username and the Registry response", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ principal_id: "principal-1" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await GET(
      new Request("http://bff.local/api/auth/resolve?username=maria%20test"),
    );

    expect(response.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8090/auth/resolve?username=maria%20test",
    );
  });

  it("rejects a missing username", async () => {
    const response = await GET(new Request("http://bff.local/api/auth/resolve"));
    expect(response.status).toBe(400);
  });
});
