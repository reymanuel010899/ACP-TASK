export default function GreetingSection() {
  return (
    <div
      className="box-border w-full h-fit shrink-0 flex flex-col gap-[4px] justify-start items-start"
    >
      <div
        className="text-[28px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]"
      >
        Good morning, Rey 👋
      </div>
      <div
        className="text-[14px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
      >
        Here&apos;s what&apos;s happening in your ecosystem today.
      </div>
    </div>
  );
}
