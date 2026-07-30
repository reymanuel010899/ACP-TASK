/**
 * Disputes — center column (Pencil "Disputes" design).
 *
 * Dashboard `--ag-*` tokens for structure; accent/status hues literal. The
 * over-time line and by-reason donut are real canvas charts. The single-series
 * line keeps a gradient area fill (an intentional polish over the flat mockup).
 */

import TrendAreaChart, { type TrendSeries } from "@/components/charts/TrendAreaChart";
import DonutChart, { type DonutSegment } from "@/components/charts/DonutChart";

const TABS = ["Overview", "All Disputes", "My Disputes", "Open", "In Review", "Escalated", "Closed", "Settings"];

const METRICS: { label: string; value: string; trend: string; trendColor: string }[] = [
  { label: "Total Disputes", value: "48", trend: "↑ 20% vs last 30 days", trendColor: "#7C3AED" },
  { label: "Open Disputes", value: "18", trend: "↑ 12% vs last 30 days", trendColor: "#F59E0B" },
  { label: "In Review", value: "14", trend: "↓ 5% vs last 30 days", trendColor: "#2563EB" },
  { label: "Escalated", value: "6", trend: "↑ 2% vs last 30 days", trendColor: "#EF4444" },
  { label: "Resolved", value: "10", trend: "↑ 45% vs last 30 days", trendColor: "#22C55E" },
];

// Single series, inverted 0–175 pixel scale (10 weekly points).
const TREND_MAX = 175;
const TREND: TrendSeries[] = [
  { label: "Disputes", color: "#8B5CF6", points: [40, 53, 70, 55, 69, 135, 70, 57, 45, 55] },
];
const TREND_AXIS = ["Apr 20", "Apr 27", "May 4", "May 11", "May 18"];

const REASONS: (DonutSegment & { pct: string })[] = [
  { label: "Payment Issues", value: 16, pct: "33.3%", color: "#7C3AED" },
  { label: "Service Quality", value: 11, pct: "22.9%", color: "#2563EB" },
  { label: "Contract Breach", value: 8, pct: "16.7%", color: "#F59E0B" },
  { label: "Delivery Delay", value: 6, pct: "12.5%", color: "#10B981" },
  { label: "Miscommunication", value: 4, pct: "8.3%", color: "#EAB308" },
  { label: "Other", value: 3, pct: "6.3%", color: "#94A3B8" },
];

const COLS: { label: string; width: string; flex?: boolean }[] = [
  { label: "ID", width: "w-[115px]" },
  { label: "Title", width: "w-[190px]", flex: true },
  { label: "Related To", width: "w-[140px]" },
  { label: "Amount", width: "w-[100px]" },
  { label: "Status", width: "w-[105px]" },
  { label: "Priority", width: "w-[88px]" },
  { label: "Created At", width: "w-[105px]" },
  { label: "Actions", width: "w-[40px]" },
];

type Row = {
  id: string; title: string; related: string; amount: string;
  status: string; statusColor: string; priority: string; priorityColor: string; date: string;
};

const ROWS: Row[] = [
  { id: "DSP-2024-048", title: "Payment for milestone 2", related: "CON-2024-021", amount: "$5,000.00", status: "Escalated", statusColor: "#EF4444", priority: "High", priorityColor: "#EF4444", date: "May 19, 2024" },
  { id: "DSP-2024-047", title: "Service availability issue", related: "CON-2024-018", amount: "$2,500.00", status: "In Review", statusColor: "#3B82F6", priority: "Medium", priorityColor: "#F59E0B", date: "May 19, 2024" },
  { id: "DSP-2024-046", title: "Deliverable not as expected", related: "CON-2024-017", amount: "$3,750.00", status: "Open", statusColor: "#F59E0B", priority: "Medium", priorityColor: "#F59E0B", date: "May 18, 2024" },
  { id: "DSP-2024-045", title: "Quality standards not met", related: "CON-2024-016", amount: "$7,200.00", status: "Escalated", statusColor: "#EF4444", priority: "High", priorityColor: "#EF4444", date: "May 18, 2024" },
];

