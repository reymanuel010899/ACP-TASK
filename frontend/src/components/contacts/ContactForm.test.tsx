// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ContactForm from "./ContactForm";

const BRANCHES = [
  { branchId: "branch:sales", path: "/acme/sales" },
  { branchId: "branch:finance", path: "/acme/finance" },
];

function fillEvidence() {
  fireEvent.change(screen.getByLabelText("Método de captura"), { target: { value: "web_form" } });
  fireEvent.change(screen.getByLabelText("Fecha y hora locales"), { target: { value: "2026-08-03T14:00" } });
  fireEvent.change(screen.getByLabelText("Zona horaria"), { target: { value: "Europe/Madrid" } });
  fireEvent.change(screen.getByLabelText("Jurisdicción"), { target: { value: "ES" } });
  fireEvent.change(screen.getByLabelText("Texto mostrado"), { target: { value: "Acepto recibir mensajes." } });
  fireEvent.change(screen.getByLabelText("Base legal"), { target: { value: "consent" } });
  fireEvent.click(screen.getByLabelText("La casilla empezó vacía"));
}

describe("ContactForm", () => {
  afterEach(cleanup);

  it("refuses to submit a person with no name", () => {
    render(<ContactForm branches={BRANCHES} onSubmit={vi.fn()} />);

    expect(screen.getByRole("button", { name: "Crear contacto" })).toBeDisabled();
  });

  it("creates a person with a destination and says it lands unusable", () => {
    const onSubmit = vi.fn();
    render(<ContactForm branches={BRANCHES} onSubmit={onSubmit} />);

    fireEvent.change(screen.getByLabelText("Nombre visible"), { target: { value: "Ana Pérez" } });
    fireEvent.change(screen.getByLabelText("Número en formato internacional"), { target: { value: "+34 600 111 222" } });

    expect(
      screen.getByText("Un destino nuevo queda inutilizable hasta que alguien autorizado lo active."),
    ).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Crear contacto" }));

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        branchId: "branch:sales",
        channel: "sms",
        address: "+34 600 111 222",
        consent: undefined,
      }),
    );
  });

  it("will not let a consent claim through without the evidence that defends it", () => {
    const onSubmit = vi.fn();
    render(<ContactForm branches={BRANCHES} onSubmit={onSubmit} />);

    fireEvent.change(screen.getByLabelText("Nombre visible"), { target: { value: "Ana Pérez" } });
    fireEvent.change(screen.getByLabelText("Número en formato internacional"), { target: { value: "+34600111222" } });
    fireEvent.click(screen.getByLabelText("Tengo evidencia de consentimiento para esta persona"));

    // This is the shape a purchased list arrives in: a claim of permission
    // with nothing behind it. The button stays shut and says which parts.
    expect(screen.getByRole("button", { name: "Crear contacto" })).toBeDisabled();
    expect(screen.getByText(/Falta evidencia:/)).toHaveTextContent("captureMethod");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("still refuses a complete evidence bundle that names no purpose", () => {
    render(<ContactForm branches={BRANCHES} onSubmit={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("Nombre visible"), { target: { value: "Ana Pérez" } });
    fireEvent.change(screen.getByLabelText("Número en formato internacional"), { target: { value: "+34600111222" } });
    fireEvent.click(screen.getByLabelText("Tengo evidencia de consentimiento para esta persona"));
    fillEvidence();

    expect(screen.getByRole("button", { name: "Crear contacto" })).toBeDisabled();
    expect(
      screen.getByText("Un consentimiento vale para las finalidades que nombra: elige al menos una."),
    ).toBeVisible();
  });

  it("submits the purposes alongside the evidence once both are present", () => {
    const onSubmit = vi.fn();
    render(<ContactForm branches={BRANCHES} onSubmit={onSubmit} />);

    fireEvent.change(screen.getByLabelText("Nombre visible"), { target: { value: "Ana Pérez" } });
    fireEvent.change(screen.getByLabelText("Número en formato internacional"), { target: { value: "+34600111222" } });
    fireEvent.click(screen.getByLabelText("Tengo evidencia de consentimiento para esta persona"));
    fillEvidence();
    fireEvent.click(screen.getByLabelText("marketing"));
    fireEvent.click(screen.getByRole("button", { name: "Crear contacto" }));

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        consent: expect.objectContaining({
          purposes: ["marketing"],
          evidence: expect.objectContaining({ jurisdiction: "ES", defaultUnchecked: true }),
        }),
      }),
    );
  });

  it("keeps a pre-ticked box out of the evidence bundle", () => {
    render(<ContactForm branches={BRANCHES} onSubmit={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("Nombre visible"), { target: { value: "Ana Pérez" } });
    fireEvent.change(screen.getByLabelText("Número en formato internacional"), { target: { value: "+34600111222" } });
    fireEvent.click(screen.getByLabelText("Tengo evidencia de consentimiento para esta persona"));
    fireEvent.change(screen.getByLabelText("Método de captura"), { target: { value: "web_form" } });
    fireEvent.change(screen.getByLabelText("Fecha y hora locales"), { target: { value: "2026-08-03T14:00" } });
    fireEvent.change(screen.getByLabelText("Jurisdicción"), { target: { value: "ES" } });
    fireEvent.change(screen.getByLabelText("Texto mostrado"), { target: { value: "Acepto." } });
    fireEvent.change(screen.getByLabelText("Base legal"), { target: { value: "consent" } });
    fireEvent.click(screen.getByLabelText("marketing"));

    // A form capture with no proof the box started empty is not consent in
    // any jurisdiction that has an opinion.
    expect(screen.getByRole("button", { name: "Crear contacto" })).toBeDisabled();
    expect(screen.getByText(/Falta evidencia:/)).toHaveTextContent("defaultUnchecked");
  });

  it("gives an edit no way to reach a destination, consent, or the branch", () => {
    const onSubmit = vi.fn();
    render(
      <ContactForm
        branches={BRANCHES}
        onSubmit={onSubmit}
        initial={{
          contactId: "contact:1",
          branchId: "branch:sales",
          recordVersion: "abc123",
          displayName: "Ana Pérez",
          givenName: "Ana",
          familyName: "Pérez",
          companyName: "Acme",
          jobTitle: "Compras",
        }}
      />,
    );

    // Each of those has its own ledger and its own authority gate. A form that
    // could write them would be a second, quieter way to grant something.
    expect(screen.queryByLabelText("Número en formato internacional")).toBeNull();
    expect(screen.queryByLabelText("Tengo evidencia de consentimiento para esta persona")).toBeNull();
    expect(screen.getByLabelText("Rama")).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Puesto"), { target: { value: "Dirección de compras" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar corrección" }));

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        contactId: "contact:1",
        recordVersion: "abc123",
        address: undefined,
        channel: undefined,
        consent: undefined,
        values: expect.objectContaining({ jobTitle: "Dirección de compras" }),
      }),
    );
  });
});
