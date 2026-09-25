// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import Sidebar from "./Sidebar";
import SessionProvider from "@/lib/SessionProvider";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/",
}));

afterEach(cleanup);

describe("Sidebar product maturity labels", () => {
  it("labels frozen vertical applications as Preview without disabling navigation", () => {
    render(
      <SessionProvider>
        <Sidebar active="dashboard" />
      </SessionProvider>,
    );

    expect(screen.getAllByText("Preview")).toHaveLength(3);
    expect(screen.getByRole("link", { name: /Contacts Preview/i })).toHaveAttribute("href", "/contacts");
    expect(screen.getByRole("link", { name: /Campaigns Preview/i })).toHaveAttribute("href", "/campaigns");
    expect(screen.getByRole("link", { name: /Voice routing Preview/i })).toHaveAttribute("href", "/voice");
  });

  it("does not mark the core agent network surfaces as Preview", () => {
    render(
      <SessionProvider>
        <Sidebar active="agents" />
      </SessionProvider>,
    );

    expect(screen.getByRole("link", { name: /Agents$/ })).toHaveAttribute("href", "/agents");
    expect(screen.getByRole("link", { name: /Tasks$/ })).toHaveAttribute("href", "/tasks");
    expect(screen.getByRole("link", { name: /Approvals$/ })).toHaveAttribute("href", "/approvals");
  });
});
