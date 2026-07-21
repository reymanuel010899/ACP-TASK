/** Avatar + user info block used in the shared top bar (from the Organizations design). */
export default function UserChip() {
  return (
    <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-[10px] justify-start items-center">
      <div className="box-border w-[32px] shrink-0 h-[32px] bg-[#D99975] rounded-full"></div>
      <div className="box-border w-fit shrink-0 h-fit flex flex-col gap-[2px] justify-start items-start">
        <div className="text-[11px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
          Rey Ferreras
        </div>
        <div className="text-[9px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
          Enterprise Plan
        </div>
      </div>
    </div>
  );
}
