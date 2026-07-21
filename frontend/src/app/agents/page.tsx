import type { Metadata } from "next";
import AppShell from "@/components/shell/AppShell";
import AgentContent from "@/components/agents/AgentContent";
import AgentRightPanel from "@/components/agents/AgentRightPanel";

export const metadata: Metadata = {
  title: "Agents — Agentio",
};

export default function AgentsPage() {
  return (
    <AppShell active="agents" rightPanel={<AgentRightPanel />}>
      <AgentContent />
    </AppShell>
  );
}
