// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ProposalQueue, {
  maskedLabel,
  missingEvidenceFields,
  type ContactProposal,
} from "./ProposalQueue";

function proposal(overrides: Partial<ContactProposal> = {}): ContactProposal {
  return {
    proposalId: "address:01JBQ9YHY3W4M9K1Q7S2X8T5ZR",
    contactId: "contact:01JBQ9YHY3W4M9K1Q7S2X8T5ZQ",
    displayName: "Ana Pérez",
    branchPath: "/acme/sales",
    channel: "sms",
    destination: {
      channel: "sms",
      text: "+34 ••• ••• 222",
      countryCode: "34",
      digitCount: 11,
      visibleTail: "222",
      fingerprint: "a1b2c3d4",
      branchPath: "/acme/sales",
      lastContactedAt: null,
    },
    proposedByActorKind: "agent",
    proposedByPrincipalId: "agent:concierge",
    proposedAt: "2026-08-04T12:00:00Z",
    pendingConsent: [],
    ...overrides,
  };
}

function fillEvidence() {
  fireEvent.change(screen.getByLabelText("Método de captura"), { target: { value: "web_form" } });
  fireEvent.change(screen.getByLabelText("Fecha y hora locales"), { target: { value: "2026-08-03T14:00" } });
  fireEvent.change(screen.getByLabelText("Zona horaria"), { target: { value: "Europe/Madrid" } });
  fireEvent.change(screen.getByLabelText("Jurisdicción"), { target: { value: "ES" } });
  fireEvent.change(screen.getByLabelText("Texto mostrado"), { target: { value: "Acepto recibir mensajes." } });
  fireEvent.change(screen.getByLabelText("Base legal"), { target: { value: "consent" } });
  fireEvent.click(screen.getByLabelText("La casilla empezó vacía"));
}

