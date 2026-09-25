// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import CapabilityFamilyControls from "./CapabilityFamilyControls";

beforeEach(() => {
  window.sessionStorage.clear();
  window.localStorage.clear();
  window.localStorage.setItem("tessera-csrf", "csrf-test");
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function response(body: unknown, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response);
}

const TWO_FAMILIES = {
  emergency_stop: false,
  families: [
    { family: "slack_messaging", enabled: true },
    { family: "slack_direct_messages", enabled: true },
  ],
};

describe("CapabilityFamilyControls", () => {
  it("turns one family off without touching the others", async () => {
    const fetchMock = vi
      .fn()
      .mockImplementationOnce(() => response(TWO_FAMILIES))
      .mockImplementationOnce(() =>
        response({
          emergency_stop: false,
          families: [
            { family: "slack_messaging", enabled: true },
            { family: "slack_direct_messages", enabled: false },
          ],
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    render(<CapabilityFamilyControls />);
    fireEvent.click(await screen.findByRole("button", { name: "Turn off send direct messages" }));

    expect(await screen.findByText("Tessera will no longer send direct messages.")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/integrations/control-plane",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ action: "family", family: "slack_direct_messages", enabled: false }),
      }),
    );
    // The other family is untouched and still offers to be turned off.
    expect(screen.getByRole("button", { name: "Turn off post messages and replies" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Turn on send direct messages" })).toBeInTheDocument();
  });

  it("stops the account and shows what was dispatched against what was prevented", async () => {
    const fetchMock = vi
      .fn()
      .mockImplementationOnce(() => response(TWO_FAMILIES))
      .mockImplementationOnce(() =>
        response({
          emergency_stop: true,
          stop_reason: "paged",
          families: [
            { family: "slack_messaging", enabled: true },
            { family: "slack_direct_messages", enabled: true },
          ],
          effects: { dispatched: 3, prevented: 2, in_progress: 1, uncertain: 4 },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    render(<CapabilityFamilyControls />);
    fireEvent.click(await screen.findByRole("button", { name: "Stop everything" }));

    expect(await screen.findByRole("button", { name: "Resume this account" })).toBeInTheDocument();
    const counts = screen.getByRole("group", { name: "Emergency stop" });
    expect(counts).toHaveTextContent("Dispatched3");
    expect(counts).toHaveTextContent("Prevented2");
    expect(counts).toHaveTextContent("In progress1");
    // Uncertain is its own bucket. Folding it into dispatched would make the
    // stop's own report the least trustworthy thing on the screen.
    expect(counts).toHaveTextContent("Uncertain4");
    expect(screen.getByText("Reason: paged")).toBeInTheDocument();
  });

  it("says nothing is known when the control plane cannot be read", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => response({ error: "nope" }, 502)));

    render(<CapabilityFamilyControls />);

    expect(
      await screen.findByText("We could not read your capability controls, so we cannot say what is on."),
    ).toBeInTheDocument();
    // Fail closed in what is shown: no switch is offered as if it were on.
    expect(screen.queryByRole("button", { name: /Turn off/ })).not.toBeInTheDocument();
  });

  it("refuses to change anything without a CSRF token", async () => {
    window.localStorage.clear();
    const fetchMock = vi.fn().mockImplementationOnce(() => response(TWO_FAMILIES));
    vi.stubGlobal("fetch", fetchMock);

    render(<CapabilityFamilyControls />);
    fireEvent.click(await screen.findByRole("button", { name: "Stop everything" }));

    await waitFor(() =>
      expect(
        screen.getByText("Your secure session needs to be refreshed. Sign in again, then retry."),
      ).toBeInTheDocument(),
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
