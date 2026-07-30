import type { Metadata } from "next";
import AppShell from "@/components/shell/AppShell";
import UserChip from "@/components/shell/UserChip";
import ContractsContent from "@/components/contracts/ContractsContent";
import ContractsRightPanel from "@/components/contracts/ContractsRightPanel";

export const metadata: Metadata = {
  title: "Contracts — Console",
};

/** Purple "＋ New Contract" action shown in the top bar (Contracts design). */
function NewContractButton() {
  return (
    <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-[8px] p-[10px_14px] justify-start items-center bg-[#6D3CE0] rounded-[6px]">
      <div className="text-[12px]/[normal] box-border text-[#FFFFFF] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
        ＋ New Contract
      </div>
    </div>
  );
}

export default function ContractsPage() {
  return (
    <AppShell
      active="contracts"
      topBarAction={
        <>
          <NewContractButton />
          <UserChip />
        </>
      }
      rightPanel={<ContractsRightPanel />}
    >
      <ContractsContent />
    </AppShell>
  );
}
