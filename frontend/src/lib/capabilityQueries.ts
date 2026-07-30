"use client";

// TanStack Query hook for the registry's enriched capability catalog — the
// real "what can agents in this ecosystem do" list, derived from agent cards.

import { useQuery } from "@tanstack/react-query";

export type CatalogCapability = {
  capability_id: string;
  name: string | null;
  description: string | null;
  tags: string[];
  agents: { principal_id: string; name: string | null; description: string | null }[];
};

export function useCapabilities() {
  return useQuery({
    queryKey: ["capabilities"],
    queryFn: async (): Promise<CatalogCapability[]> => {
      const res = await fetch("/api/capabilities", { cache: "no-store" });
      if (!res.ok) throw new Error(`Could not load capabilities (HTTP ${res.status}).`);
      const data = (await res.json()) as { capabilities?: CatalogCapability[] };
      return data.capabilities ?? [];
    },
    staleTime: 60_000,
  });
}
