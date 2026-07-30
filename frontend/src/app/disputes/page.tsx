import type { Metadata } from "next";
import AppShell from "@/components/shell/AppShell";
import UserChip from "@/components/shell/UserChip";
import DisputesContent from "@/components/disputes/DisputesContent";
import DisputesRightPanel from "@/components/disputes/DisputesRightPanel";

export const metadata: Metadata = {
  title: "Disputes — Console",
};

export default function DisputesPage() {
  return (
    <AppShell
      active="disputes"
      topBarAction={<UserChip />}
      rightPanel={<DisputesRightPanel />}
    >
      <DisputesContent />
    </AppShell>
  );
}
