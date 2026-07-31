import { afterEach, expect, it, vi } from "vitest";
import { POST } from "./route";

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("forwards cookie and CSRF when explicitly closing a conversation", async () => {
  vi.stubGlobal("fetch", vi.fn(async (_url, init?: RequestInit) => {
    const headers = new Headers(init?.headers);
    expect(headers.get("cookie")).toBe("tessera_session=s1");
    expect(headers.get("x-csrf-token")).toBe("csrf-1");
    return Response.json({ state: "expired", closed: true });
  }));
  const response = await POST(
    new Request("https://localhost/api/client/conversations/conversation%3A1/close", {
      method: "POST", headers: {
        Cookie: "tessera_session=s1", "X-CSRF-Token": "csrf-1",
      }, body: "{}",
    }),
    { params: Promise.resolve({ conversation_id: "conversation:1" }) },
  );
  expect(response.status).toBe(200);
});
