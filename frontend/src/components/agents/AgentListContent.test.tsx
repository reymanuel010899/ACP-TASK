// @vitest-environment jsdom
//
// Agents listing (plan 2026-07-23-002, U6): runner-backed list with REAL status
// and lifecycle actions. Only fetch is stubbed (routed by URL).
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render as rtlRender, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement } from "react";

import AgentListContent from "./AgentListContent";

// The list is now server-state via TanStack Query; every render needs a
// provider. A fresh client per render keeps tests isolated (no cache bleed),
// and retry is off so a rejected fetch surfaces immediately.
function render(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return rtlRender(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: pushMock }) }));
// The component reads the signed-in user (ownership); tests run outside the
// real SessionProvider, so serve a stable principal here.
vi.mock("@/lib/SessionProvider", () => ({
  useSession: () => ({ session: { principalId: "user-test-principal" }, isHydrated: true }),
}));

function agent(over: Record<string, unknown> = {}) {
  return {
    id: "agt_1",
    kind: "managed",
    // The mocked session owns this agent, so owner-only actions render.
    owner_principal_id: "user-test-principal",
    name: "DevOps Agent",
    version: "0.1.0",
    template: "terraform-provider",
    endpoint_url: null,
    capabilities: ["terraform.generate"],
    list_price: 6,
    min_price: 3,
    created_at: "2026-07-23T10:00:00Z",
    runtime: { status: "stopped", pid: null, port: null, url: null, principal_id: null, error: null },
    ...over,
  };
}

let calls: string[] = [];

function routedFetch(listBody: unknown) {
  return vi.fn().mockImplementation((url: string, init?: RequestInit) => {
    calls.push(`${init?.method ?? "GET"} ${url}`);
    // The list is now SERVER-paginated: the component calls
    // /api/agents?page=N&page_size=10[&q=...] and consumes the paginated
    // contract (agents/total/page/total_pages/stats). Serve it here,
    // deriving totals/stats from the agents the test provided.
    if (url.split("?")[0] === "/api/agents" && (!init || init.method === undefined)) {
      const agents =
        ((listBody as { agents?: Array<{ runtime?: { status?: string } }> }).agents) ?? [];
      const count = (s: string) => agents.filter((a) => a.runtime?.status === s).length;
      return Promise.resolve({
        ok: true,
        json: async () => ({
          agents,
          total: agents.length,
          page: 1,
          page_size: 10,
          total_pages: 1,
          stats: {
            total: agents.length,
            online: count("online"),
            stopped: count("stopped"),
            error: count("error"),
          },
        }),
      });
    }
    return Promise.resolve({ ok: true, json: async () => ({ id: "agt_1", runtime: {} }) });
  });
}

beforeEach(() => {
  calls = [];
  pushMock.mockReset();
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("AgentListContent (runner-backed)", () => {
  it("renders agents with real status", async () => {
    vi.stubGlobal("fetch", routedFetch({ agents: [agent()] }));
    render(<AgentListContent />);
    await waitFor(() => expect(screen.getByText("DevOps Agent")).toBeInTheDocument());
    // "Stopped" appears in the stat card and the row status.
    expect(screen.getAllByText("Stopped").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Total Agents")).toBeInTheDocument();
  });

  it("shows Online status and a Stop action for a running agent", async () => {
    vi.stubGlobal(
      "fetch",
      routedFetch({
        agents: [agent({ runtime: { status: "online", pid: 5, port: 51000, url: "http://127.0.0.1:51000", principal_id: "atp:principal:x", error: null } })],
      }),
    );
    render(<AgentListContent />);
    // Wait for the row itself (its Stop action) — "Online" alone is ambiguous
    // with the always-present "Online" stat-card label.
    expect(await screen.findByRole("button", { name: "Stop" })).toBeInTheDocument();
  });

  it("Start posts to the runner start endpoint", async () => {
    vi.stubGlobal("fetch", routedFetch({ agents: [agent()] }));
    render(<AgentListContent />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Start" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Start" }));
    await waitFor(() => expect(calls).toContain("POST /api/agents/agt_1/start"));
  });

  it("a connected (BYO) agent shows its endpoint and Disconnect, not Start", async () => {
    vi.stubGlobal(
      "fetch",
      routedFetch({
        agents: [
          agent({
            kind: "connected",
            name: "External Bot",
            template: null,
            endpoint_url: "https://agents.example.com/bot",
            runtime: { status: "online", pid: null, port: null, url: "https://agents.example.com/bot", principal_id: "ext-1", error: null },
          }),
        ],
      }),
    );
    render(<AgentListContent />);
    await waitFor(() => expect(screen.getByText("External Bot")).toBeInTheDocument());
    expect(screen.getByText("Connected")).toBeInTheDocument();
    expect(screen.getByText("https://agents.example.com/bot")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Disconnect" })).toBeInTheDocument();
    // externally hosted -> the console never offers to launch it
    expect(screen.queryByRole("button", { name: "Start" })).not.toBeInTheDocument();
  });

  it("clicking a row opens that agent's detail page", async () => {
    vi.stubGlobal("fetch", routedFetch({ agents: [agent()] }));
    render(<AgentListContent />);
    await waitFor(() => expect(screen.getByText("DevOps Agent")).toBeInTheDocument());
    fireEvent.click(screen.getByText("DevOps Agent"));
    expect(pushMock).toHaveBeenCalledWith("/agents/agt_1");
  });

  it("a row action does NOT navigate to the detail page", async () => {
    vi.stubGlobal("fetch", routedFetch({ agents: [agent()] }));
    render(<AgentListContent />);
    await waitFor(() => expect(screen.getByRole("button", { name: "Start" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Start" }));
    await waitFor(() => expect(calls).toContain("POST /api/agents/agt_1/start"));
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("empty state offers to create the first agent", async () => {
    vi.stubGlobal("fetch", routedFetch({ agents: [] }));
    render(<AgentListContent />);
    await waitFor(() => expect(screen.getByText("No agents yet")).toBeInTheDocument());
  });

  it("shows an error state when the runner is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("boom")));
    render(<AgentListContent />);
    await waitFor(() => expect(screen.getByText(/Could not reach the runner/)).toBeInTheDocument());
  });
});
