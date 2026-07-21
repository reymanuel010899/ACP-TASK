/** Purple "＋ New Task ⌄" action button used in the shared top bar. */
export default function NewTaskButton() {
  return (
    <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-[8px] p-[10px_14px] justify-start items-start bg-[#5D20DC] rounded-[6px]">
      <div className="text-[12px]/[normal] box-border text-[#F4F2FF] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
        ＋ New Task ⌄
      </div>
    </div>
  );
}
