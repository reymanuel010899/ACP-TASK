/**
 * Approvals — center column (Pencil "Approvals" design).
 *
 * Dashboard `--ag-*` design language for structure; accent/status hues literal.
 * The two analytics visuals (approvals-over-time and by-category) are rendered
 * with real canvas charts instead of the flat Pencil mockups.
 */

import TrendAreaChart, { type TrendSeries } from "@/components/charts/TrendAreaChart";
import DonutChart, { type DonutSegment } from "@/components/charts/DonutChart";

const TABS = ["Overview", "My Approvals", "Pending", "Approved", "Rejected", "Delegated", "Settings"];

const METRICS: { label: string; value: string; trend: string; trendColor: string }[] = [
  { label: "Pending Approvals", value: "27", trend: "↑ 18% vs last 30 days", trendColor: "#F59E0B" },
  { label: "My Pending", value: "9", trend: "↑ 12% vs last 30 days", trendColor: "#8B5CF6" },
  { label: "Approved", value: "156", trend: "↑ 24% vs last 30 days", trendColor: "#22C55E" },
  { label: "Rejected", value: "8", trend: "↓ 5% vs last 30 days", trendColor: "#EF4444" },
  { label: "Avg. Approval Time", value: "1.8 days", trend: "↓ 0.6 days vs last 30 days", trendColor: "#3B82F6" },
  { label: "Approval Rate", value: "95.1%", trend: "↑ 6% vs last 30 days", trendColor: "#06B6D4" },
];

// Series shapes carried over from the design's line chart (16 weekly points,
// values are the design's inverted pixel heights on a 0–160 scale).
const TREND_MAX = 160;
const TREND: TrendSeries[] = [
  { label: "Submitted", color: "#7C3AED", points: [38, 38, 55, 69, 59, 67, 100, 114, 130, 92, 66, 58, 81, 81, 68, 74] },
  { label: "Approved", color: "#22C55E", points: [22, 33, 43, 50, 42, 46, 62, 70, 74, 65, 48, 42, 56, 51, 53, 66] },
  { label: "Rejected", color: "#EF4444", points: [10, 12, 12, 17, 16, 20, 24, 25, 21, 15, 12, 17, 20, 17, 16, 20] },
];
const TREND_AXIS = ["Apr 20", "Apr 27", "May 4", "May 11", "May 18"];

const CATEGORIES: (DonutSegment & { pct: string })[] = [
  { label: "Contract Changes", value: 62, pct: "32.5%", color: "#7C3AED" },
  { label: "Access Requests", value: 45, pct: "23.6%", color: "#2563EB" },
  { label: "Budget Approvals", value: 31, pct: "16.2%", color: "#22C55E" },
  { label: "Agent Onboarding", value: 26, pct: "13.6%", color: "#F59E0B" },
  { label: "Policy Exceptions", value: 17, pct: "8.9%", color: "#22B8CF" },
  { label: "Other", value: 10, pct: "5.2%", color: "#94A3B8" },
];

const COLS: { label: string; width: string; flex?: boolean }[] = [
  { label: "ID", width: "w-[100px]" },
  { label: "Title", width: "w-[205px]", flex: true },
  { label: "Type", width: "w-[82px]" },
  { label: "Requested By", width: "w-[130px]" },
  { label: "Status", width: "w-[100px]" },
  { label: "Priority", width: "w-[90px]" },
  { label: "Submitted", width: "w-[100px]" },
  { label: "Actions", width: "w-[40px]" },
];

type Row = { id: string; title: string; type: string; by: string; status: string; statusColor: string; priority: string; priorityColor: string; date: string };

const ROWS: Row[] = [
  { id: "APR-2024-156", title: "Contract Renewal - TechCorp", type: "Contract", by: "Ana Martinez", status: "Approved", statusColor: "#22C55E", priority: "High", priorityColor: "#EF4444", date: "May 19, 2024" },
  { id: "APR-2024-155", title: "Budget Increase - Q2 Campaign", type: "Budget", by: "Miguel Torres", status: "Approved", statusColor: "#22C55E", priority: "Medium", priorityColor: "#F59E0B", date: "May 18, 2024" },
  { id: "APR-2024-154", title: "New Agent Onboarding - WriterAI", type: "Onboarding", by: "Sofia Rodriguez", status: "Approved", statusColor: "#22C55E", priority: "Medium", priorityColor: "#F59E0B", date: "May 18, 2024" },
];

