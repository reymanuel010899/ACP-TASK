// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ContactRecord, { type ContactRecordData } from "./ContactRecord";

const DIGITS = "600111222";

function address(overrides: Partial<ContactRecordData["addresses"][number]> = {}) {
  return {
    addressId: "address:01JBQ9YHY3W4M9K1Q7S2X8T5ZR",
    channel: "sms",
    isPrimary: true,
    label: null,
    lastContactedAt: "2026-07-30",
    destination: {
      channel: "sms",
      text: "+34 ••• ••• 1222 · a1b2c3d4 · /acme/sales · last contacted 2026-07-30",
      countryCode: "34",
      digitCount: 11,
      visibleTail: "1222",
      fingerprint: "a1b2c3d4",
      branchPath: "/acme/sales",
      lastContactedAt: "2026-07-30",
    },
    usability: "active",
    suppression: "none",
    providerReachability: "reachable",
    consent: {
      marketing: {
        state: "granted",
        captureMethod: "import_form",
        capturedAt: "2026-08-02T12:00:00Z",
        jurisdiction: "ES",
        legalBasis: "consent",
        disclosureHash: "deadbeefcafe",
        expiresAt: null,
        decidedByPrincipalId: "principal:manager",
      },
      service: { state: "unknown" },
    },
    exclusions: { service: "consent_missing" },
    ...overrides,
  };
}

function record(overrides: Partial<ContactRecordData> = {}): ContactRecordData {
  return {
    contactId: "contact:01JBQ9YHY3W4M9K1Q7S2X8T5ZQ",
    recordVersion: "9f2c3a4b5d6e7f80",
    branchPath: "/acme/sales",
    status: "active",
    source: "import",
    displayName: "Ana Pérez",
    givenName: "Ana",
    familyName: "Pérez",
    companyName: "Acme",
    jobTitle: "Compras",
    addresses: [address()],
    authorizedChannels: ["sms"],
    mayEdit: true,
    ...overrides,
  };
}

describe("ContactRecord", () => {
  afterEach(cleanup);

  it("answers a record it may not show with absence rather than a refusal", () => {
    render(<ContactRecord record={null} />);

    // A distinguishable "you are not allowed to see Ana Pérez" would confirm
    // she exists, which is the disclosure the null answer avoids.
    expect(screen.getByRole("status")).toHaveTextContent(
      "No hay ninguna ficha que puedas ver con este identificador.",
    );
  });

  it("shows the destination masked and never the digits", () => {
    render(<ContactRecord record={record()} />);

    expect(screen.getByTestId("masked-destination")).toHaveTextContent("+34 ••• ••• 1222");
    expect(document.body.textContent).not.toContain(DIGITS);
  });

  it("renders the four axes separately instead of collapsing them to one badge", () => {
    render(
      <ContactRecord
        record={record({
          addresses: [address({ suppression: "suppressed_by_bounce", exclusions: { marketing: "suppressed_by_bounce" } })],
        })}
      />,
    );

    // A live grant and a bounce suppression are both true at once. An operator
    // shown only the losing one has no way to act.
    expect(screen.getByTestId("axis-usability")).toHaveTextContent("active");
    expect(screen.getByTestId("axis-suppression")).toHaveTextContent("suppressed_by_bounce");
    expect(screen.getByTestId("axis-providerReachability")).toHaveTextContent("reachable");
    expect(within(screen.getByTestId("consent-marketing")).getByText("granted")).toBeVisible();
    expect(screen.getByTestId("exclusion-marketing")).toHaveTextContent("suppressed_by_bounce");
  });

  it("shows the evidence behind a grant, and only the hash of the wording", () => {
    render(<ContactRecord record={record()} />);
    const row = screen.getByTestId("consent-marketing");

    expect(within(row).getByText("import_form")).toBeVisible();
    expect(within(row).getByText("ES")).toBeVisible();
    expect(within(row).getByText("consent")).toBeVisible();
    expect(within(row).getByText("deadbeef")).toBeVisible();
  });

  it("says an unusable destination cannot receive an effect yet", () => {
    render(<ContactRecord record={record({ addresses: [address({ usability: "proposed" })] })} />);

    expect(
      screen.getByText(
        "Este destino no puede recibir ningún efecto hasta que una persona autorizada lo active.",
      ),
    ).toBeVisible();
  });

  it("withholds the identity and the written destination from a redacted record", () => {
    const redacted = record({
      redacted: true,
      displayName: undefined,
      givenName: undefined,
      familyName: undefined,
      companyName: undefined,
      jobTitle: undefined,
      addresses: [address()],
      mayEdit: false,
    });

    render(<ContactRecord record={redacted} />);

    // Asserted against the whole document, not the fields a reader remembered
    // to check: a leak in one forgotten field is the leak that ships.
    expect(document.body.textContent).not.toContain("Ana Pérez");
    expect(document.body.textContent).not.toContain(DIGITS);
    expect(screen.queryByTestId("written-address")).toBeNull();
    expect(screen.getByText("Identidad reservada")).toBeVisible();
    // Still useful for the job campaign-use actually is: which destination,
    // and why it is or is not reachable.
    expect(screen.getByTestId("masked-destination")).toHaveTextContent("a1b2c3d4");
    expect(screen.getByTestId("exclusion-service")).toHaveTextContent("consent_missing");
  });

  it("shows the written form only when the server chose to send it", () => {
    render(
      <ContactRecord
        record={record({ addresses: [address({ writtenAddress: "+34 600 111 222" })] })}
      />,
    );

    expect(screen.getByTestId("written-address")).toHaveTextContent("+34 600 111 222");
  });

  it("keeps editing out of reach for a principal without edit authority", () => {
    const onEdit = vi.fn();
    render(<ContactRecord record={record({ mayEdit: false })} onEdit={onEdit} />);

    expect(screen.getByRole("button", { name: "Editar ficha" })).toBeDisabled();
    expect(onEdit).not.toHaveBeenCalled();
  });

  it("reports the channels that are authorized right now, not the ones configured", () => {
    render(<ContactRecord record={record({ authorizedChannels: [] })} />);

    expect(screen.getByTestId("authorized-channels")).toHaveTextContent("ninguno");
  });
});
