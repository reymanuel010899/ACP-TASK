/**
 * Negotiations — center column (Pencil "Negotiations" design).
 *
 * Dashboard `--ag-*` tokens for structure; accent/status hues literal. The
 * over-time line chart and by-status donut are real canvas charts.
 */

import TrendAreaChart, { type TrendSeries } from "@/components/charts/TrendAreaChart";
import DonutChart, { type DonutSegment } from "@/components/charts/DonutChart";

const TABS = ["Overview", "All Negotiations", "My Negotiations", "Active", "Pending", "Completed", "Cancelled", "Templates", "Settings"];

const METRICS: { label: string; value: string; trend: string; trendColor: string }[] = [
  { label: "Total Negotiations", value: "62", trend: "↑ 18% vs last 30 days", trendColor: "#7C3AED" },
  { label: "Active Negotiations", value: "21", trend: "↑ 23% vs last 30 days", trendColor: "#2563EB" },
  { label: "Pending Response", value: "14", trend: "↓ 8% vs last 30 days", trendColor: "#F59E0B" },
  { label: "Completed", value: "19", trend: "↑ 27% vs last 30 days", trendColor: "#22C55E" },
  { label: "Success Rate", value: "76%", trend: "↑ 12% vs last 30 days", trendColor: "#8B5CF6" },
  { label: "Avg. Negotiation Time", value: "6.4 days", trend: "↓ 1.2 days vs last 30 days", trendColor: "#06B6D4" },
];

// Line shapes from the design (14 weekly points, inverted 0–185 pixel scale).
const TREND_MAX = 185;
const TREND: TrendSeries[] = [
  { label: "Active", color: "#2563EB", points: [65, 75, 85, 97, 93, 97, 130, 103, 95, 115, 107, 110, 115, 128] },
  { label: "Pending", color: "#F59E0B", points: [45, 53, 60, 57, 55, 57, 67, 75, 69, 85, 73, 65, 50, 50] },
  { label: "Completed", color: "#22C55E", points: [35, 50, 60, 65, 60, 65, 95, 75, 80, 90, 77, 71, 93, 87] },
  { label: "Cancelled", color: "#EF4444", points: [20, 35, 43, 40, 30, 20, 20, 23, 17, 17, 23, 15, 15, 17] },
];
const TREND_AXIS = ["Apr 20", "Apr 27", "May 4", "May 11", "May 18"];

const STATUS: (DonutSegment & { pct: string })[] = [
  { label: "Active", value: 21, pct: "33.9%", color: "#2563EB" },
  { label: "Pending", value: 14, pct: "22.6%", color: "#F59E0B" },
  { label: "Completed", value: 19, pct: "30.6%", color: "#22C55E" },
  { label: "Cancelled", value: 8, pct: "12.9%", color: "#EF4444" },
];

const COLS: { label: string; width: string; flex?: boolean }[] = [
  { label: "ID", width: "w-[95px]" },
  { label: "Title", width: "w-[150px]", flex: true },
  { label: "Counterparty", width: "w-[140px]" },
  { label: "Value", width: "w-[100px]" },
  { label: "Status", width: "w-[96px]" },
  { label: "Priority", width: "w-[92px]" },
  { label: "Owner", width: "w-[72px]" },
  { label: "Updated", width: "w-[95px]" },
  { label: "Actions", width: "w-[40px]" },
];

type Row = {
  id: string; title: string; party: string; value: string;
  status: string; statusColor: string; priority: string; priorityColor: string; updated: string;
};

const ROWS: Row[] = [
  { id: "N-2024-021", title: "Contract Renewal 2024", party: "TechCorp Inc.", value: "$120,000.00", status: "Active", statusColor: "#3B82F6", priority: "High", priorityColor: "#EF4444", updated: "May 19, 2024" },
  { id: "N-2024-018", title: "Service Agreement", party: "CloudNet Ltd.", value: "$85,500.00", status: "Pending", statusColor: "#F59E0B", priority: "Medium", priorityColor: "#F59E0B", updated: "May 18, 2024" },
  { id: "N-2024-030", title: "Partnership Terms", party: "DataFlow Systems", value: "$200,000.00", status: "Active", statusColor: "#3B82F6", priority: "High", priorityColor: "#EF4444", updated: "May 17, 2024" },
  { id: "N-2024-024", title: "SLA Negotiation", party: "SecureOps", value: "$45,000.00", status: "In Review", statusColor: "#F59E0B", priority: "Medium", priorityColor: "#F59E0B", updated: "May 16, 2024" },
];

