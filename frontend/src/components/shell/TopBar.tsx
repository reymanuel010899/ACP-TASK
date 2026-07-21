import type { ReactNode } from "react";
import ThemeToggle from "@/components/shell/ThemeToggle";

/**
 * Shared top bar (Pencil design): global search on the left; theme toggle,
 * notifications and messages on the right. The only part that varies per page
 * is the trailing `action` slot (e.g. the "＋ New Task" button).
 */
export default function TopBar({ action }: { action?: ReactNode }) {
  return (
    <div className="box-border w-full h-[62px] shrink-0 flex flex-row gap-0 p-[14px_20px] justify-between items-center [border-width:0px_0px_1px_0px] [border-style:solid] [border-color:var(--ag2-border)]">
      <div className="box-border w-[410px] shrink-0 h-[35px] flex flex-row gap-[10px] p-[0px_12px] justify-start items-center bg-[var(--ag2-input)] [border:1px_solid_var(--ag2-border)] rounded-[7px]">
        <div className="text-[18px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
          ⌕
        </div>
        <div className="text-[12px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
          Search agents, capabilities, services...
        </div>
      </div>
      <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-[15px] justify-start items-center">
        <ThemeToggle className="text-[20px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]" />
        <div className="text-[19px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
          ♧
        </div>
        <div className="text-[18px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
          ▢
        </div>
        {action}
      </div>
    </div>
  );
}