export default function ApprovalsContent() {
  return (
    <div className="box-border w-full [flex:1_1_0] flex flex-col gap-[14px] p-[16px_20px_18px_20px] justify-start items-start">
      {/* Header */}
      <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
        <div className="box-border w-fit shrink-0 h-fit flex flex-col gap-[4px] justify-start items-start">
          <div className="text-[24px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
            Approvals
          </div>
          <div className="text-[12px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            Review and approve requests, changes, and actions across your organization.
          </div>
        </div>
        <div className="box-border w-fit shrink-0 h-[36px] flex flex-row gap-0 p-[0px_16px] justify-start items-center bg-[var(--ag-purple)] rounded-[6px]">
          <div className="text-[12px]/[normal] box-border text-[#FFFFFF] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
            + New Approval Request
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
      <div className="box-border w-full h-[112px] shrink-0 flex flex-row gap-[10px] justify-start items-start">
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
      <div className="box-border w-full h-[304px] shrink-0 flex flex-row gap-[12px] justify-start items-start">
        {/* Approvals over time */}
        <div className="box-border [flex:1_1_0] min-w-0 h-full flex flex-col gap-[10px] p-[16px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]">
          <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
            <div className="text-[14px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
              Approvals Over Time
            </div>
            <div className="box-border w-fit h-fit shrink-0 flex flex-row gap-[12px] justify-start items-center">
              {TREND.map((s) => (
                <div key={s.label} className="box-border w-fit h-fit shrink-0 flex flex-row gap-[5px] justify-start items-center">
                  <div className="box-border w-[8px] shrink-0 h-[8px] rounded-full" style={{ backgroundColor: s.color }}></div>
                  <div className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                    {s.label}
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className="box-border w-full [flex:1_1_0] min-h-0 flex flex-col justify-center items-stretch">
            <TrendAreaChart series={TREND} height={186} max={TREND_MAX} showArea={false} />
          </div>
          <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
            {TREND_AXIS.map((a) => (
              <div key={a} className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                {a}
              </div>
            ))}
          </div>
        </div>
        {/* Approvals by category */}
        <div className="box-border [flex:1_1_0] min-w-0 h-full flex flex-col gap-[12px] p-[16px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]">
          <div className="text-[14px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
            Approvals by Category
          </div>
          <div className="box-border w-full [flex:1_1_0] flex flex-row gap-[16px] justify-start items-center">
            <DonutChart data={CATEGORIES} size={128} thickness={20}>
              <div className="text-[22px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-center [white-space:nowrap]">
                191
              </div>
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-center [white-space:nowrap]">
                Total
              </div>
            </DonutChart>
            <div className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[9px] justify-start items-start">
              {CATEGORIES.map((c) => (
                <div key={c.label} className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
                  <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-[8px] justify-start items-center">
                    <div className="box-border w-[9px] shrink-0 h-[9px] rounded-full" style={{ backgroundColor: c.color }}></div>
                    <div className="text-[11px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                      {c.label}
                    </div>
                  </div>
                  <div className="text-[10px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                    {c.value} ({c.pct})
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className="text-[11px]/[normal] box-border text-[#C084FC] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            View all categories ›
          </div>
        </div>
      </div>

      {/* Recent approvals table */}
      <div className="box-border w-full [flex:1_1_0] flex flex-col gap-0 p-[14px_16px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px] overflow-hidden">
        <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
          <div className="text-[14px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
            Recent Approvals
          </div>
          <div className="text-[10px]/[normal] box-border text-[#A78BFA] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            View all
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
          <div key={r.id} className="box-border w-full h-[38px] shrink-0 flex flex-row gap-0 justify-start items-center">
            <div className="box-border w-[100px] shrink-0 h-full flex flex-row gap-0 justify-start items-center">
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{r.id}</div>
            </div>
            <div className="box-border [flex:1_1_0] min-w-0 h-full flex flex-row gap-0 justify-start items-center">
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{r.title}</div>
            </div>
            <div className="box-border w-[82px] shrink-0 h-full flex flex-row gap-0 justify-start items-center">
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{r.type}</div>
            </div>
            <div className="box-border w-[130px] shrink-0 h-full flex flex-row gap-0 justify-start items-center">
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{r.by}</div>
            </div>
            <div className="box-border w-[100px] shrink-0 h-full flex flex-row gap-0 justify-start items-center">
              <div className="text-[9px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]" style={{ color: r.statusColor }}>{r.status}</div>
            </div>
            <div className="box-border w-[90px] shrink-0 h-full flex flex-row gap-0 justify-start items-center">
              <div className="text-[9px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]" style={{ color: r.priorityColor }}>{r.priority}</div>
            </div>
            <div className="box-border w-[100px] shrink-0 h-full flex flex-row gap-0 justify-start items-center">
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{r.date}</div>
            </div>
            <div className="box-border w-[40px] shrink-0 h-full flex flex-row gap-0 justify-start items-center">
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">•••</div>
            </div>
          </div>
        ))}
        {/* Footer */}
        <div className="box-border w-full h-[34px] shrink-0 flex flex-row gap-0 justify-between items-center">
          <div className="text-[10px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            Showing 1 to 5 of 191 approvals
          </div>
          <div className="text-[10px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            ‹ 1 2 3 4 5 … 39 ›
          </div>
        </div>
      </div>
    </div>
  );
}
