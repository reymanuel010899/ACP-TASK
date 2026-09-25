// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import IntegrationsContent from "./IntegrationsContent";


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

describe("IntegrationsContent", () => {
  it("renders Google OAuth controls inside the Google Workspace grid card", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({ status: "disconnected" }),
        } as Response),
      ),
    );

    render(<IntegrationsContent />);

    const googleCard = await screen.findByRole("region", {
      name: "Google Workspace",
    });
    expect(googleCard).toHaveAttribute("data-layout", "grid");
    expect(
      screen.getByRole("button", { name: "Connect Google" }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("google-brand-icon")).toBeInTheDocument();
    expect(googleCard).toHaveTextContent("Google Workspace is not connected");
    expect(googleCard).not.toHaveTextContent("Connected on May 15, 2024");
  });
});
