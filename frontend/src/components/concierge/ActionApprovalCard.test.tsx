// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import ActionApprovalCard from "./ActionApprovalCard";

const proposal = {
  proposalId: "proposal-1",
  version: 2,
  capabilityId: "calendar.create",
  agentName: "Scheduling Agent",
  connectedAccount: "a***@example.com",
  expiresAt: "in 5 minutes",
  risk: "Creates an external calendar event",
  summary: "Interview with Ana",
  participants: ["Ana", "You"],
  timeZone: "America/Santo_Domingo",
};

beforeEach(() => {
  window.sessionStorage.clear(); window.localStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("shows material action fields and approves the exact version once", async () => {
  window.localStorage.setItem("tessera-csrf", "csrf-1");
  const fetchMock = vi.fn<typeof fetch>();
  fetchMock.mockResolvedValue(Response.json({ status: "approved" }));
  vi.stubGlobal("fetch", fetchMock);
  const onDecision = vi.fn();
  render(<ActionApprovalCard proposal={proposal} onDecision={onDecision} />);

  expect(screen.getByText("Scheduling Agent")).toBeVisible();
  expect(screen.getByText("America/Santo_Domingo")).toBeVisible();
  expect(screen.getByText(/Ana, You/)).toBeVisible();

  await userEvent.click(screen.getByRole("button", { name: "Approve exact action" }));
  await waitFor(() => expect(onDecision).toHaveBeenCalledWith(true));
  const init = fetchMock.mock.calls[0][1];
  expect(init).toBeDefined();
  expect(JSON.parse(String(init?.body))).toEqual({ approved: true, version: 2 });
  expect(screen.getByText("Approved for one execution.")).toBeVisible();
  expect(screen.getByRole("button", { name: "Approve exact action" })).toBeDisabled();
});

it("rejects accessibly and reports missing secure session without a request", async () => {
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  render(<ActionApprovalCard proposal={proposal} />);

  await userEvent.click(screen.getByRole("button", { name: "Reject" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("secure session");
  expect(fetchMock).not.toHaveBeenCalled();
});
