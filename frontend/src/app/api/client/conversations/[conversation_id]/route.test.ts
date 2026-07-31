import { afterEach, expect, it, vi } from "vitest";
import { GET } from "./route";

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("awaits dynamic params and forwards only the session cookie", async () => {
  const fetchMock = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    expect(String(url)).toContain("/conversations/conversation%3A1");
    expect(new Headers(init?.headers).get("cookie")).toBe("tessera_session=s1");
    return Response.json({ state: "ready", conversationId: "conversation:1" });
  });
  vi.stubGlobal("fetch", fetchMock);
  const response = await GET(
    new Request("https://localhost/api/client/conversations/conversation%3A1", {
      headers: { Cookie: "tessera_session=s1" },
    }),
    { params: Promise.resolve({ conversation_id: "conversation:1" }) },
  );
  expect(response.status).toBe(200);
  expect(response.headers.get("cache-control")).toBe("no-store");
});
