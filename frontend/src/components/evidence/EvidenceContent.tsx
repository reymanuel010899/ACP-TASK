/**
 * Evidence & Audit — center column (Pencil "Evidence & Audit" design).
 *
 * Dashboard `--ag-*` tokens for structure; accent/status hues literal. The
 * over-time line (with gradient area fill) and by-type donut are canvas charts.
 */

import TrendAreaChart, { type TrendSeries } from "@/components/charts/TrendAreaChart";
import DonutChart, { type DonutSegment } from "@/components/charts/DonutChart";

const TABS = ["Overview", "Audit Logs", "Evidence Store", "Export & Reports", "Retention Policies", "Settings"];

const METRICS: { label: string; value: string; trend: string; trendColor: string }[] = [
  { label: "Total Evidence Items", value: "3,842", trend: "↑ 18% vs last 30 days", trendColor: "#7C3AED" },
  { label: "Audit Log Events", value: "24,651", trend: "↑ 24% vs last 30 days", trendColor: "#2563EB" },
  { label: "Integrity Verified", value: "99.98%", trend: "↑ 0.05% vs last 30 days", trendColor: "#22C55E" },
  { label: "Storage Used", value: "248.6 GB", trend: "24.9% of 1 TB", trendColor: "#F59E0B" },
  { label: "Retention Compliance", value: "100%", trend: "Compliant", trendColor: "#8B5CF6" },
];

// Single series with area fill (inverted 0–175 pixel scale, 7 daily points).
const TREND_MAX = 175;
const TREND: TrendSeries[] = [
  { label: "Evidence", color: "#8B5CF6", points: [30, 70, 43, 140, 70, 47, 30] },
];
const TREND_AXIS = ["May 13", "May 14", "May 15", "May 16", "May 17", "May 18", "May 19"];

const TYPES: (DonutSegment & { pct: string; display: string })[] = [
  { label: "Task Executions", value: 1342, display: "1,342", pct: "34.9%", color: "#7C3AED" },
  { label: "Contract Events", value: 842, display: "842", pct: "21.9%", color: "#2563EB" },
  { label: "Approvals", value: 612, display: "612", pct: "15.9%", color: "#22C55E" },
  { label: "Negotiations", value: 456, display: "456", pct: "11.9%", color: "#F59E0B" },
  { label: "Agent Actions", value: 310, display: "310", pct: "8.1%", color: "#22B8CF" },
  { label: "Other", value: 280, display: "280", pct: "7.3%", color: "#94A3B8" },
];

const COLS: { label: string; width: string; flex?: boolean }[] = [
  { label: "Timestamp", width: "w-[160px]" },
  { label: "Actor", width: "w-[150px]", flex: true },
  { label: "Action", width: "w-[100px]" },
  { label: "Resource", width: "w-[110px]" },
  { label: "Entity ID", width: "w-[110px]" },
  { label: "IP Address", width: "w-[110px]" },
  { label: "Result", width: "w-[95px]" },
  { label: "Details", width: "w-[55px]" },
];

type Row = { time: string; actor: string; action: string; resource: string; entity: string; ip: string };

const ROWS: Row[] = [
  { time: "May 19, 2024 10:24:15 AM", actor: "Rey Ferreras", action: "UPDATE", resource: "Contract", entity: "C-883", ip: "192.168.1.45" },
  { time: "May 19, 2024 10:15:42 AM", actor: "Ana Martinez", action: "APPROVE", resource: "Task", entity: "T-1289", ip: "192.168.1.22" },
  { time: "May 19, 2024 09:58:31 AM", actor: "System", action: "CREATE", resource: "Evidence", entity: "E-3842", ip: "10.0.0.12" },
  { time: "May 19, 2024 09:45:12 AM", actor: "Sofia Rodriguez", action: "DELETE", resource: "Document", entity: "D-772", ip: "192.168.1.78" },
];

