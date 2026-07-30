/**
 * Negotiations — right rail (Pencil "Negotiations Right Panel" design):
 * negotiation-health donut (canvas), upcoming deadlines, and recent activity.
 * Dashboard `--ag-*` tokens for structure; accent hues literal.
 */

import DonutChart, { type DonutSegment } from "@/components/charts/DonutChart";

// Health gauge proportions (On Track dominant), matching the design's ring.
const HEALTH: DonutSegment[] = [
  { label: "On Track", value: 65, color: "#22C55E" },
  { label: "At Risk", value: 18, color: "#F59E0B" },
  { label: "Delayed", value: 10, color: "#EF4444" },
  { label: "Stalled", value: 7, color: "#94A3B8" },
];

const DEADLINES: { id: string; sub: string; days: string; tag: string; color: string }[] = [
  { id: "N-2024-021", sub: "Contract renewal - TechCorp", days: "2 days", tag: "High", color: "#EF4444" },
  { id: "N-2024-018", sub: "Service agreement - CloudNet", days: "5 days", tag: "Medium", color: "#F59E0B" },
  { id: "N-2024-030", sub: "Partnership terms - DataFlow", days: "7 days", tag: "Medium", color: "#F59E0B" },
  { id: "N-2024-024", sub: "SLA negotiation - SecureOps", days: "10 days", tag: "Low", color: "#22C55E" },
];

const ACTIVITY: { title: string; sub: string; time: string; color: string }[] = [
  { title: "Counterparty responded", sub: "N-2024-021 · Contract Renewal 2024", time: "2h ago", color: "#2563EB" },
  { title: "New proposal received", sub: "N-2024-018 · Service Agreement", time: "5h ago", color: "#F59E0B" },
  { title: "Negotiation completed", sub: "N-2024-012 · NDA Agreement", time: "1d ago", color: "#22C55E" },
  { title: "Comment added", sub: "N-2024-024 · SLA Negotiation", time: "2d ago", color: "#7C3AED" },
];

const TITLE =
  "text-[14px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]";

export default function NegotiationsRightPanel() {
  return (
    <div className="box-border w-[280px] shrink-0 h-full flex flex-col gap-[12px] p-[14px] justify-start items-start bg-[var(--ag-right-bg)] [border-width:0px_0px_0px_1px] [border-style:solid] [border-color:var(--ag-divider)] overflow-y-auto">
      {/* Negotiation health */}
      <div className="box-border w-full h-[232px] shrink-0 flex flex-col gap-[12px] p-[14px] justify-center items-center bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]">
        <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-start items-center">
          <div className="text-[15px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
            Negotiation Health
          </div>
        </div>
        <DonutChart data={HEALTH} size={118} thickness={16}>
          <div className="text-[24px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-center [white-space:nowrap]">
            82
          </div>
          <div className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-center [white-space:nowrap]">
            Healthy
          </div>
        </DonutChart>
        <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-start items-center">
          <div className="text-[11px]/[normal] box-border text-[#C084FC] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            View Health Report ›
          </div>
        </div>
      </div>

      {/* Upcoming deadlines */}
      <div className="box-border w-full h-[314px] shrink-0 flex flex-col gap-[10px] p-[14px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]">
        <div className={TITLE}>Upcoming Deadlines</div>
        {DEADLINES.map((d) => (
          <div key={d.id} className="box-border w-full h-[46px] shrink-0 flex flex-row gap-0 justify-between items-center">
            <div className="box-border w-fit shrink-0 h-fit flex flex-col gap-[4px] justify-start items-start">
              <div className="text-[10px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
                {d.id}
              </div>
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                {d.sub}
              </div>
            </div>
            <div className="box-border w-fit shrink-0 h-fit flex flex-col gap-[2px] justify-start items-end" style={{ color: d.color }}>
              <div className="text-[9px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-normal text-right [white-space:nowrap]">
                {d.days}
              </div>
              <div className="text-[9px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-normal text-right [white-space:nowrap]">
                {d.tag}
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Recent activity */}
      <div className="box-border w-full [flex:1_1_0] flex flex-col gap-[11px] p-[14px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]">
        <div className={TITLE}>Recent Activity</div>
        {ACTIVITY.map((a) => (
          <div key={a.title} className="box-border w-full h-[48px] shrink-0 flex flex-row gap-[9px] justify-start items-center">
            <div className="box-border w-[30px] shrink-0 h-[30px] rounded-[6px]" style={{ backgroundColor: a.color }}></div>
            <div className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[4px] justify-start items-start">
              <div className="text-[10px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
                {a.title}
              </div>
              <div className="text-[8px]/[normal] box-border text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                {a.sub}
              </div>
            </div>
            <div className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
              {a.time}
            </div>
          </div>
        ))}
        <div className="text-[10px]/[normal] box-border text-[#C084FC] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
          View all activity ›
        </div>
      </div>
    </div>
  );
}
