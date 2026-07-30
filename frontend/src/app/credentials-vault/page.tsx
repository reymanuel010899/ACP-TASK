import type { Metadata } from "next";
import AppShell from "@/components/shell/AppShell";
import UserChip from "@/components/shell/UserChip";
import VaultContent from "@/components/vault/VaultContent";
import VaultRightPanel from "@/components/vault/VaultRightPanel";

export const metadata: Metadata = {
  title: "Credentials Vault — Console",
};

export default function CredentialsVaultPage() {
  return (
    <AppShell
      active="credentials-vault"
      topBarAction={<UserChip />}
      rightPanel={<VaultRightPanel />}
    >
      <VaultContent />
    </AppShell>
  );
}
