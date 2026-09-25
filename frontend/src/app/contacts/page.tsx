import type { Metadata } from "next";
import AppShell from "@/components/shell/AppShell";
import UserChip from "@/components/shell/UserChip";
import ContactsContent from "@/components/contacts/ContactsContent";

export const metadata: Metadata = {
  title: "Contacts — Console",
};

export default function ContactsPage() {
  return (
    <AppShell active="contacts" topBarAction={<UserChip />}>
      <ContactsContent />
    </AppShell>
  );
}
