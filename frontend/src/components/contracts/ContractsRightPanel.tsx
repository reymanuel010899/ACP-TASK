/**
 * Contracts — right rail (Pencil "Contracts Right Panel" design): status
 * overview donut, expiring-soon list, and recent activity. Same `--ag-*`
 * token conventions as ContractsContent.
 */

import DonutChart, { type DonutSegment } from "@/components/charts/DonutChart";

const LEGEND: (DonutSegment & { label: string })[] = [
  { label: "Active 68 (53%)", value: 68, color: "#22C55E" },
  { label: "Pending 12 (9%)", value: 12, color: "#F59E0B" },
  { label: "Expired 18 (14%)", value: 18, color: "#EF4444" },
  { label: "Completed 30 (24%)", value: 30, color: "#8B8CC7" },
];

const EXPIRING: { name: string; meta: string; deadline: string }[] = [
  { name: "AI Analytics License", meta: "C-882 · May 19, 2024", deadline: "in 5 days" },
  { name: "Cloud Infrastructure", meta: "C-881 · May 19, 2024", deadline: "in 17 days" },
  { name: "Software Subscription", meta: "C-878 · May 19, 2024", deadline: "in 18 days" },
];

const ACTIVITY: { main: string; by: string; time: string; dot: string }[] = [
  { main: "Contract C-883 signed", by: "by Michael Chen", time: "2h ago", dot: "#22C55E" },
  { main: "Contract C-882 pending signature", by: "by Ana Martinez", time: "5h ago", dot: "#F59E0B" },
  { main: "Contract C-879 updated", by: "by Sofia Rodriguez", time: "1d ago", dot: "#3B82F6" },
  { main: "Contract C-877 expired", by: "by System", time: "2d ago", dot: "#EF4444" },
];

const CARD_TITLE =
  "text-[14px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]";

export default function ContractsRightPanel() {
  return (
    <div className="box-border w-[320px] shrink-0 h-full flex flex-col gap-[12px] p-[14px] justify-start items-start bg-[var(--ag-right-bg)] [border-width:0px_0px_0px_1px] [border-style:solid] [border-color:var(--ag-divider)] overflow-y-auto">
      {/* Overview */}
      <div className="box-border w-full h-[250px] shrink-0 flex flex-col gap-[14px] p-[14px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]">
        <div className="text-[15px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
          Contracts Overview
        </div>
        <div className="box-border w-full h-[102px] shrink-0 flex flex-row gap-[14px] justify-start items-center">
          <DonutChart data={LEGEND} size={100} thickness={20} />
          <div className="box-border w-fit shrink-0 h-full flex flex-col gap-0 justify-between items-start">
            {LEGEND.map((l) => (
              <div key={l.label} className="box-border w-fit h-fit shrink-0 flex flex-row gap-[7px] justify-start items-center">
                <div className="box-border w-[8px] shrink-0 h-[8px] rounded-full" style={{ backgroundColor: l.color }}></div>
                <div className="text-[10px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                  {l.label}
                </div>
              </div>
            ))}
          </div>
        </div>
        <div className="box-border w-full h-[38px] shrink-0 flex flex-row gap-0 justify-center items-center bg-[#4C179E] rounded-[5px]">
          <div className="text-[11px]/[normal] box-border text-[#FFFFFF] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
            View Full Report
          </div>
        </div>
      </div>

      {/* Expiring soon */}
      <div className="box-border w-full h-[260px] shrink-0 flex flex-col gap-[12px] p-[14px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]">
        <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
          <div className={CARD_TITLE}>Expiring Soon</div>
          <div className="text-[10px]/[normal] box-border text-[#A78BFA] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            View all
          </div>
        </div>
        {EXPIRING.map((e) => (
          <div key={e.name} className="box-border w-full h-[43px] shrink-0 flex flex-row gap-[9px] justify-start items-center">
            <div className="box-border w-[28px] shrink-0 h-[28px] bg-[#1E1B4B] rounded-[6px]"></div>
            <div className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[3px] justify-start items-start">
              <div className="text-[10px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
                {e.name}
              </div>
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                {e.meta}
              </div>
            </div>
            <div className="text-[9px]/[normal] box-border text-[#F59E0B] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
              {e.deadline}
            </div>
          </div>
        ))}
      </div>

      {/* Recent activity */}
      <div className="box-border w-full [flex:1_1_0] flex flex-col gap-[12px] p-[14px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]">
        <div className={CARD_TITLE}>Recent Activity</div>
        {ACTIVITY.map((a) => (
          <div key={a.main} className="box-border w-full h-fit shrink-0 flex flex-row gap-[9px] justify-start items-center">
            <div className="box-border w-[18px] shrink-0 h-[18px] rounded-full" style={{ backgroundColor: a.dot }}></div>
            <div className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[3px] justify-start items-start">
              <div className="text-[10px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
                {a.main}
              </div>
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                {a.by}
              </div>
            </div>
            <div className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
              {a.time}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
