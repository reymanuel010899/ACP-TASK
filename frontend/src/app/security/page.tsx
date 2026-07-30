import type { Metadata } from "next";
import AppShell from "@/components/shell/AppShell";
import UserChip from "@/components/shell/UserChip";
import SecurityContent from "@/components/security/SecurityContent";
import SecurityRightPanel from "@/components/security/SecurityRightPanel";

export const metadata: Metadata = {
  title: "Security — Console",
};

export default function SecurityPage() {
  return (
    <AppShell
      active="security"
      topBarAction={<UserChip />}
      rightPanel={<SecurityRightPanel />}
    >
      <SecurityContent />
    </AppShell>
  );
}
