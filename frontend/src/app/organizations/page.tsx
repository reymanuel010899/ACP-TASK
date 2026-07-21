import type { Metadata } from "next";
import AppShell from "@/components/shell/AppShell";
import UserChip from "@/components/shell/UserChip";
import OrgContent from "@/components/organizations/OrgContent";
import OrgRightPanel from "@/components/organizations/OrgRightPanel";

export const metadata: Metadata = {
  title: "Organizations — Agentio",
};

export default function OrganizationsPage() {
  return (
    <AppShell
      active="organizations"
      topBarAction={<UserChip />}
      rightPanel={<OrgRightPanel />}
    >
      <OrgContent />
    </AppShell>
  );
}
