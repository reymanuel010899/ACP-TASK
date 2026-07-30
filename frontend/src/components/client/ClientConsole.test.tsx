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
});
