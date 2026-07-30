import type { Metadata } from "next";
import AppShell from "@/components/shell/AppShell";
import UserChip from "@/components/shell/UserChip";
import EvidenceContent from "@/components/evidence/EvidenceContent";
import EvidenceRightPanel from "@/components/evidence/EvidenceRightPanel";

export const metadata: Metadata = {
  title: "Evidence & Audit — Console",
};

export default function EvidenceAuditPage() {
  return (
    <AppShell
      active="evidence-audit"
      topBarAction={<UserChip />}
      rightPanel={<EvidenceRightPanel />}
    >
      <EvidenceContent />
    </AppShell>
  );
}
