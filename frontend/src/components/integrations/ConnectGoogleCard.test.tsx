// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import ConnectGoogleCard from "./ConnectGoogleCard";


beforeEach(() => {
  window.sessionStorage.clear();
  window.sessionStorage.setItem("tessera-csrf", "csrf-test");
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

describe("ConnectGoogleCard", () => {
  it("loads disconnected status from the BFF and starts a consent flow", async () => {
    const redirect = vi.fn();
    const fetchMock = vi
      .fn()
      .mockImplementationOnce(() => response({ status: "disconnected" }))
      .mockImplementationOnce(() =>
        response({ authorization_url: "https://accounts.google.test/consent" }),
      );
    vi.stubGlobal("fetch", fetchMock);
    render(<ConnectGoogleCard redirect={redirect} />);

    const connect = await screen.findByRole("button", { name: "Connect Google" });
    fireEvent.click(connect);

    expect(await screen.findByText("Redirecting to Google…")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/integrations/google/connect",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({ "X-CSRF-Token": "csrf-test" }),
      }),
    );
    expect(redirect).toHaveBeenCalledWith("https://accounts.google.test/consent");
  });

  it("renders denied and callback-failed recovery states from the safe callback code", async () => {
    vi.stubGlobal("fetch", vi.fn(() => response({ status: "disconnected" })));
    window.history.replaceState({}, "", "/integrations?google=denied");
    const first = render(<ConnectGoogleCard redirect={vi.fn()} />);
    expect(await screen.findByText(/Google access was denied/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();

    first.unmount();
    window.history.replaceState({}, "", "/integrations?google=callback-failed");
    render(<ConnectGoogleCard redirect={vi.fn()} />);
    expect(await screen.findByText(/could not finish connecting/i)).toBeInTheDocument();
  });

  it("shows connected capabilities and supports reconnect", async () => {
    const redirect = vi.fn();
    const fetchMock = vi
      .fn()
      .mockImplementationOnce(() =>
        response({
          status: "connected",
          enabled_capabilities: ["calendar.create", "gmail.send"],
        }),
      )
      .mockImplementationOnce(() =>
        response({ authorization_url: "https://accounts.google.test/reconnect" }),
      );
    vi.stubGlobal("fetch", fetchMock);
    render(<ConnectGoogleCard redirect={redirect} />);

    expect(await screen.findByText("Google Workspace is connected")).toBeInTheDocument();
    expect(screen.getByText("Calendar events")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reconnect Google" }));
    expect(await screen.findByText("Starting a fresh Google consent flow…")).toBeInTheDocument();
    expect(redirect).toHaveBeenCalled();
  });

  it("keeps pending revocation visible and offers retry after provider failure", async () => {
    const fetchMock = vi
      .fn()
      .mockImplementationOnce(() =>
        response({ status: "connected", enabled_capabilities: ["calendar.create"] }),
      )
      .mockImplementationOnce(() => response({ status: "pending_revocation" }, 202))
      .mockImplementationOnce(() => response({ status: "disconnected" }));
    vi.stubGlobal("fetch", fetchMock);
    render(<ConnectGoogleCard redirect={vi.fn()} />);

    fireEvent.click(await screen.findByRole("button", { name: "Disconnect Google" }));
    expect(await screen.findByText(/Revocation is pending/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry revocation" })).toHaveFocus();

    fireEvent.click(screen.getByRole("button", { name: "Retry revocation" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Connect Google" })).toBeInTheDocument(),
    );
  });

  it("does not claim access is blocked when disconnect status is unknown", async () => {
    const fetchMock = vi
      .fn()
      .mockImplementationOnce(() =>
        response({ status: "connected", enabled_capabilities: ["calendar.create"] }),
      )
      .mockImplementationOnce(() => Promise.reject(new Error("offline")))
      .mockImplementationOnce(() =>
        response({ status: "connected", enabled_capabilities: ["calendar.create"] }),
      );
    vi.stubGlobal("fetch", fetchMock);
    render(<ConnectGoogleCard redirect={vi.fn()} />);

    fireEvent.click(await screen.findByRole("button", { name: "Disconnect Google" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      /could not confirm whether Google access was blocked/i,
    );
    expect(screen.queryByText(/access is already blocked/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Check status" }));
    expect(await screen.findByText("Google Workspace is connected")).toBeInTheDocument();
  });

  it("announces failures and recovers when status loading fails", async () => {
    const fetchMock = vi
      .fn()
      .mockImplementationOnce(() => Promise.reject(new Error("offline")))
      .mockImplementationOnce(() => response({ status: "disconnected" }));
    vi.stubGlobal("fetch", fetchMock);
    render(<ConnectGoogleCard redirect={vi.fn()} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(/could not load/i);
    expect(screen.getByRole("button", { name: "Connect Google" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Retry status" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Connect Google" })).toBeEnabled(),
    );
  });
});
