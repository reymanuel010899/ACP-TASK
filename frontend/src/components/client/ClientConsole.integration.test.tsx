// @vitest-environment jsdom

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

it("carries a grounded clarification into one exact tenant-bound approval", async () => {
  HTMLElement.prototype.scrollTo = vi.fn();
  localStorage.setItem("tessera-csrf", "csrf-test");
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(Response.json({
      state: "needs_input", conversationId: "conversation:e2e",
      need: { field: "person", question: "¿Cuál María?", options: [
        { id: "U1", display_name: "María", handle: "maria.ops" },
        { id: "U2", display_name: "María", handle: "maria.sales" },
      ] },
    }))
    .mockResolvedValueOnce(Response.json({
      state: "awaiting_approval", conversationId: "conversation:e2e",
      draft: {
        draftHash: "sha256:draft", destination: "María · @maria.sales",
        text: "La reunión empieza a las diez.", workflowId: "workflow:e2e",
        revisionId: "revision:e2e", revision: 2,
      },
    }))
    .mockResolvedValueOnce(Response.json({ state: "approved" }));
  vi.stubGlobal("fetch", fetchMock);

  render(<ClientConsole />);
  fireEvent.click(screen.getByLabelText("Open concierge"));
  fireEvent.change(screen.getByPlaceholderText("¿Qué necesitas?"), {
    target: { value: "Mándale a María que la reunión empieza a las diez." },
  });
  await act(async () => { fireEvent.click(screen.getByText("Send")); await Promise.resolve(); });
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "María · @maria.sales" }));
    await Promise.resolve();
  });

  expect(screen.getByText("La reunión empieza a las diez.")).toBeVisible();
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Confirmar y enviar" }));
    await Promise.resolve();
  });

  expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toMatchObject({
    conversationId: "conversation:e2e", message: "María · @maria.sales",
  });
  expect(fetchMock.mock.calls[2][0]).toBe("/api/workflows/workflow%3Ae2e/approve");
  expect(JSON.parse(String(fetchMock.mock.calls[2][1]?.body))).toMatchObject({
    conversationId: "conversation:e2e", draftHash: "sha256:draft",
    revisionId: "revision:e2e", revision: 2,
  });
});
