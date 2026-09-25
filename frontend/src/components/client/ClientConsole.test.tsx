// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ClientConsole, { CHAT_INACTIVITY_MS } from "./ClientConsole";

describe("ClientConsole inactivity", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    HTMLElement.prototype.scrollTo = vi.fn();
    vi.stubGlobal("fetch", vi.fn(async () => ({
      json: async () => ({
        status: "conversation",
        reply: "Claro, seguimos conversando.",
        brain: "groq",
      }),
    })));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("closes and clears the chat after three minutes without a reply", async () => {
    render(<ClientConsole />);
    fireEvent.click(screen.getByLabelText("Open concierge"));
    fireEvent.change(screen.getByPlaceholderText("¿Qué necesitas?"), {
      target: { value: "Hola" },
    });

    await act(async () => {
      fireEvent.click(screen.getByText("Send"));
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByText("Claro, seguimos conversando.")).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(CHAT_INACTIVITY_MS - 1);
    });
    expect(screen.getByText("Claro, seguimos conversando.")).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.queryByPlaceholderText("¿Qué necesitas?")).not.toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("Open concierge"));
    expect(screen.queryByText("Claro, seguimos conversando.")).not.toBeInTheDocument();
  });

  it("renders a model-generated workflow preview in the same conversation", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ json: async () => ({
      status: "workflow_preview", reply: "Revisa el plan.", brain: "groq",
      workflow: { workflowId: "w1", revisionId: "r1", revision: 1,
        outcome: "Coordinar entrevista", steps: [{ id: "s1", label: "slack.thread.read", provider: "Slack", account: "Acme", effect: "read" }] },
    }) })));
    render(<ClientConsole />); fireEvent.click(screen.getByLabelText("Open concierge"));
    fireEvent.change(screen.getByPlaceholderText("¿Qué necesitas?"), { target: { value: "coordina la entrevista" } });
    await act(async () => { fireEvent.click(screen.getByText("Send")); await Promise.resolve(); await Promise.resolve(); });
    expect(screen.getByLabelText("Workflow preview")).toBeVisible();
    expect(screen.getByText("Coordinar entrevista")).toBeVisible();
  });

  it("survives a bare workflow handle for a run already in flight", async () => {
    // `_start_slack_entity_resolution` and `_conversation_response` both send
    // `workflow` as {workflowId, revisionId} with no steps -- rendering that as
    // a preview crashed the whole console on `workflow.steps.map`.
    vi.stubGlobal("fetch", vi.fn(async () => ({ json: async () => ({
      state: "retrieving", conversationId: "conversation:9", reply: "Buscando el canal…",
      workflow: { workflowId: "w2", revisionId: "r2" },
    }) })));
    render(<ClientConsole />); fireEvent.click(screen.getByLabelText("Open concierge"));
    fireEvent.change(screen.getByPlaceholderText("¿Qué necesitas?"), { target: { value: "¿qué dijo María?" } });
    await act(async () => { fireEvent.click(screen.getByText("Send")); await Promise.resolve(); await Promise.resolve(); });
    expect(screen.getByText("Buscando el canal…")).toBeVisible();
    expect(screen.queryByLabelText("Workflow preview")).not.toBeInTheDocument();
  });

  it("keeps the conversation id across clarification turns and offers accessible candidates", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(Response.json({
        state: "needs_input", conversationId: "conversation:7",
        need: { field: "person", question: "¿Cuál María?", options: [
          { id: "U1", display_name: "María", handle: "maria.ops" },
          { id: "U2", display_name: "María", handle: "maria.sales" },
        ] },
      }))
      .mockResolvedValueOnce(Response.json({
        state: "ready", conversationId: "conversation:7", answer: "María confirmó el envío.", citations: [],
      }));
    vi.stubGlobal("fetch", fetchMock);
    render(<ClientConsole />);
    fireEvent.click(screen.getByLabelText("Open concierge"));
    fireEvent.change(screen.getByPlaceholderText("¿Qué necesitas?"), { target: { value: "¿Qué dijo María?" } });
    await act(async () => { fireEvent.click(screen.getByText("Send")); await Promise.resolve(); });

    const candidate = screen.getByRole("button", { name: "María · @maria.sales" });
    await act(async () => { fireEvent.click(candidate); await Promise.resolve(); });

    const secondBody = JSON.parse(String(fetchMock.mock.calls[1][1]?.body));
    expect(secondBody).toMatchObject({ conversationId: "conversation:7", message: "María · @maria.sales" });
    expect(screen.getByText("María confirmó el envío.")).toBeVisible();
  });

  it("polls transient state and renders grounded Slack evidence", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(Response.json({ state: "retrieving", conversationId: "conversation:8", reply: "Buscando…" }))
      .mockResolvedValueOnce(Response.json({
        state: "ready", conversationId: "conversation:8", answer: "El lanzamiento sigue el viernes.",
        period: { label: "24–30 julio" }, partial: true,
        citations: [{ citation_id: "c1", permalink: "https://acme.slack.com/archives/C1/p1", author_label: "Ana" }],
      }));
    vi.stubGlobal("fetch", fetchMock);
    render(<ClientConsole />);
    fireEvent.click(screen.getByLabelText("Open concierge"));
    fireEvent.change(screen.getByPlaceholderText("¿Qué necesitas?"), { target: { value: "Resume #lanzamiento" } });
    await act(async () => { fireEvent.click(screen.getByText("Send")); await Promise.resolve(); });
    await act(async () => { vi.advanceTimersByTime(1500); await Promise.resolve(); });

    expect(screen.getByText("El lanzamiento sigue el viernes.")).toBeVisible();
    expect(screen.getByText("Periodo revisado: 24–30 julio")).toBeVisible();
    expect(screen.getByRole("link", { name: /Slack de Ana/ })).toBeVisible();
  });

  it("invalidates an exact Slack draft when the user edits its message", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({
      state: "awaiting_approval", conversationId: "conversation:9",
      draft: { draftHash: "hash-1", destination: "#general", text: "Hola equipo", workflowId: "w9", revisionId: "r9" },
    })));
    render(<ClientConsole />);
    fireEvent.click(screen.getByLabelText("Open concierge"));
    fireEvent.change(screen.getByPlaceholderText("¿Qué necesitas?"), { target: { value: "Manda un saludo" } });
    await act(async () => { fireEvent.click(screen.getByText("Send")); await Promise.resolve(); });

    expect(screen.getByText("#general")).toBeVisible();
    expect(screen.getByText("Hola equipo")).toBeVisible();
    const approve = screen.getByRole("button", { name: "Confirmar y enviar" });
    expect(approve).toBeEnabled();
    fireEvent.change(screen.getByPlaceholderText("¿Qué necesitas?"), { target: { value: "Hola equipo actualizado" } });
    expect(approve).toBeDisabled();
    expect(screen.getByText(/Esta aprobación ya no es válida/)).toBeVisible();
  });
});
