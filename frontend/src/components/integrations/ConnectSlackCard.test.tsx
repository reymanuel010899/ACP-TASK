// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import ConnectSlackCard from "./ConnectSlackCard";


beforeEach(() => {
  window.sessionStorage.clear(); window.localStorage.clear();
  window.localStorage.setItem("tessera-csrf", "csrf-test");
  window.history.replaceState({}, "", "/integrations");
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

describe("ConnectSlackCard", () => {
  it("renders two workspaces separately and disconnects only the selected one", async () => {
    const fetchMock = vi.fn()
      .mockImplementationOnce(() => response({ provider: "slack", connections: [
        { connection_id: "conn-a", team_id: "T-A", team_name: "Acme", status: "connected", enabled_capabilities: ["slack.message.send"], owner: true },
        { connection_id: "conn-b", team_id: "T-B", team_name: "Beta", status: "connected", enabled_capabilities: ["slack.channels.list"], owner: true },
      ] }))
      .mockImplementationOnce(() => response({ status: "disconnected", connection_id: "conn-b" }));
    vi.stubGlobal("fetch", fetchMock);

    render(<ConnectSlackCard redirect={vi.fn()} />);
    const beta = await screen.findByRole("group", { name: "Beta workspace" });
    fireEvent.click(within(beta).getByRole("button", { name: "Disconnect Beta" }));

    expect(await screen.findByText("Beta was disconnected.")).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Acme workspace" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Beta workspace" })).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/integrations/slack/conn-b",
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("offers one upgrade per missing family and asks only for that family", async () => {
    const redirect = vi.fn();
    const fetchMock = vi.fn()
      .mockImplementationOnce(() => response({ provider: "slack", connections: [
        {
          connection_id: "conn-a", team_id: "T-A", team_name: "Acme",
          status: "connected", enabled_capabilities: ["slack.message.send"],
          owner: true,
          missing_families: [
            { family: "slack_pins", missing_scopes: ["pins:write"], operations: ["slack.message.pin"] },
            { family: "slack_direct_messages", missing_scopes: ["im:write"], operations: ["slack.direct_message.send"] },
          ],
        },
      ] }))
      .mockImplementationOnce(() => response({ authorization_url: "https://slack.test/consent" }));
    vi.stubGlobal("fetch", fetchMock);

    render(<ConnectSlackCard redirect={redirect} />);

    // Each prompt says what the grant buys and what it costs.
    expect(await screen.findByText("To pin and unpin messages, Tessera needs pins:write")).toBeInTheDocument();
    expect(screen.getByText("To send direct messages, Tessera needs im:write")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Allow pin and unpin messages" }));

    await waitFor(() => expect(redirect).toHaveBeenCalledWith("https://slack.test/consent"));
    const body = JSON.parse(fetchMock.mock.calls[1][1].body as string);
    expect(body.target_connection_id).toBe("conn-a");
    expect(body.families).toEqual(["slack_pins"]);
    // Asking for pins must not drag every other capability along.
    expect(body.capabilities).toBeUndefined();
  });

  it("shows no upgrade prompts when nothing is missing", async () => {
    const fetchMock = vi.fn().mockImplementationOnce(() => response({
      provider: "slack", connections: [
        {
          connection_id: "conn-a", team_id: "T-A", team_name: "Acme",
          status: "connected", enabled_capabilities: ["slack.message.send"],
          owner: true, missing_families: [],
        },
      ],
    }));
    vi.stubGlobal("fetch", fetchMock);

    render(<ConnectSlackCard redirect={vi.fn()} />);

    await screen.findByRole("group", { name: "Acme workspace" });
    expect(screen.queryByText(/Tessera needs/)).not.toBeInTheDocument();
  });

  it("shows a tenant-authorized workspace to members without lifecycle controls", async () => {
    vi.stubGlobal("fetch", vi.fn(() => response({ provider: "slack", connections: [
      { connection_id: "conn-a", team_id: "T-A", team_name: "Acme", status: "connected", enabled_capabilities: ["slack.channels.list"], owner: false },
    ] })));

    render(<ConnectSlackCard redirect={vi.fn()} />);
    const workspace = await screen.findByRole("group", { name: "Acme workspace" });
    expect(workspace).toBeInTheDocument();
    expect(within(workspace).queryByRole("button", { name: /Upgrade/ })).not.toBeInTheDocument();
    expect(within(workspace).queryByRole("button", { name: /Disconnect/ })).not.toBeInTheDocument();
  });
});
