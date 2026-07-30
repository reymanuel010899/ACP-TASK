// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import WorkflowPreviewCard from "./WorkflowPreviewCard";
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); sessionStorage.clear(); });
it("shows providers, disclosure and binds approval to the exact revision", async () => {
  sessionStorage.setItem("tessera-csrf", "csrf"); const fetchMock = vi.fn().mockImplementation((_url: string | URL | Request, init?: RequestInit) => init?.method === "POST" ? Promise.resolve(Response.json({ status: "approved" })) : Promise.resolve(Response.json({ revision: { steps: [{ step_id: "s", capability_id: "gmail.send", execution_status: "queued", verification_status: "pending" }] } }))); vi.stubGlobal("fetch", fetchMock);
  render(<WorkflowPreviewCard workflow={{ workflowId: "w1", revisionId: "r2", revision: 2, outcome: "Coordinar entrevista", steps: [{ id: "s", label: "Enviar correo", provider: "Google", account: "Acme", effect: "write", disclosure: "resumen con Google", effectFields: { to: "laura@example.com", body: { $ref: "search.output.summary" } } }] }} />);
  expect(screen.getByText(/resumen con Google/)).toBeVisible();
  expect(screen.getByText("laura@example.com")).toBeVisible();
  expect(screen.getByText(/Se completará con search.output.summary/)).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Aprobar este plan" }));
  expect(JSON.parse(String(fetchMock.mock.calls[0][1].body))).toMatchObject({ revisionId: "r2", revision: 2 });
});

it("renders completed Slack read output returned by workflow polling", async () => {
  sessionStorage.setItem("tessera-csrf", "csrf");
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
