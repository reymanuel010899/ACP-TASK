import type { Metadata } from "next";
import AppShell from "@/components/shell/AppShell";
import UserChip from "@/components/shell/UserChip";
import NegotiationsContent from "@/components/negotiations/NegotiationsContent";
import NegotiationsRightPanel from "@/components/negotiations/NegotiationsRightPanel";

export const metadata: Metadata = {
  title: "Negotiations — Console",
};

export default function NegotiationsPage() {
  return (
    <AppShell
      active="negotiations"
      topBarAction={<UserChip />}
      rightPanel={<NegotiationsRightPanel />}
    >
      <NegotiationsContent />
    </AppShell>
  );
}
