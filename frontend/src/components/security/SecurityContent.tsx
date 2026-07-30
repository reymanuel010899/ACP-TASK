/**
 * Security — center column (matches the provided Security screenshot).
 *
 * Dashboard `--ag-*` tokens for structure; accent/status hues literal. The
 * threat-activity line and severity donut are real canvas charts.
 */

import TrendAreaChart, { type TrendSeries } from "@/components/charts/TrendAreaChart";
import DonutChart, { type DonutSegment } from "@/components/charts/DonutChart";

const TABS = ["Overview", "Threats", "Alerts", "Access Control", "Compliance", "Audit Logs", "Settings"];

const METRICS: { icon: string; iconColor: string; label: string; value: string; trend: string }[] = [
  { icon: "🛡", iconColor: "#EF4444", label: "Active Threats", value: "3", trend: "↓ 25% vs last 30 days" },
  { icon: "⚠", iconColor: "#F59E0B", label: "Critical Alerts", value: "1", trend: "↓ 50% vs last 30 days" },
  { icon: "🔒", iconColor: "#3B82F6", label: "Blocked Attempts", value: "1,248", trend: "↑ 18% vs last 30 days" },
  { icon: "👥", iconColor: "#8B5CF6", label: "Users at Risk", value: "2", trend: "↓ 33% vs last 30 days" },
];

const SCORE: DonutSegment[] = [
  { label: "Score", value: 92, color: "#22C55E" },
  { label: "Rest", value: 8, color: "#334155" },
];

const TREND_MAX = 100;
const TREND: TrendSeries[] = [
  { label: "Threats Detected", color: "#EF4444", points: [25, 40, 35, 80, 45, 30, 15] },
];
const TREND_AXIS = ["May 13", "May 14", "May 15", "May 16", "May 17", "May 18", "May 19"];
const Y_AXIS = ["100", "80", "60", "40", "20", "0"];

const SEVERITY: (DonutSegment & { pct: string })[] = [
  { label: "Critical", value: 3, pct: "13%", color: "#EF4444" },
  { label: "High", value: 8, pct: "35%", color: "#F59E0B" },
  { label: "Medium", value: 7, pct: "30%", color: "#EAB308" },
  { label: "Low", value: 3, pct: "13%", color: "#3B82F6" },
  { label: "Info", value: 2, pct: "9%", color: "#94A3B8" },
];

const ALERT_COLS = ["Alert", "Severity", "Source", "Detected At", "Status", "Actions"];
type Alert = { name: string; severity: string; sevColor: string; source: string; at: string; status: string; statusColor: string };
const ALERTS: Alert[] = [
  { name: "Multiple failed login attempts", severity: "High", sevColor: "#EF4444", source: "Authentication", at: "May 19, 2024 10:24 AM", status: "Active", statusColor: "#EF4444" },
  { name: "Unusual access from new location", severity: "Medium", sevColor: "#F59E0B", source: "Access Monitor", at: "May 19, 2024 09:15 AM", status: "Investigating", statusColor: "#F59E0B" },
  { name: "Suspicious API activity detected", severity: "High", sevColor: "#EF4444", source: "API Gateway", at: "May 18, 2024 11:32 PM", status: "Active", statusColor: "#EF4444" },
  { name: "Malware detected in file upload", severity: "Critical", sevColor: "#DC2626", source: "File Scanner", at: "May 18, 2024 08:45 PM", status: "Quarantined", statusColor: "#F59E0B" },
  { name: "Privilege escalation attempt", severity: "Medium", sevColor: "#F59E0B", source: "Access Control", at: "May 18, 2024 06:12 PM", status: "Resolved", statusColor: "#22C55E" },
];

const VECTORS: { icon: string; label: string; pct: number; color: string }[] = [
  { icon: "⚡", label: "Brute Force", pct: 42, color: "#EF4444" },
  { icon: "⛓", label: "Credential Stuffing", pct: 28, color: "#F59E0B" },
  { icon: "◈", label: "API Abuse", pct: 17, color: "#EAB308" },
  { icon: "◍", label: "Malicious IPs", pct: 9, color: "#3B82F6" },
  { icon: "●", label: "Other", pct: 4, color: "#94A3B8" },
];

const CARD =
  "box-border flex flex-col gap-[12px] p-[16px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]";
const CARD_TITLE =
  "text-[14px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]";

function SevBadge({ label, color }: { label: string; color: string }) {
  return (
    <div className="box-border w-fit h-fit shrink-0 flex flex-row gap-0 p-[3px_8px] justify-start items-start rounded-[4px]" style={{ backgroundColor: `${color}22` }}>
      <div className="text-[9px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]" style={{ color }}>
        {label}
      </div>
    </div>
  );
}

