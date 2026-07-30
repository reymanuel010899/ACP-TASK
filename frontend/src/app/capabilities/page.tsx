import type { Metadata } from "next";
import AppShell from "@/components/shell/AppShell";
import UserChip from "@/components/shell/UserChip";
import CapabilitiesContent from "@/components/capabilities/CapabilitiesContent";
import CapabilitiesRightPanel from "@/components/capabilities/CapabilitiesRightPanel";

export const metadata: Metadata = {
  title: "Capabilities — Console",
};

export default function CapabilitiesPage() {
  return (
    <AppShell
      active="capabilities"
      topBarAction={<UserChip />}
      rightPanel={<CapabilitiesRightPanel />}
    >
      <CapabilitiesContent />
    </AppShell>
  );
}
