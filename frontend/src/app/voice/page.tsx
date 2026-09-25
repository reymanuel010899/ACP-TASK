import type { Metadata } from "next";
import AppShell from "@/components/shell/AppShell";
import UserChip from "@/components/shell/UserChip";
import RoutingConfiguration from "@/components/voice/RoutingConfiguration";

export const metadata: Metadata = { title: "Voice routing — Console" };

export default function VoicePage() {
  return <AppShell active="voice" topBarAction={<UserChip />}><RoutingConfiguration /></AppShell>;
}
