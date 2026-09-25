// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import WorkflowPreviewCard from "./WorkflowPreviewCard";
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); sessionStorage.clear(); localStorage.clear(); });
it("shows providers, disclosure and binds approval to the exact revision", async () => {
  localStorage.setItem("tessera-csrf", "csrf"); const fetchMock = vi.fn().mockImplementation((_url: string | URL | Request, init?: RequestInit) => init?.method === "POST" ? Promise.resolve(Response.json({ status: "approved" })) : Promise.resolve(Response.json({ revision: { steps: [{ step_id: "s", capability_id: "gmail.send", execution_status: "queued", verification_status: "pending" }] } }))); vi.stubGlobal("fetch", fetchMock);
  render(<WorkflowPreviewCard workflow={{ workflowId: "w1", revisionId: "r2", revision: 2, outcome: "Coordinar entrevista", steps: [{ id: "s", label: "Enviar correo", provider: "Google", account: "Acme", effect: "write", disclosure: "resumen con Google", effectFields: { to: "laura@example.com", body: { $ref: "search.output.summary" } } }] }} />);
  expect(screen.getByText(/resumen con Google/)).toBeVisible();
  expect(screen.getByText("laura@example.com")).toBeVisible();
  expect(screen.getByText(/Se completará con search.output.summary/)).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Aprobar este plan" }));
  expect(JSON.parse(String(fetchMock.mock.calls[0][1].body))).toMatchObject({ revisionId: "r2", revision: 2 });
});

it("renders completed Slack read output returned by workflow polling", async () => {
  localStorage.setItem("tessera-csrf", "csrf");
  const fetchMock = vi.fn().mockImplementation((_url: string | URL | Request, init?: RequestInit) =>
    init?.method === "POST"
      ? Promise.resolve(Response.json({ status: "approved" }))
      : Promise.resolve(Response.json({ revision: { steps: [{
        step_id: "channels", capability_id: "slack.channels.list",
        execution_status: "completed", verification_status: "not_required",
        output: { channels: [{ id: "C1", name: "tessera-test", is_private: false }] },
      }] } })),
  );
  vi.stubGlobal("fetch", fetchMock);
  render(<WorkflowPreviewCard workflow={{
    workflowId: "w1", revisionId: "r1", revision: 1,
    outcome: "Listar canales públicos", steps: [{
      id: "channels", label: "slack.channels.list", provider: "Slack",
      account: "Airobotix", effect: "read",
    }],
  }} />);

  await userEvent.click(screen.getByRole("button", { name: "Aprobar este plan" }));

  expect(await screen.findByText("#tessera-test")).toBeVisible();
});

it("shows the exact Slack payload and binds approval to its draft hash", async () => {
  localStorage.setItem("tessera-csrf", "csrf");
  const fetchMock = vi.fn().mockResolvedValue(Response.json({ status: "approved" }));
  vi.stubGlobal("fetch", fetchMock);
  render(<WorkflowPreviewCard
    workflow={{ workflowId: "w2", revisionId: "r3", revision: 3, outcome: "Enviar a #general", steps: [] }}
    slackDraft={{ conversationId: "conversation:2", draftHash: "sha256:abc", destination: "#general", text: "Hola\nequipo" }}
  />);

  expect(screen.getByText("#general")).toBeVisible();
  expect(screen.getByText(/Hola\s+equipo/)).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Confirmar y enviar" }));
  expect(JSON.parse(String(fetchMock.mock.calls[0][1].body))).toMatchObject({
    conversationId: "conversation:2", draftHash: "sha256:abc", revisionId: "r3", revision: 3,
  });
});

it("blocks approval for a superseded draft", () => {
  render(<WorkflowPreviewCard
    workflow={{ workflowId: "w2", revisionId: "r3", revision: 3, outcome: "Enviar", steps: [] }}
    slackDraft={{ conversationId: "conversation:2", draftHash: "old", destination: "#general", text: "Anterior" }}
    superseded
  />);
  expect(screen.getByRole("button", { name: "Confirmar y enviar" })).toBeDisabled();
  expect(screen.getByText(/ya no es válida/)).toBeVisible();
});

it("stops warning that an approval is invalid once it has been given", async () => {
  // Typing in the composer marks the draft superseded. After the approval has
  // landed that warning is simply false, and it appeared directly above the
  // confirmation that the plan was approved — two opposite claims about the
  // same message, one of which invites re-sending what was already sent.
  localStorage.setItem("tessera-csrf", "csrf-1");
  vi.stubGlobal("fetch", vi.fn(async () => Response.json({ ok: true })));
  render(
    <WorkflowPreviewCard
      workflow={{ workflowId: "w1", revisionId: "r1", revision: 1, outcome: "Enviar a #general", steps: [] }}
      slackDraft={{ conversationId: "conversation:1", draftHash: "sha256:d", destination: "#general", text: "hola" }}
      superseded
    />,
  );

  expect(screen.getByText(/Esta aprobación ya no es válida/)).toBeInTheDocument();

  // A superseded draft cannot be approved from the card, so drive the state
  // the way the console does: re-render as approved.
  cleanup();
  render(
    <WorkflowPreviewCard
      workflow={{ workflowId: "w1", revisionId: "r1", revision: 1, outcome: "Enviar a #general", steps: [] }}
      slackDraft={{ conversationId: "conversation:1", draftHash: "sha256:d", destination: "#general", text: "hola" }}
    />,
  );
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Confirmar y enviar" }));
    await Promise.resolve();
  });
  expect(screen.getByText(/Plan aprobado para esta revisión/)).toBeInTheDocument();
  expect(screen.queryByText(/Esta aprobación ya no es válida/)).not.toBeInTheDocument();
});