export default function EvidenceContent() {
  return (
    <div className="box-border w-full [flex:1_1_0] flex flex-col gap-[14px] p-[16px_20px_18px_20px] justify-start items-start">
      {/* Header */}
      <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
        <div className="box-border w-fit shrink-0 h-fit flex flex-col gap-[4px] justify-start items-start">
          <div className="text-[24px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
            Evidence &amp; Audit
          </div>
          <div className="text-[12px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            Immutable records of actions, decisions, and system events across your ecosystem.
          </div>
        </div>
        <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-[10px] justify-start items-start">
          <div className="box-border w-fit shrink-0 h-[36px] flex flex-row gap-0 p-[0px_14px] justify-start items-center bg-[var(--ag-input-bg)] rounded-[6px]">
            <div className="text-[11px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
              Export Report
            </div>
          </div>
          <div className="box-border w-fit shrink-0 h-[36px] flex flex-row gap-0 p-[0px_14px] justify-start items-center bg-[var(--ag-purple)] rounded-[6px]">
            <div className="text-[11px]/[normal] box-border text-[#FFFFFF] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
              ＋ Create Evidence
            </div>
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
      <div className="box-border w-full h-[118px] shrink-0 flex flex-row gap-[10px] justify-start items-start">
        {METRICS.map((m) => (
          <div key={m.label} className="box-border [flex:1_1_0] h-full flex flex-col gap-[8px] p-[14px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[7px]">
            <div className="text-[10px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
              {m.label}
            </div>
            <div className="text-[22px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
              {m.value}
            </div>
            <div className="text-[9px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]" style={{ color: m.trendColor }}>
              {m.trend}
            </div>
          </div>
        ))}
      </div>

      {/* Analytics */}
      <div className="box-border w-full h-[294px] shrink-0 flex flex-row gap-[12px] justify-start items-start">
        {/* Over time */}
        <div className="box-border [flex:1_1_0] min-w-0 h-full flex flex-col gap-[8px] p-[16px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]">
          <div className="text-[14px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
            Evidence Over Time
          </div>
          <div className="box-border w-full [flex:1_1_0] min-h-0 flex flex-col justify-center items-stretch">
            <TrendAreaChart series={TREND} height={192} max={TREND_MAX} />
          </div>
          <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
            {TREND_AXIS.map((a) => (
              <div key={a} className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                {a}
              </div>
            ))}
          </div>
        </div>
        {/* By type */}
        <div className="box-border [flex:1_1_0] min-w-0 h-full flex flex-col gap-[12px] p-[16px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]">
          <div className="text-[14px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
            Evidence by Type
          </div>
          <div className="box-border w-full [flex:1_1_0] flex flex-row gap-[16px] justify-start items-center">
            <DonutChart data={TYPES} size={130} thickness={20}>
              <div className="text-[20px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-center [white-space:nowrap]">
                3,842
              </div>
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-center [white-space:nowrap]">
                Total
              </div>
            </DonutChart>
            <div className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[8px] justify-start items-start">
              {TYPES.map((t) => (
                <div key={t.label} className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
                  <div className="text-[10px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]" style={{ color: t.color }}>
                    ● {t.label}
                  </div>
                  <div className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                    {t.display} ({t.pct})
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className="text-[10px]/[normal] box-border text-[#C084FC] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            View all categories ›
          </div>
        </div>
      </div>

      {/* Recent audit logs table */}
      <div className="box-border w-full [flex:1_1_0] flex flex-col gap-0 p-[14px_16px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px] overflow-hidden">
        <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
          <div className="text-[14px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
            Recent Audit Logs
          </div>
          <div className="text-[10px]/[normal] box-border text-[#A78BFA] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            View all logs
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
          <div key={r.entity} className="box-border w-full h-[40px] shrink-0 flex flex-row gap-0 justify-start items-center">
            <div className="box-border w-[160px] shrink-0 h-full flex flex-row gap-0 justify-start items-center">
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{r.time}</div>
            </div>
            <div className="box-border [flex:1_1_0] min-w-0 h-full flex flex-row gap-0 justify-start items-center">
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{r.actor}</div>
            </div>
            <div className="box-border w-[100px] shrink-0 h-full flex flex-row gap-0 justify-start items-center">
              <div className="text-[9px]/[normal] box-border text-[#8B5CF6] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{r.action}</div>
            </div>
            <div className="box-border w-[110px] shrink-0 h-full flex flex-row gap-0 justify-start items-center">
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{r.resource}</div>
            </div>
            <div className="box-border w-[110px] shrink-0 h-full flex flex-row gap-0 justify-start items-center">
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{r.entity}</div>
            </div>
            <div className="box-border w-[110px] shrink-0 h-full flex flex-row gap-0 justify-start items-center">
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{r.ip}</div>
            </div>
            <div className="box-border w-[95px] shrink-0 h-full flex flex-row gap-0 justify-start items-center">
              <div className="text-[9px]/[normal] box-border text-[#22C55E] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">Success</div>
            </div>
            <div className="box-border w-[55px] shrink-0 h-full flex flex-row gap-0 justify-start items-center">
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">▣</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
