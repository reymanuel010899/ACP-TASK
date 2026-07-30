import type { Metadata } from "next";
import AppShell from "@/components/shell/AppShell";
import AgentDetailContent from "@/components/agents/AgentDetailContent";
import AgentRightPanel from "@/components/agents/AgentRightPanel";

export const metadata: Metadata = {
  title: "Agent — Console",
};

export default async function AgentDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <AppShell active="agents" rightPanel={<AgentRightPanel />}>
      <AgentDetailContent agentId={id} />
    </AppShell>
  );
}
