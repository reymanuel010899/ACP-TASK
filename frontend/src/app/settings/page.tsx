import type { Metadata } from "next";
import AppShell from "@/components/shell/AppShell";
import UserChip from "@/components/shell/UserChip";
import SettingsContent from "@/components/settings/SettingsContent";
import SettingsRightPanel from "@/components/settings/SettingsRightPanel";

export const metadata: Metadata = {
  title: "Settings — Console",
};

export default function SettingsPage() {
  return (
    <AppShell
      active="settings"
      topBarAction={<UserChip />}
      rightPanel={<SettingsRightPanel />}
    >
      <SettingsContent />
    </AppShell>
  );
}
