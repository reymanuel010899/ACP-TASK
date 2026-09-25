import { afterEach, expect, it, vi } from "vitest";
import { POST } from "./route";

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

function request(body: string) {
  return new Request(
    "https://localhost/api/client/conversations/conversation%3A1/effects/effect%3A1",
    {
      method: "POST",
      headers: { Cookie: "tessera_session=s1", "X-CSRF-Token": "csrf-1" },
      body,
    },
  );
}

const params = Promise.resolve({
  conversation_id: "conversation:1", effect_id: "effect:1",
});

it("forwards the decision with the session cookie and CSRF token", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url, init?: RequestInit) => {
    expect(String(url)).toMatch(
      /\/conversations\/conversation%3A1\/effects\/effect%3A1$/,
    );
    const headers = new Headers(init?.headers);
    expect(headers.get("cookie")).toBe("tessera_session=s1");
    expect(headers.get("x-csrf-token")).toBe("csrf-1");
    expect(new TextDecoder().decode(init?.body as ArrayBuffer)).toBe(
      '{"decision":"approve"}',
    );
    return Response.json({ state: "awaiting_approval" });
  }));
  const response = await POST(request('{"decision":"approve"}'), { params });
  expect(response.status).toBe(200);
});

it("passes an upstream refusal through instead of inventing a verdict", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(
    { error: "effect not permitted" }, { status: 403 },
  )));
  const response = await POST(request('{"decision":"approve"}'), { params });
  expect(response.status).toBe(403);
  expect(await response.json()).toEqual({ error: "effect not permitted" });
});

it("reports a failed hop as retryable, never as a decision that landed", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("ECONNREFUSED"); }));
  const response = await POST(request('{"decision":"approve"}'), { params });
  expect(response.status).toBe(502);
  expect(await response.json()).toMatchObject({ state: "retryable_failure" });
});
