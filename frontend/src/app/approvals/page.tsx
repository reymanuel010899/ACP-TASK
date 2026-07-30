import type { Metadata } from "next";
import AppShell from "@/components/shell/AppShell";
import UserChip from "@/components/shell/UserChip";
import ApprovalsContent from "@/components/approvals/ApprovalsContent";
import ApprovalsRightPanel from "@/components/approvals/ApprovalsRightPanel";

export const metadata: Metadata = {
  title: "Approvals — Console",
};

export default function ApprovalsPage() {
  return (
    <AppShell
      active="approvals"
      topBarAction={<UserChip />}
      rightPanel={<ApprovalsRightPanel />}
    >
      <ApprovalsContent />
    </AppShell>
  );
}
