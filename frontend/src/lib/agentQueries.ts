"use client";

// TanStack Query hooks for the runner-backed agents API. One source of truth
// for reads (cached, deduped) and writes (which invalidate ONLY the agents
// cache — never the whole app). Ownership identity rides on mutating calls.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSession } from "@/lib/SessionProvider";

export type RuntimeStatus = "online" | "starting" | "stopped" | "offline" | "error";

export type RunnerAgent = {
  id: string;
  owner_principal_id?: string | null;
  kind: "managed" | "connected";
  trust_tier?: "verified" | "basic";
  name: string;
  description?: string;
  version?: string;
  template: string | null;
  endpoint_url: string | null;
  capabilities: string[];
  list_price: number | null;
  min_price: number | null;
  created_at: string;
  runtime: {
    status: RuntimeStatus;
    pid: number | null;
    port: number | null;
    url: string | null;
    principal_id: string | null;
    error: string | null;
  };
};

export type AgentsPage = {
  agents: RunnerAgent[];
  total: number;
  page: number;
  total_pages: number;
  stats: { total: number; online: number; stopped: number; error: number };
};

export type AgentStats = {
  total: number;
  online: number;
  stopped: number;
  error: number;
  trend: { date: string; count: number }[];
  change_pct: number;
};

// Query keys: everything about agents lives under ["agents"], so a single
// invalidateQueries({ queryKey: agentKeys.all }) refreshes exactly this domain.
export const agentKeys = {
  all: ["agents"] as const,
  list: (page: number, search: string) => ["agents", "list", { page, search }] as const,
  detail: (id: string) => ["agents", "detail", id] as const,
  stats: ["agents", "stats"] as const,
};

/** Fleet-wide dashboard stats: real total + a real per-day cumulative trend.
 * Shares the ["agents"] key prefix, so lifecycle mutations refresh it too. */
export function useAgentStats() {
  return useQuery({
    queryKey: agentKeys.stats,
    queryFn: async (): Promise<AgentStats> => {
      const res = await fetch("/api/agents/stats", { cache: "no-store" });
      if (!res.ok) throw new Error(`Could not load stats (HTTP ${res.status}).`);
      return (await res.json()) as AgentStats;
    },
    staleTime: 30_000,
  });
}

/** The paginated, searchable agents list (server paginates; we cache the page). */
export function useAgentsList(page: number, search: string, opts?: { poll?: boolean }) {
  return useQuery({
    queryKey: agentKeys.list(page, search),
    queryFn: async (): Promise<AgentsPage> => {
      const params = new URLSearchParams({ page: String(page), page_size: "10" });
      if (search) params.set("q", search);
      const res = await fetch(`/api/agents?${params}`, { cache: "no-store" });
      if (!res.ok) {
        const data = (await res.json().catch(() => null)) as { error?: string } | null;
        throw new Error(data?.error ?? `Could not load agents (HTTP ${res.status}).`);
      }
      return (await res.json()) as AgentsPage;
    },
    placeholderData: (prev) => prev, // keep the old page visible while the next loads
    // Poll only while something is transitioning, so the flip to Online is live.
    refetchInterval: opts?.poll ? 2500 : false,
  });
}

/** One agent's definition + live runtime. */
export function useAgentDetail(id: string) {
  return useQuery({
    queryKey: agentKeys.detail(id),
    queryFn: async (): Promise<RunnerAgent> => {
      const res = await fetch(`/api/agents/${encodeURIComponent(id)}`, { cache: "no-store" });
      if (res.status === 404) throw new Error("This agent no longer exists.");
      if (!res.ok) throw new Error(`Could not load this agent (HTTP ${res.status}).`);
      return (await res.json()) as RunnerAgent;
    },
  });
}

/** Lifecycle + disconnect mutations. Each invalidates ONLY the agents cache. */
export function useAgentActions() {
  const qc = useQueryClient();
  const { session } = useSession();
  const ownerHeaders = (): Record<string, string> =>
    session ? { "X-Owner-Principal": session.principalId } : {};

  const invalidate = () => qc.invalidateQueries({ queryKey: agentKeys.all });

  const lifecycle = useMutation({
    mutationFn: async ({ id, action }: { id: string; action: "start" | "stop" | "restart" }) => {
      const res = await fetch(`/api/agents/${encodeURIComponent(id)}/${action}`, {
        method: "POST",
        headers: ownerHeaders(),
      });
      if (!res.ok) {
        const data = (await res.json().catch(() => null)) as { error?: string } | null;
        throw new Error(data?.error ?? `Action failed (HTTP ${res.status}).`);
      }
      return res.json();
    },
    // Optimistic: flip the row's status instantly on Start so the UI reacts
    // without waiting for a refetch. Rolled back if the server rejects.
    onMutate: async ({ id, action }) => {
      if (action !== "start") return {};
      await qc.cancelQueries({ queryKey: agentKeys.all });
      const snapshots = qc.getQueriesData<AgentsPage>({ queryKey: agentKeys.all });
      for (const [key, data] of snapshots) {
        if (!data) continue;
        qc.setQueryData<AgentsPage>(key, {
          ...data,
          agents: data.agents.map((a) =>
            a.id === id ? { ...a, runtime: { ...a.runtime, status: "starting" } } : a,
          ),
        });
      }
      return { snapshots };
    },
    onError: (_e, _v, ctx) => {
      for (const [key, data] of ctx?.snapshots ?? []) qc.setQueryData(key, data);
    },
    onSettled: invalidate,
  });

  const disconnect = useMutation({
    mutationFn: async (id: string) => {
      const res = await fetch(`/api/agents/${encodeURIComponent(id)}`, {
        method: "DELETE",
        headers: ownerHeaders(),
      });
      if (!res.ok) {
        const data = (await res.json().catch(() => null)) as { error?: string } | null;
        throw new Error(data?.error ?? `Disconnect failed (HTTP ${res.status}).`);
      }
      return res.json();
    },
    onSettled: invalidate,
  });

  // Take ownership of an unclaimed (legacy) agent.
  const claim = useMutation({
    mutationFn: async (id: string) => {
      const res = await fetch(`/api/agents/${encodeURIComponent(id)}/claim`, {
        method: "POST",
        headers: ownerHeaders(),
      });
      if (!res.ok) {
        const data = (await res.json().catch(() => null)) as { error?: string } | null;
        throw new Error(data?.error ?? `Claim failed (HTTP ${res.status}).`);
      }
      return res.json();
    },
    onSettled: invalidate,
  });

  return { lifecycle, disconnect, claim, invalidate };
}