export default function DisputesContent() {
  return (
    <div className="box-border w-full [flex:1_1_0] flex flex-col gap-[14px] p-[16px_18px_18px_18px] justify-start items-start">
      {/* Header */}
      <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
        <div className="box-border w-fit shrink-0 h-fit flex flex-col gap-[4px] justify-start items-start">
          <div className="text-[24px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
            Disputes
          </div>
          <div className="text-[12px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            Resolve conflicts and manage disputes across contracts and transactions.
          </div>
        </div>
        <div className="box-border w-fit shrink-0 h-[36px] flex flex-row gap-0 p-[0px_16px] justify-start items-center bg-[var(--ag-purple)] rounded-[6px]">
          <div className="text-[12px]/[normal] box-border text-[#FFFFFF] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
            + Create Dispute
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="box-border w-full h-[36px] shrink-0 flex flex-row gap-[28px] justify-start items-center [border-width:0px_0px_1px_0px] [border-style:solid] [border-color:var(--ag-divider)]">
        {TABS.map((tab, i) => (
          <div
            key={tab}
            className={
              i === 0
                ? "text-[11px]/[normal] box-border text-[#A78BFA] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]"
                : "text-[11px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
            }
          >
            {tab}
          </div>
        ))}
      </div>

      {/* Metrics */}
      <div className="box-border w-full h-[122px] shrink-0 flex flex-row gap-[10px] justify-start items-start">
        {METRICS.map((m) => (
          <div key={m.label} className="box-border [flex:1_1_0] h-full flex flex-col gap-[8px] p-[14px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[7px]">
            <div className="text-[10px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
              {m.label}
            </div>
            <div className="text-[23px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
              {m.value}
            </div>
            <div className="text-[9px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]" style={{ color: m.trendColor }}>
              {m.trend}
            </div>
          </div>
        ))}
      </div>

      {/* Analytics */}
      <div className="box-border w-full h-[292px] shrink-0 flex flex-row gap-[12px] justify-start items-start">
        {/* Over time */}
        <div className="box-border [flex:1_1_0] min-w-0 h-full flex flex-col gap-[8px] p-[16px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]">
          <div className="text-[14px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
            Disputes Over Time
          </div>
          <div className="box-border w-full [flex:1_1_0] min-h-0 flex flex-col justify-center items-stretch">
            <TrendAreaChart series={TREND} height={190} max={TREND_MAX} />
          </div>
          <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
            {TREND_AXIS.map((a) => (
              <div key={a} className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                {a}
              </div>
            ))}
          </div>
        </div>
        {/* By reason */}
        <div className="box-border [flex:1_1_0] min-w-0 h-full flex flex-col gap-[14px] p-[16px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]">
          <div className="text-[14px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
            Disputes by Reason
          </div>
          <div className="box-border w-full [flex:1_1_0] flex flex-row gap-[16px] justify-start items-center">
            <DonutChart data={REASONS} size={132} thickness={20}>
              <div className="text-[24px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-center [white-space:nowrap]">
                48
              </div>
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-center [white-space:nowrap]">
                Total
              </div>
            </DonutChart>
            <div className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[9px] justify-start items-start">
              {REASONS.map((r) => (
                <div key={r.label} className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
                  <div className="text-[10px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]" style={{ color: r.color }}>
                    ● {r.label}
                  </div>
                  <div className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                    {r.value} ({r.pct})
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Recent disputes table */}
      <div className="box-border w-full [flex:1_1_0] flex flex-col gap-0 p-[14px_16px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px] overflow-hidden">
        <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
          <div className="text-[14px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
            Recent Disputes
          </div>
          <div className="text-[10px]/[normal] box-border text-[#A78BFA] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            View all disputes
          </div>
        </div>
        {/* Header */}
        <div className="box-border w-full h-[36px] shrink-0 flex flex-row gap-0 justify-start items-center">
          {COLS.map((c) => (
            <div key={c.label} className={`box-border ${c.flex ? "[flex:1_1_0] min-w-0" : `${c.width} shrink-0`} h-full flex flex-row gap-0 justify-start items-center`}>
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
                {c.label}
              </div>
            </div>
          ))}
        </div>
        {/* Rows */}
        {ROWS.map((r) => (
          <div key={r.id} className="box-border w-full h-[40px] shrink-0 flex flex-row gap-0 justify-start items-center">
            <div className="box-border w-[115px] shrink-0 h-full flex flex-row gap-0 justify-start items-center">
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{r.id}</div>
            </div>
            <div className="box-border [flex:1_1_0] min-w-0 h-full flex flex-row gap-0 justify-start items-center">
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{r.title}</div>
            </div>
            <div className="box-border w-[140px] shrink-0 h-full flex flex-row gap-0 justify-start items-center">
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{r.related}</div>
            </div>
            <div className="box-border w-[100px] shrink-0 h-full flex flex-row gap-0 justify-start items-center">
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{r.amount}</div>
            </div>
            <div className="box-border w-[105px] shrink-0 h-full flex flex-row gap-0 justify-start items-center">
              <div className="text-[9px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]" style={{ color: r.statusColor }}>{r.status}</div>
            </div>
            <div className="box-border w-[88px] shrink-0 h-full flex flex-row gap-0 justify-start items-center">
              <div className="text-[9px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]" style={{ color: r.priorityColor }}>{r.priority}</div>
            </div>
            <div className="box-border w-[105px] shrink-0 h-full flex flex-row gap-0 justify-start items-center">
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{r.date}</div>
            </div>
            <div className="box-border w-[40px] shrink-0 h-full flex flex-row gap-0 justify-start items-center">
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">•••</div>
            </div>
          </div>
        ))}
        {/* Footer */}
        <div className="box-border w-full [flex:1_1_0] flex flex-row gap-0 justify-between items-center">
          <div className="text-[10px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            Showing 1 to 5 of 48 disputes
          </div>
          <div className="text-[10px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            ‹ 1 2 3 … 10 ›
          </div>
        </div>
      </div>
    </div>
  );
}
