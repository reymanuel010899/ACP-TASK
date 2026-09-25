// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import CampaignsContent from "./CampaignsContent";

vi.mock("@/lib/agentSession", () => ({ readStoredCsrfToken: () => "csrf:test" }));

const branches = [{ branchId: "branch:clients", name: "Clientes", path: "/general/clientes", kind: "folder", depth: 1, contactCount: 1, children: [] }];

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === "/api/campaigns" && !init?.method) return new Response(JSON.stringify({ campaigns: [] }), { status: 200 });
    if (url === "/api/contacts/branches") return new Response(JSON.stringify({ branches }), { status: 200 });
    if (url === "/api/campaigns/preview") return new Response(JSON.stringify({
      campaign_id: "campaign:1", eligible_count: 1, estimated_spend_micros: 10000,
      audience: [{ contact_id: "contact:1", channel: "sms", masked_destination: "+1 •••• 7140", branch_id: "branch:clients" }],
      exclusion_reasons: {}, envelope_hash: "hash:1",
    }), { status: 201 });
    if (url.includes("/authorize")) return new Response(JSON.stringify({ campaignId: "campaign:1", status: "authorized" }), { status: 202 });
    throw new Error(`unexpected request ${url}`);
  }));
});

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

test("opens the campaign composer and requires a preview before launch", async () => {
  render(<CampaignsContent />);
  await screen.findByText("Todavía no hay campañas");
  fireEvent.click(screen.getByRole("button", { name: "+ Nueva campaña" }));
  fireEvent.change(screen.getByLabelText("Nombre"), { target: { value: "Prueba SMS" } });
  fireEvent.change(screen.getByLabelText("Audiencia"), { target: { value: "branch:clients" } });
  fireEvent.change(screen.getByPlaceholderText("Hola, te recordamos que…"), { target: { value: "Hola desde Tessera" } });
  fireEvent.click(screen.getByRole("button", { name: "Revisar audiencia" }));
  expect(await screen.findByText("1 contactos elegibles")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Autorizar y lanzar" })).toBeDisabled();
});

test("authorizes exactly the previewed envelope", async () => {
  render(<CampaignsContent />);
  await screen.findByText("Todavía no hay campañas");
  fireEvent.click(screen.getByRole("button", { name: "+ Nueva campaña" }));
  fireEvent.change(screen.getByLabelText("Nombre"), { target: { value: "Prueba SMS" } });
  fireEvent.change(screen.getByLabelText("Audiencia"), { target: { value: "branch:clients" } });
  fireEvent.change(screen.getByPlaceholderText("Hola, te recordamos que…"), { target: { value: "Hola" } });
  fireEvent.click(screen.getByRole("button", { name: "Revisar audiencia" }));
  await screen.findByText("1 contactos elegibles");
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Autorizar y lanzar" }));
  await waitFor(() => expect(fetch).toHaveBeenCalledWith(
    "/api/campaigns/campaign%3A1/authorize",
    expect.objectContaining({ body: JSON.stringify({ envelopeHash: "hash:1" }) }),
  ));
});
