import type { Metadata } from "next";
import AppShell from "@/components/shell/AppShell";
import UserChip from "@/components/shell/UserChip";
import CampaignsContent from "@/components/campaigns/CampaignsContent";

export const metadata: Metadata = { title: "Campaigns — Console" };

export default function CampaignsPage() {
  return (
    <AppShell active="campaigns" topBarAction={<UserChip />}>
      <CampaignsContent />
    </AppShell>
  );
}