export default function SecurityContent() {
  return (
    <div className="box-border w-full [flex:1_1_0] flex flex-col gap-[14px] p-[16px_20px_18px_20px] justify-start items-start">
      {/* Header */}
      <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-start">
        <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-[12px] justify-start items-center">
          <div className="text-[22px]/[normal] box-border text-[#A78BFA] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">🛡</div>
          <div className="box-border w-fit shrink-0 h-fit flex flex-col gap-[4px] justify-start items-start">
            <div className="text-[24px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
              Security
            </div>
            <div className="text-[12px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
              Monitor, detect, and respond to security threats across your ecosystem.
            </div>
          </div>
        </div>
        <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-[10px] justify-start items-start">
          <div className="box-border w-fit shrink-0 h-[34px] flex flex-row gap-[6px] p-[0px_14px] justify-center items-center bg-[var(--ag-purple)] rounded-[6px]">
            <div className="text-[11px]/[normal] box-border text-[#FFFFFF] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">⚙ Security Settings</div>
          </div>
          <div className="box-border w-fit shrink-0 h-[34px] flex flex-row gap-[6px] p-[0px_14px] justify-center items-center bg-[var(--ag-input-bg)] [border:1px_solid_var(--ag-card-border)] rounded-[6px]">
            <div className="text-[11px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">⬇ Download Report</div>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="box-border w-full h-[34px] shrink-0 flex flex-row gap-[28px] justify-start items-center [border-width:0px_0px_1px_0px] [border-style:solid] [border-color:var(--ag-divider)]">
        {TABS.map((tab, i) => (
          <div key={tab} className={i === 0 ? "box-border h-full flex flex-row items-center [border-width:0px_0px_2px_0px] [border-style:solid] [border-color:#A78BFA]" : "box-border h-full flex flex-row items-center"}>
            <div className={i === 0 ? "text-[11px]/[normal] box-border text-[#C084FC] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]" : "text-[11px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"}>
              {tab}
            </div>
          </div>
        ))}
      </div>

      {/* Metrics */}
      <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[10px] justify-start items-stretch">
        {/* Security Score */}
        <div className={`${CARD} w-[220px] shrink-0 [flex-direction:row] items-center gap-[12px]`}>
          <DonutChart data={SCORE} size={72} thickness={9}>
            <div className="text-[16px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-center [white-space:nowrap]">92</div>
            <div className="text-[8px]/[normal] box-border text-[#22C55E] font-[Inter,system-ui,sans-serif] font-normal text-center [white-space:nowrap]">Excellent</div>
          </DonutChart>
          <div className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[6px] justify-center items-start">
            <div className="text-[10px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">Security Score</div>
            <div className="text-[13px]/[normal] box-border text-[#22C55E] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">↑ 8 pts</div>
            <div className="text-[9px]/[normal] box-border text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">vs last 30 days</div>
          </div>
        </div>
        {/* Others */}
        {METRICS.map((m) => (
          <div key={m.label} className={`${CARD} [flex:1_1_0] min-w-0 gap-[8px]`}>
            <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[8px] justify-start items-center">
              <div className="text-[15px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]" style={{ color: m.iconColor }}>{m.icon}</div>
              <div className="text-[10px]/[normal] box-border [flex:1_1_0] min-w-0 text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-semibold text-left [overflow:hidden] [text-overflow:ellipsis] [white-space:nowrap]">{m.label}</div>
            </div>
            <div className="text-[24px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">{m.value}</div>
            <div className="text-[9px]/[normal] box-border text-[#22C55E] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{m.trend}</div>
          </div>
        ))}
      </div>

      {/* Analytics row */}
      <div className="box-border w-full h-[280px] shrink-0 flex flex-row gap-[12px] justify-start items-stretch">
        {/* Threat Activity */}
        <div className={`${CARD} [flex:1.5_1_0] min-w-0`}>
          <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
            <div className={CARD_TITLE}>Threat Activity</div>
            <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-0 p-[5px_10px] justify-between items-center bg-[var(--ag-input-bg)] [border:1px_solid_var(--ag-card-border)] rounded-[6px]">
              <div className="text-[10px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">Last 7 days ⌄</div>
            </div>
          </div>
          <div className="box-border w-full [flex:1_1_0] min-h-0 flex flex-row gap-[8px] justify-start items-stretch">
            <div className="box-border w-fit shrink-0 h-full flex flex-col justify-between items-end py-[4px]">
              {Y_AXIS.map((y) => (
                <div key={y} className="text-[8px]/[normal] box-border text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-normal text-right [white-space:nowrap]">{y}</div>
              ))}
            </div>
            <div className="box-border [flex:1_1_0] min-w-0 h-full flex flex-col justify-center items-stretch">
              <TrendAreaChart series={TREND} height={170} max={TREND_MAX} />
            </div>
          </div>
          <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center pl-[24px]">
            {TREND_AXIS.map((a) => (
              <div key={a} className="text-[8px]/[normal] box-border text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{a}</div>
            ))}
          </div>
          <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[18px] justify-start items-center">
            {[{ l: "Threats Detected", c: "#EF4444" }, { l: "Blocked Attempts", c: "#8B5CF6" }].map((s) => (
              <div key={s.l} className="box-border w-fit h-fit shrink-0 flex flex-row gap-[6px] justify-start items-center">
                <div className="box-border w-[8px] shrink-0 h-[8px] rounded-full" style={{ backgroundColor: s.c }}></div>
                <div className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{s.l}</div>
              </div>
            ))}
          </div>
        </div>
        {/* Threats by Severity */}
        <div className={`${CARD} [flex:1_1_0] min-w-0`}>
          <div className={CARD_TITLE}>Threats by Severity</div>
          <div className="box-border w-full [flex:1_1_0] flex flex-row gap-[16px] justify-start items-center">
            <DonutChart data={SEVERITY} size={120} thickness={18}>
              <div className="text-[22px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-center [white-space:nowrap]">23</div>
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-center [white-space:nowrap]">Total</div>
            </DonutChart>
            <div className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[10px] justify-start items-start">
              {SEVERITY.map((s) => (
                <div key={s.label} className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
                  <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-[7px] justify-start items-center">
                    <div className="box-border w-[8px] shrink-0 h-[8px] rounded-full" style={{ backgroundColor: s.color }}></div>
                    <div className="text-[10px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{s.label}</div>
                  </div>
                  <div className="text-[10px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{s.value} ({s.pct})</div>
                </div>
              ))}
            </div>
          </div>
          <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-center items-center">
            <div className="text-[10px]/[normal] box-border text-[#C084FC] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">View all threats ›</div>
          </div>
        </div>
      </div>

      {/* Bottom row */}
      <div className="box-border w-full [flex:1_1_0] flex flex-row gap-[12px] justify-start items-stretch">
        {/* Recent Security Alerts */}
        <div className={`${CARD} [flex:1.5_1_0] min-w-0`}>
          <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
            <div className={CARD_TITLE}>Recent Security Alerts</div>
            <div className="text-[10px]/[normal] box-border text-[#C084FC] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">View all alerts</div>
          </div>
          {/* Header */}
          <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-start items-center">
            {ALERT_COLS.map((c, i) => (
              <div key={c} className={`box-border ${i === 0 ? "[flex:1_1_0] min-w-0" : ["w-[80px]", "w-[110px]", "w-[150px]", "w-[110px]", "w-[55px]"][i - 1] + " shrink-0"} h-full flex flex-row gap-0 justify-start items-center`}>
                <div className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">{c}</div>
              </div>
            ))}
          </div>
          {ALERTS.map((a) => (
            <div key={a.name} className="box-border w-full h-[30px] shrink-0 flex flex-row gap-0 justify-start items-center">
              <div className="box-border [flex:1_1_0] min-w-0 h-full flex flex-row gap-0 justify-start items-center">
                <div className="text-[10px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{a.name}</div>
              </div>
              <div className="box-border w-[80px] shrink-0 h-full flex flex-row gap-0 justify-start items-center"><SevBadge label={a.severity} color={a.sevColor} /></div>
              <div className="box-border w-[110px] shrink-0 h-full flex flex-row gap-0 justify-start items-center">
                <div className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{a.source}</div>
              </div>
              <div className="box-border w-[150px] shrink-0 h-full flex flex-row gap-0 justify-start items-center">
                <div className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{a.at}</div>
              </div>
              <div className="box-border w-[110px] shrink-0 h-full flex flex-row gap-[5px] justify-start items-center">
                <div className="text-[9px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]" style={{ color: a.statusColor }}>● {a.status}</div>
              </div>
              <div className="box-border w-[55px] shrink-0 h-full flex flex-row gap-0 justify-start items-center">
                <div className="text-[10px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">•••</div>
              </div>
            </div>
          ))}
          <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-center items-center">
            <div className="text-[10px]/[normal] box-border text-[#C084FC] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">View all alerts ›</div>
          </div>
        </div>
        {/* Top Attack Vectors */}
        <div className={`${CARD} [flex:1_1_0] min-w-0`}>
          <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
            <div className={CARD_TITLE}>Top Attack Vectors</div>
            <div className="text-[10px]/[normal] box-border text-[#C084FC] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">View report</div>
          </div>
          {VECTORS.map((v) => (
            <div key={v.label} className="box-border w-full h-fit shrink-0 flex flex-row gap-[10px] justify-start items-center">
              <div className="box-border w-[26px] shrink-0 h-[26px] flex flex-row gap-0 justify-center items-center bg-[var(--ag-input-bg)] [border:1px_solid_var(--ag-card-border)] rounded-[6px]">
                <div className="text-[12px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-normal text-center [white-space:nowrap]" style={{ color: v.color }}>{v.icon}</div>
              </div>
              <div className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[4px] justify-start items-start">
                <div className="text-[10px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{v.label}</div>
                <div className="box-border w-full h-[4px] shrink-0 bg-[var(--ag-input-bg)] rounded-[2px] overflow-hidden">
                  <div className="box-border h-full rounded-[2px]" style={{ width: `${v.pct}%`, backgroundColor: v.color }}></div>
                </div>
              </div>
              <div className="text-[10px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">{v.pct}%</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
