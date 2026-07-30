import type { Metadata } from "next";
import AppShell from "@/components/shell/AppShell";
import AgentListContent from "@/components/agents/AgentListContent";

export const metadata: Metadata = {
  title: "Agents — Console",
};

export default function AgentsPage() {
  return (
    <AppShell active="agents">
      <AgentListContent />
    </AppShell>
  );
}
