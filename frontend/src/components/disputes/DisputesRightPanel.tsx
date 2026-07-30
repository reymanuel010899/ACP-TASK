/**
 * Disputes — right rail (Pencil "Disputes Right" design): resolution-rate gauge
 * (canvas), escalated disputes, and quick actions. Dashboard `--ag-*` tokens
 * for structure; accent hues literal.
 */

import DonutChart, { type DonutSegment } from "@/components/charts/DonutChart";

const RESOLUTION: DonutSegment[] = [
  { label: "Resolved", value: 72, color: "#22C55E" },
  { label: "In Progress", value: 28, color: "#2563EB" },
];

const ESCALATED: { id: string; sub: string; time: string; tag: string; color: string }[] = [
  { id: "DSP-2024-048", sub: "Payment not received for milestone 2", time: "2h ago", tag: "High", color: "#EF4444" },
  { id: "DSP-2024-045", sub: "Service quality below agreement", time: "5h ago", tag: "High", color: "#EF4444" },
  { id: "DSP-2024-039", sub: "Contract terms violation", time: "1d ago", tag: "Medium", color: "#F59E0B" },
];

const ACTIONS: { title: string; sub: string; color: string }[] = [
  { title: "Create Dispute", sub: "File a new dispute", color: "#6D3CE0" },
  { title: "Upload Evidence", sub: "Add evidence to a dispute", color: "#2563EB" },
  { title: "View Dispute Policy", sub: "Review dispute resolution policy", color: "#10B981" },
];

const TITLE =
  "text-[14px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]";

export default function DisputesRightPanel() {
  return (
    <div className="box-border w-[270px] shrink-0 h-full flex flex-col gap-[12px] p-[14px] justify-start items-start bg-[var(--ag-right-bg)] [border-width:0px_0px_0px_1px] [border-style:solid] [border-color:var(--ag-divider)] overflow-y-auto">
      {/* Resolution overview */}
      <div className="box-border w-full h-[260px] shrink-0 flex flex-col gap-[12px] p-[14px] justify-start items-center bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]">
        <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-start items-center">
          <div className={TITLE}>Dispute Resolution Overview</div>
        </div>
        <DonutChart data={RESOLUTION} size={124} thickness={16}>
          <div className="text-[22px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-center [white-space:nowrap]">
            72%
          </div>
        </DonutChart>
        <div className="box-border w-full h-fit shrink-0 flex flex-col gap-[2px] justify-start items-start">
          <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
            <div className="text-[10px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
              Average Resolution Time
            </div>
            <div className="text-[10px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
              6.4 days
            </div>
          </div>
          <div className="text-[9px]/[normal] box-border text-[#22C55E] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            ↓ 1.2 days vs last 30 days
          </div>
        </div>
      </div>

      {/* Escalated disputes */}
      <div className="box-border w-full h-[254px] shrink-0 flex flex-col gap-[10px] p-[14px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]">
        <div className={TITLE}>Escalated Disputes</div>
        {ESCALATED.map((e) => (
          <div key={e.id} className="box-border w-full h-[48px] shrink-0 flex flex-row gap-0 justify-between items-center">
            <div className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[4px] justify-start items-start">
              <div className="text-[10px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
                {e.id}
              </div>
              <div className="text-[8px]/[normal] box-border text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                {e.sub}
              </div>
            </div>
            <div className="box-border w-fit shrink-0 h-fit flex flex-col gap-[2px] justify-start items-end" style={{ color: e.color }}>
              <div className="text-[8px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-normal text-right [white-space:nowrap]">
                {e.time}
              </div>
              <div className="text-[8px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-normal text-right [white-space:nowrap]">
                {e.tag}
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Quick actions */}
      <div className="box-border w-full [flex:1_1_0] flex flex-col gap-[10px] p-[14px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]">
        <div className={TITLE}>Quick Actions</div>
        {ACTIONS.map((a) => (
          <div key={a.title} className="box-border w-full h-[49px] shrink-0 flex flex-row gap-[10px] p-[0px_10px] justify-start items-center bg-[var(--ag-input-bg)] rounded-[6px]">
            <div className="box-border w-[28px] shrink-0 h-[28px] rounded-[6px]" style={{ backgroundColor: a.color }}></div>
            <div className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[4px] justify-start items-start">
              <div className="text-[10px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
                {a.title}
              </div>
              <div className="text-[8px]/[normal] box-border text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                {a.sub}
              </div>
            </div>
            <div className="text-[18px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
              ›
            </div>
          </div>
        ))}
        <div className="box-border w-full h-fit shrink-0 flex flex-col gap-[4px] p-[4px_0px] justify-start items-start">
          <div className="text-[10px]/[15px] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left">
            Need help? Contact our support team for assistance.
          </div>
          <div className="text-[10px]/[normal] box-border text-[#C084FC] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            Contact Support ↗
          </div>
        </div>
      </div>
    </div>
  );
}
