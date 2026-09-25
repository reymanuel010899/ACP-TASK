// @vitest-environment jsdom

// The server-authoritative envelope, exercised through the console rather than
// the projection functions. A field the server emits and the client ignores is
// indistinguishable from one that was never built, so every assertion here is
// about what a person actually sees or can press.

import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import ClientConsole from "./ClientConsole";

afterEach(() => {
  cleanup();
  sessionStorage.clear(); localStorage.clear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

async function openWith(reply: Record<string, unknown>, fetchMock: ReturnType<typeof vi.fn>) {
  HTMLElement.prototype.scrollTo = vi.fn();
  localStorage.setItem("tessera-csrf", "csrf-test");
  vi.stubGlobal("fetch", fetchMock);
  render(<ClientConsole />);
  fireEvent.click(screen.getByLabelText("Open concierge"));
  fireEvent.change(screen.getByPlaceholderText("¿Qué necesitas?"), {
    target: { value: "reacciona y avisa a María" },
  });
  await act(async () => { fireEvent.click(screen.getByText("Send")); await Promise.resolve(); });
  return reply;
}

const GROUP_REPLY = {
  state: "awaiting_approval", conversationId: "conversation:group",
  stateVersion: 4, terminal: false, allowedActions: ["approve", "reject"],
  effectGroup: {
    groupId: "group:1", summary: "0 of 2 completed",
    effects: [
      {
        effectId: "effect:react", capabilityId: "slack.reaction.add",
        summary: "add reaction #general", status: "awaiting_approval",
        reinforced: false, allowedActions: ["approve", "reject"],
        detailsExpanded: false,
      },
      {
        effectId: "effect:tell", capabilityId: "slack.message.post",
        summary: "post María", status: "awaiting_approval",
        reinforced: true, allowedActions: ["approve", "reject"],
        detailsExpanded: true,
      },
    ],
  },
};

it("shows a compound request as effects that are answered one at a time", async () => {
  const fetchMock = vi.fn().mockResolvedValueOnce(Response.json(GROUP_REPLY));
  await openWith(GROUP_REPLY, fetchMock);

  expect(screen.getByText("add reaction #general")).toBeInTheDocument();
  expect(screen.getByText("post María")).toBeInTheDocument();
  // Two effects, two independent approvals. One button for both would be the
  // group-as-transaction reading this whole design refuses.
  expect(screen.getAllByRole("button", { name: /aprobar|approve/i })).toHaveLength(2);
});

it("sends one effect's decision to that effect's own endpoint", async () => {
  const decided = {
    ...GROUP_REPLY, stateVersion: 5,
    effectGroup: {
      ...GROUP_REPLY.effectGroup, summary: "0 of 2 completed",
      effects: [
        { ...GROUP_REPLY.effectGroup.effects[0], status: "approved", allowedActions: [] },
        GROUP_REPLY.effectGroup.effects[1],
      ],
    },
  };
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(Response.json(GROUP_REPLY))
    .mockResolvedValueOnce(Response.json(decided));
  await openWith(GROUP_REPLY, fetchMock);

  await act(async () => {
    fireEvent.click(screen.getAllByRole("button", { name: /aprobar|approve/i })[0]);
    await Promise.resolve();
  });

  const [url, init] = fetchMock.mock.calls[1];
  expect(url).toBe(
    "/api/client/conversations/conversation%3Agroup/effects/effect%3Areact",
  );
  expect(JSON.parse(String((init as RequestInit).body))).toEqual({ decision: "approve" });
  expect((init as RequestInit).headers).toMatchObject({ "X-CSRF-Token": "csrf-test" });
});

it("refuses to repaint an older snapshot over a newer one", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(Response.json({
      state: "retrieving", conversationId: "conversation:lag",
      stateVersion: 9, terminal: false, reply: "Buscando…",
    }))
    // A late reply from an earlier version. Applying it would walk the
    // conversation backwards.
    .mockResolvedValue(Response.json({
      state: "retrieving", conversationId: "conversation:lag",
      stateVersion: 3, terminal: false, reply: "Instantánea vieja",
    }));
  vi.useFakeTimers();
  try {
    await openWith({}, fetchMock);
    await act(async () => { await vi.advanceTimersByTimeAsync(1600); });
    expect(screen.queryByText("Instantánea vieja")).not.toBeInTheDocument();
    expect(screen.getByText("Buscando…")).toBeInTheDocument();
  } finally {
    vi.useRealTimers();
  }
});

it("stops polling when the server says the conversation is terminal", async () => {
  const fetchMock = vi.fn().mockResolvedValueOnce(Response.json({
    // A status the client's own list still calls pollable. `terminal` is the
    // server's word, and it wins.
    state: "executing", conversationId: "conversation:done",
    stateVersion: 2, terminal: true, reply: "Listo.",
  }));
  vi.useFakeTimers();
  try {
    await openWith({}, fetchMock);
    await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  } finally {
    vi.useRealTimers();
  }
});

it("does not offer approval the server has not allowed", async () => {
  const fetchMock = vi.fn().mockResolvedValueOnce(Response.json({
    state: "retryable_failure", conversationId: "conversation:blocked",
    stateVersion: 3, terminal: true, allowedActions: [],
    draft: {
      draftHash: "sha256:draft", destination: "#general", text: "hola",
      workflowId: "workflow:1", revisionId: "revision:1", revision: 1,
    },
  }));
  await openWith({}, fetchMock);

  expect(screen.queryByRole("button", { name: "Confirmar y enviar" })).not.toBeInTheDocument();
  // The draft is still preserved, and the console still says so.
  expect(screen.getByText(/El borrador se conserva/)).toBeInTheDocument();
});

it("says the read model is catching up instead of presenting it as settled", async () => {
  const fetchMock = vi.fn().mockResolvedValueOnce(Response.json({
    state: "retrieving", conversationId: "conversation:lagging",
    stateVersion: 7, terminal: false, projectionLag: true, reply: "Un momento.",
  }));
  await openWith({}, fetchMock);
  expect(screen.getByText(/Poniéndome al día/)).toBeInTheDocument();
});

it("says why an answer is partial rather than only that it is", async () => {
  const fetchMock = vi.fn().mockResolvedValueOnce(Response.json({
    state: "ready", conversationId: "conversation:partial",
    stateVersion: 5, terminal: true,
    answer: "María mencionó el despliegue.", citations: [],
    partial: true, partialReason: "se alcanzó el límite de páginas",
  }));
  await openWith({}, fetchMock);
  expect(screen.getByText(/se alcanzó el límite de páginas/)).toBeInTheDocument();
});
