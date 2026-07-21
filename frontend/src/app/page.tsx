import AppShell from "@/components/shell/AppShell";
import NewTaskButton from "@/components/shell/NewTaskButton";
import GreetingSection from "@/components/dashboard/GreetingSection";
import StatsRow from "@/components/dashboard/StatsRow";
import AgentsSection from "@/components/dashboard/AgentsSection";
import EcosystemNetwork from "@/components/dashboard/EcosystemNetwork";
import CapabilitiesSection from "@/components/dashboard/CapabilitiesSection";
import RightRail from "@/components/dashboard/RightRail";

export default function Home() {
  return (
    <AppShell
      active="dashboard"
      topBarAction={<NewTaskButton />}
      rightPanel={<RightRail />}
    >
      <div className="box-border w-full [flex:1_1_0] flex flex-col gap-[20px] p-[20px_24px_24px_24px] justify-start items-start">
        <GreetingSection />
        <StatsRow />
        <AgentsSection />
        <EcosystemNetwork />
        <CapabilitiesSection />
      </div>
    </AppShell>
  );
}
