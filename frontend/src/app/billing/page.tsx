import type { Metadata } from "next";
import AppShell from "@/components/shell/AppShell";
import UserChip from "@/components/shell/UserChip";
import BillingContent from "@/components/billing/BillingContent";
import BillingRightPanel from "@/components/billing/BillingRightPanel";

export const metadata: Metadata = {
  title: "Billing — Console",
};

export default function BillingPage() {
  return (
    <AppShell
      active="billing"
      topBarAction={<UserChip />}
      rightPanel={<BillingRightPanel />}
    >
      <BillingContent />
    </AppShell>
  );
}
