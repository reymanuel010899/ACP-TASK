import type { Metadata } from "next";
import AppShell from "@/components/shell/AppShell";
import NewTaskButton from "@/components/shell/NewTaskButton";
import MarketplaceContent from "@/components/marketplace/MarketplaceContent";
import MarketplaceFilters from "@/components/marketplace/MarketplaceFilters";

export const metadata: Metadata = {
  title: "Marketplace — Console",
};

export default function MarketplacePage() {
  return (
    <AppShell
      active="marketplace"
      topBarAction={<NewTaskButton />}
      rightPanel={<MarketplaceFilters />}
    >
      <MarketplaceContent />
    </AppShell>
  );
}
