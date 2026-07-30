import type { Metadata } from "next";
import AppShell from "@/components/shell/AppShell";
import UserChip from "@/components/shell/UserChip";
import IntegrationsContent from "@/components/integrations/IntegrationsContent";
import IntegrationsRightPanel from "@/components/integrations/IntegrationsRightPanel";

export const metadata: Metadata = {
  title: "Integrations — Console",
};

export default function IntegrationsPage() {
  return (
    <AppShell
      active="integrations"
      topBarAction={<UserChip />}
      rightPanel={<IntegrationsRightPanel />}
    >
      <IntegrationsContent />
    </AppShell>
  );
}
