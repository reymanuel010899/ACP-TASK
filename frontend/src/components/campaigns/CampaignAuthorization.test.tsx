// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, expect, test, vi } from "vitest";
import CampaignAuthorization from "./CampaignAuthorization";

const preview = {
  campaignId: "campaign:1",
  eligibleCount: 2,
  estimatedSpendMicros: 3500000,
  audience: [
    { contactId: "contact:1", channel: "sms", maskedDestination: "+1 •••• 0101", branchId: "branch:sales" },
  ],
  exclusionReasons: { consent_missing: 2, quiet_hours: 1 },
  envelopeHash: "abc123",
};

afterEach(cleanup);

test("shows a redacted audience, exclusions, and estimated spend", () => {
  render(<CampaignAuthorization preview={preview} onAuthorize={() => undefined} />);
  expect(screen.getByText("2 contactos elegibles")).toBeInTheDocument();
  expect(screen.getByText("Gasto máximo estimado: $3.50")).toBeInTheDocument();
  expect(screen.getByText("+1 •••• 0101")).toBeInTheDocument();
  expect(screen.getByText("consent missing: 2")).toBeInTheDocument();
  expect(screen.queryByText(/address_id/i)).not.toBeInTheDocument();
});

test("requires explicit acknowledgement before authorizing", () => {
  const authorize = vi.fn();
  render(<CampaignAuthorization preview={preview} onAuthorize={authorize} />);
  const button = screen.getByRole("button", { name: "Autorizar y lanzar" });
  expect(button).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(button);
  expect(authorize).toHaveBeenCalledWith("campaign:1", "abc123");
});