export default function NegotiationsContent() {
  return (
    <div className="box-border w-full [flex:1_1_0] flex flex-col gap-[14px] p-[16px_18px_18px_18px] justify-start items-start">
      {/* Header */}
      <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
        <div className="box-border w-fit shrink-0 h-fit flex flex-col gap-[4px] justify-start items-start">
          <div className="text-[24px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
            Negotiations
          </div>
          <div className="text-[12px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            Manage and track contract negotiations from initiation to agreement.
          </div>
        </div>
        <div className="box-border w-fit shrink-0 h-[36px] flex flex-row gap-0 p-[0px_16px] justify-start items-center bg-[var(--ag-purple)] rounded-[6px]">
          <div className="text-[12px]/[normal] box-border text-[#FFFFFF] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
            + New Negotiation
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="box-border w-full h-[36px] shrink-0 flex flex-row gap-[26px] justify-start items-center [border-width:0px_0px_1px_0px] [border-style:solid] [border-color:var(--ag-divider)]">
        {TABS.map((tab, i) => (
          <div
            key={tab}
            className={
              i === 0
                ? "text-[10px]/[normal] box-border text-[#A78BFA] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]"
                : "text-[10px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
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
      <div className="box-border w-full h-[300px] shrink-0 flex flex-row gap-[12px] justify-start items-start">
        {/* Over time */}
        <div className="box-border [flex:1_1_0] min-w-0 h-full flex flex-col gap-[8px] p-[16px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]">
          <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
            <div className="text-[14px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
              Negotiations Over Time
            </div>
            <div className="box-border w-fit h-fit shrink-0 flex flex-row gap-[10px] justify-start items-center">
              {TREND.map((s) => (
                <div key={s.label} className="box-border w-fit h-fit shrink-0 flex flex-row gap-[4px] justify-start items-center">
                  <div className="box-border w-[8px] shrink-0 h-[8px] rounded-full" style={{ backgroundColor: s.color }}></div>
                  <div className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                    {s.label}
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className="box-border w-full [flex:1_1_0] min-h-0 flex flex-col justify-center items-stretch">
            <TrendAreaChart series={TREND} height={196} max={TREND_MAX} showArea={false} />
          </div>
          <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
            {TREND_AXIS.map((a) => (
              <div key={a} className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                {a}
              </div>
            ))}
          </div>
        </div>
        {/* By status */}
        <div className="box-border [flex:1_1_0] min-w-0 h-full flex flex-col gap-[14px] p-[16px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]">
          <div className="text-[14px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
            Negotiations by Status
          </div>
          <div className="box-border w-full [flex:1_1_0] flex flex-row gap-[16px] justify-start items-center">
            <DonutChart data={STATUS} size={140} thickness={22}>
              <div className="text-[25px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-center [white-space:nowrap]">
                62
              </div>
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-center [white-space:nowrap]">
                Total
              </div>
            </DonutChart>
            <div className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[12px] justify-start items-start">
              {STATUS.map((s) => (
                <div key={s.label} className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
                  <div className="text-[11px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]" style={{ color: s.color }}>
                    ● {s.label}
                  </div>
                  <div className="text-[10px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                    {s.value} ({s.pct})
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Recent negotiations table */}
      <div className="box-border w-full [flex:1_1_0] flex flex-col gap-0 p-[14px_16px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px] overflow-hidden">
        <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
          <div className="text-[14px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
            Recent Negotiations
          </div>
          <div className="text-[10px]/[normal] box-border text-[#A78BFA] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            View all negotiations
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
            <div className="box-border w-[95px] shrink-0 h-full flex flex-row gap-0 justify-start items-center">
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{r.id}</div>
            </div>
            <div className="box-border [flex:1_1_0] min-w-0 h-full flex flex-row gap-0 justify-start items-center">
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{r.title}</div>
            </div>
            <div className="box-border w-[140px] shrink-0 h-full flex flex-row gap-0 justify-start items-center">
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{r.party}</div>
            </div>
            <div className="box-border w-[100px] shrink-0 h-full flex flex-row gap-0 justify-start items-center">
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{r.value}</div>
            </div>
            <div className="box-border w-[96px] shrink-0 h-full flex flex-row gap-0 justify-start items-center">
              <div className="text-[9px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]" style={{ color: r.statusColor }}>{r.status}</div>
            </div>
            <div className="box-border w-[92px] shrink-0 h-full flex flex-row gap-0 justify-start items-center">
              <div className="text-[9px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]" style={{ color: r.priorityColor }}>{r.priority}</div>
            </div>
            <div className="box-border w-[72px] shrink-0 h-full flex flex-row gap-0 justify-start items-center">
              <div className="box-border w-[16px] shrink-0 h-[16px] bg-[var(--ag-purple)] rounded-full"></div>
            </div>
            <div className="box-border w-[95px] shrink-0 h-full flex flex-row gap-0 justify-start items-center">
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{r.updated}</div>
            </div>
            <div className="box-border w-[40px] shrink-0 h-full flex flex-row gap-0 justify-start items-center">
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">•••</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