describe("ProposalQueue", () => {
  afterEach(cleanup);

  it("says the queue is empty rather than rendering nothing at all", () => {
    render(<ProposalQueue proposals={[]} onApprove={vi.fn()} onReject={vi.fn()} />);

    expect(screen.getByRole("status")).toHaveTextContent("No hay propuestas esperando revisión.");
  });

  it("shows a destination masked and never renders the digits", () => {
    render(
      <ProposalQueue proposals={[proposal()]} onApprove={vi.fn()} onReject={vi.fn()} />,
    );

    const item = screen.getByRole("listitem");
    expect(within(item).getByTestId("masked-destination")).toHaveTextContent("+34 ••• ••• 222");
    // The subscriber digits are the thing the mask withholds. If they ever
    // reach this component they will reach a screen.
    expect(item.textContent).not.toContain("600111222");
    expect(within(item).getByText("a1b2c3d4")).toBeVisible();
  });

  it("names who proposed it, because an agent claim is not a human decision", () => {
    render(
      <ProposalQueue proposals={[proposal()]} onApprove={vi.fn()} onReject={vi.fn()} />,
    );

    expect(screen.getByText("agent · agent:concierge")).toBeVisible();
  });

  it("approves an address-only proposal without demanding consent evidence", () => {
    const onApprove = vi.fn();
    render(
      <ProposalQueue proposals={[proposal()]} onApprove={onApprove} onReject={vi.fn()} />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Aprobar y activar" }));

    expect(onApprove).toHaveBeenCalledWith(
      "address:01JBQ9YHY3W4M9K1Q7S2X8T5ZR",
      { evidence: undefined, purposes: [], reason: undefined },
    );
  });

  it("refuses to approve a claimed consent until U6's evidence is present", () => {
    const onApprove = vi.fn();
    render(
      <ProposalQueue
        proposals={[proposal({ pendingConsent: ["marketing"] })]}
        onApprove={onApprove}
        onReject={vi.fn()}
      />,
    );

    const approve = screen.getByRole("button", { name: "Aprobar y activar" });
    expect(approve).toBeDisabled();
    // Named, not merely blocked: an operator who cannot see which field is
    // missing fills the form again and gets the same refusal.
    expect(screen.getByText(/Falta evidencia/)).toHaveTextContent("captureMethod");

    fireEvent.click(approve);
    expect(onApprove).not.toHaveBeenCalled();
  });

  it("carries the evidence and the claimed purposes into the decision", () => {
    const onApprove = vi.fn();
    render(
      <ProposalQueue
        proposals={[proposal({ pendingConsent: ["marketing"] })]}
        onApprove={onApprove}
        onReject={vi.fn()}
      />,
    );

    fillEvidence();
    fireEvent.change(screen.getByLabelText("Motivo"), { target: { value: "confirmado por teléfono" } });
    fireEvent.click(screen.getByRole("button", { name: "Aprobar y activar" }));

    expect(onApprove).toHaveBeenCalledTimes(1);
    expect(onApprove.mock.calls[0][0]).toBe("address:01JBQ9YHY3W4M9K1Q7S2X8T5ZR");
    expect(onApprove.mock.calls[0][1]).toMatchObject({
      purposes: ["marketing"],
      reason: "confirmado por teléfono",
      evidence: {
        captureMethod: "web_form",
        capturedAtLocal: "2026-08-03T14:00",
        captureTimezone: "Europe/Madrid",
        jurisdiction: "ES",
        disclosureText: "Acepto recibir mensajes.",
        legalBasis: "consent",
        defaultUnchecked: true,
      },
    });
  });

  it("rejects with a reason, and rejecting never needs evidence", () => {
    const onReject = vi.fn();
    render(
      <ProposalQueue
        proposals={[proposal({ pendingConsent: ["marketing"] })]}
        onApprove={vi.fn()}
        onReject={onReject}
      />,
    );

    fireEvent.change(screen.getByLabelText("Motivo"), { target: { value: "número equivocado" } });
    fireEvent.click(screen.getByRole("button", { name: "Rechazar" }));

    expect(onReject).toHaveBeenCalledWith(
      "address:01JBQ9YHY3W4M9K1Q7S2X8T5ZR",
      "número equivocado",
    );
  });

  it("decides one proposal at a time even when several are waiting", () => {
    const onApprove = vi.fn();
    render(
      <ProposalQueue
        proposals={[
          proposal(),
          proposal({ proposalId: "address:01JBQ9YHY3W4M9K1Q7S2X8T5ZS", displayName: "Ana Pérez" }),
        ]}
        onApprove={onApprove}
        onReject={vi.fn()}
      />,
    );

    const rows = screen.getAllByRole("listitem");
    fireEvent.click(within(rows[1]).getByRole("button", { name: "Aprobar y activar" }));

    expect(onApprove).toHaveBeenCalledTimes(1);
    expect(onApprove.mock.calls[0][0]).toBe("address:01JBQ9YHY3W4M9K1Q7S2X8T5ZS");
  });

  it("binds the decision to the proposal identifier, never to the name", () => {
    const onApprove = vi.fn();
    // Two proposals with identical display names is the ordinary case the
    // whole queue has to survive: a label cannot tell them apart.
    render(
      <ProposalQueue
        proposals={[
          proposal({ proposalId: "address:01JBQ9YHY3W4M9K1Q7S2X8T5ZA" }),
          proposal({ proposalId: "address:01JBQ9YHY3W4M9K1Q7S2X8T5ZB" }),
        ]}
        onApprove={onApprove}
        onReject={vi.fn()}
      />,
    );

    const rows = screen.getAllByRole("listitem");
    fireEvent.click(within(rows[0]).getByRole("button", { name: "Aprobar y activar" }));
    fireEvent.click(within(rows[1]).getByRole("button", { name: "Aprobar y activar" }));

    expect(onApprove.mock.calls.map((call) => call[0])).toEqual([
      "address:01JBQ9YHY3W4M9K1Q7S2X8T5ZA",
      "address:01JBQ9YHY3W4M9K1Q7S2X8T5ZB",
    ]);
  });

  it("locks both buttons while a decision is in flight", () => {
    render(
      <ProposalQueue
        proposals={[proposal()]}
        onApprove={vi.fn()}
        onReject={vi.fn()}
        busyProposalId="address:01JBQ9YHY3W4M9K1Q7S2X8T5ZR"
      />,
    );

    expect(screen.getByRole("button", { name: "Aprobar y activar" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Rechazar" })).toBeDisabled();
  });

  it("counts what is waiting so an operator can see the queue is not empty", () => {
    render(
      <ProposalQueue
        proposals={[proposal(), proposal({ proposalId: "address:01JBQ9YHY3W4M9K1Q7S2X8T5ZC" })]}
        onApprove={vi.fn()}
        onReject={vi.fn()}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent("2 propuestas esperando tu decisión");
  });
});

describe("missingEvidenceFields", () => {
  it("names every absent required field in a stable order", () => {
    expect(
      missingEvidenceFields({
        captureMethod: "",
        capturedAtLocal: "",
        captureTimezone: "",
        jurisdiction: "",
        disclosureText: "",
        legalBasis: "",
        defaultUnchecked: false,
      }),
    ).toEqual([
      "captureMethod",
      "capturedAtLocal",
      "jurisdiction",
      "disclosureText",
      "legalBasis",
    ]);
  });

  it("treats a pre-ticked box on a form capture as missing proof, not as proof", () => {
    const evidence = {
      captureMethod: "web_form",
      capturedAtLocal: "2026-08-03T14:00",
      captureTimezone: "Europe/Madrid",
      jurisdiction: "ES",
      disclosureText: "Acepto.",
      legalBasis: "consent",
      defaultUnchecked: false,
    };

    expect(missingEvidenceFields(evidence)).toEqual(["defaultUnchecked"]);
    expect(missingEvidenceFields({ ...evidence, defaultUnchecked: true })).toEqual([]);
  });

  it("does not demand a checkbox proof where the capture had no checkbox", () => {
    expect(
      missingEvidenceFields({
        captureMethod: "verbal_recorded",
        capturedAtLocal: "2026-08-03T14:00",
        captureTimezone: "Europe/Madrid",
        jurisdiction: "ES",
        disclosureText: "Acepto.",
        legalBasis: "consent",
        defaultUnchecked: false,
      }),
    ).toEqual([]);
  });
});

describe("maskedLabel", () => {
  it("prefixes the country code, because the wrong country is the costly mistake", () => {
    expect(
      maskedLabel({ channel: "sms", text: "••• ••• 222", countryCode: "34", fingerprint: "a1" }),
    ).toBe("+34 ••• ••• 222");
  });

  it("renders an emailish mask with no country code at all", () => {
    expect(
      maskedLabel({ channel: "email", text: "a••@example.com", countryCode: null, fingerprint: "a1" }),
    ).toBe("a••@example.com");
  });
});
