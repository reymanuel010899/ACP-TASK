/**
 * Approvals — right rail (Pencil "Approvals Right Panel" design): approval
 * health donut (canvas), my-pending list, and approval workflows. Dashboard
 * `--ag-*` tokens for structure; accent hues literal.
 */

import DonutChart, { type DonutSegment } from "@/components/charts/DonutChart";

const HEALTH: DonutSegment[] = [
  { label: "Approved", value: 95.1, color: "#22C55E" },
  { label: "Pending", value: 3.7, color: "#F59E0B" },
  { label: "Rejected", value: 1.2, color: "#EF4444" },
];

const PENDING: { name: string; sub: string; tag: string; tagColor: string }[] = [
  { name: "Contract Renewal - TechCorp", sub: "Contract • $120,000.00", tag: "High", tagColor: "#EF4444" },
  { name: "Budget Increase - Marketing Agent", sub: "Budget • $15,000.00", tag: "Medium", tagColor: "#F59E0B" },
  { name: "New Agent Access - DataAnalyst", sub: "Access • Production Environment", tag: "Medium", tagColor: "#F59E0B" },
];

const WORKFLOWS: { name: string; sub: string; count: string }[] = [
  { name: "Standard Approval", sub: "Most common workflow", count: "124" },
  { name: "Executive Approval", sub: "High-value approvals", count: "38" },
  { name: "Emergency Approval", sub: "Time-sensitive requests", count: "15" },
  { name: "Compliance Approval", sub: "Policy and compliance", count: "14" },
];

const TITLE =
  "text-[14px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]";

export default function ApprovalsRightPanel() {
  return (
    <div className="box-border w-[260px] shrink-0 h-full flex flex-col gap-[12px] p-[14px] justify-start items-start bg-[var(--ag-right-bg)] [border-width:0px_0px_0px_1px] [border-style:solid] [border-color:var(--ag-divider)] overflow-y-auto">
      {/* Approval health */}
      <div className="box-border w-full h-[230px] shrink-0 flex flex-col gap-[14px] p-[14px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]">
        <div className="text-[15px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
          Approval Health
        </div>
        <div className="box-border w-full h-[88px] shrink-0 flex flex-row gap-[14px] justify-start items-center">
          <DonutChart data={HEALTH} size={88} thickness={14} />
          <div className="box-border w-fit shrink-0 h-fit flex flex-col gap-[11px] justify-start items-start">
            {HEALTH.map((h) => (
              <div key={h.label} className="box-border w-fit h-fit shrink-0 flex flex-row gap-[8px] justify-start items-center">
                <div className="box-border w-[8px] shrink-0 h-[8px] rounded-full" style={{ backgroundColor: h.color }}></div>
                <div className="text-[10px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                  {h.label} <span className="text-[var(--ag-text)] font-semibold">{h.value}%</span>
                </div>
              </div>
            ))}
          </div>
        </div>
        <div className="text-[11px]/[normal] box-border text-[#C084FC] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
          View Health Report ↗
        </div>
      </div>

      {/* My pending approvals */}
      <div className="box-border w-full h-[270px] shrink-0 flex flex-col gap-[7px] p-[14px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]">
        <div className={TITLE}>My Pending Approvals</div>
        {PENDING.map((p) => (
          <div key={p.name} className="box-border w-full h-[43px] shrink-0 flex flex-row gap-[8px] justify-start items-center">
            <div className="box-border w-[28px] shrink-0 h-[28px] bg-[#24134A] rounded-[6px]"></div>
            <div className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[3px] justify-start items-start">
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
                {p.name}
              </div>
              <div className="text-[8px]/[normal] box-border text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                {p.sub}
              </div>
            </div>
            <div className="text-[8px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]" style={{ color: p.tagColor }}>
              {p.tag}
            </div>
          </div>
        ))}
        <div className="text-[10px]/[normal] box-border text-[#C084FC] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
          View all my approvals ›
        </div>
      </div>

      {/* Approval workflows */}
      <div className="box-border w-full [flex:1_1_0] flex flex-col gap-[12px] p-[14px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]">
        <div className={TITLE}>Approval Workflows</div>
        {WORKFLOWS.map((wf) => (
          <div key={wf.name} className="box-border w-full h-fit shrink-0 flex flex-row gap-[8px] justify-start items-center">
            <div className="box-border w-[28px] shrink-0 h-[28px] bg-[#1E3A8A] rounded-[6px]"></div>
            <div className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[3px] justify-start items-start">
              <div className="text-[10px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
                {wf.name}
              </div>
              <div className="text-[8px]/[normal] box-border text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                {wf.sub}
              </div>
            </div>
            <div className="text-[11px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
              {wf.count}
            </div>
          </div>
        ))}
        <div className="text-[10px]/[normal] box-border text-[#C084FC] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
          Manage Workflows ›
        </div>
      </div>
    </div>
  );
}
