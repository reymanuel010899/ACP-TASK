import type { ReactNode } from "react";
import Sidebar, { type NavKey } from "@/components/shell/Sidebar";
import TopBar from "@/components/shell/TopBar";

/**
 * Shared page frame: full-viewport row with the app sidebar, a scrollable
 * center column (shared top bar + content), and an optional right panel.
 * `topBarAction` is the only part of the top bar that varies per page.
 */
export default function AppShell({
  active,
  topBarAction,
  children,
  rightPanel,
}: {
  active: NavKey;
  topBarAction?: ReactNode;
  children: ReactNode;
  rightPanel?: ReactNode;
}) {
  return (
    <div className="box-border w-full h-screen flex flex-row gap-0 justify-start items-start bg-[var(--ag-bg)] overflow-hidden">
      <Sidebar active={active} />
      <div className="box-border [flex:1_1_0] min-w-0 h-full overflow-y-auto flex flex-col gap-0 justify-start items-start">
        <TopBar action={topBarAction} />
        {children}
      </div>
      {rightPanel}
    </div>
  );
}
