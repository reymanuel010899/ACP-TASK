/**
 * Billing — center column (matches the provided Billing screenshot).
 *
 * Dashboard `--ag-*` tokens for structure; accent hues literal. The spend
 * summary is a real canvas donut chart.
 */

import DonutChart, { type DonutSegment } from "@/components/charts/DonutChart";

const TABS = ["Overview", "Invoices", "Payment Methods", "Usage", "Plans & Limits", "Settings"];

const METRICS: { icon: string; iconColor: string; label: string; value: string; sub: string; subColor: string }[] = [
  { icon: "▤", iconColor: "#8B5CF6", label: "Current Balance", value: "$2,540.75", sub: "Due on Jun 1, 2024", subColor: "var(--ag-text-muted)" },
  { icon: "◉", iconColor: "#22C55E", label: "This Month's Spend", value: "$12,540.75", sub: "↑ 18.6% vs last month", subColor: "#22C55E" },
  { icon: "▣", iconColor: "#8B5CF6", label: "Credits Remaining", value: "$430.00", sub: "Available credits", subColor: "var(--ag-text-muted)" },
  { icon: "▦", iconColor: "#F59E0B", label: "Next Invoice", value: "Jun 1, 2024", sub: "Invoice #INV-2024-0601", subColor: "var(--ag-text-muted)" },
];

const USAGE: { icon: string; color: string; name: string; used: string; pct: number }[] = [
  { icon: "▤", color: "#8B5CF6", name: "API Requests", used: "1.25M / 2M", pct: 62.5 },
  { icon: "▣", color: "#22C55E", name: "Agent Executions", used: "18,540 / 30,000", pct: 61.8 },
  { icon: "▤", color: "#F59E0B", name: "Storage", used: "512 GB / 1 TB", pct: 50 },
  { icon: "☁", color: "#3B82F6", name: "Data Transfer", used: "320 GB / 1 TB", pct: 32 },
];

const SPEND: (DonutSegment & { amount: string; pct: string })[] = [
  { label: "API Requests", value: 6250, amount: "$6,250.00", pct: "49.8%", color: "#8B5CF6" },
  { label: "Agent Executions", value: 3420, amount: "$3,420.00", pct: "27.3%", color: "#22C55E" },
  { label: "Storage", value: 1780, amount: "$1,780.00", pct: "14.2%", color: "#F59E0B" },
  { label: "Data Transfer", value: 1090.75, amount: "$1,090.75", pct: "8.7%", color: "#3B82F6" },
];

const INV_COLS = ["Invoice ID", "Date", "Status", "Amount", "Due Date", "Actions"];
type Invoice = { id: string; date: string; amount: string; due: string };
const INVOICES: Invoice[] = [
  { id: "INV-2024-0501", date: "May 1, 2024", amount: "$10,580.00", due: "May 31, 2024" },
  { id: "INV-2024-0401", date: "Apr 1, 2024", amount: "$9,620.50", due: "Apr 30, 2024" },
  { id: "INV-2024-0301", date: "Mar 1, 2024", amount: "$8,980.75", due: "Mar 31, 2024" },
  { id: "INV-2024-0201", date: "Feb 1, 2024", amount: "$8,540.00", due: "Feb 29, 2024" },
  { id: "INV-2024-0101", date: "Jan 1, 2024", amount: "$7,890.25", due: "Jan 31, 2024" },
];

const CARD =
  "box-border flex flex-col gap-[14px] p-[16px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]";
const CARD_TITLE =
  "text-[15px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]";

function IconTile({ glyph, color, size = 34 }: { glyph: string; color: string; size?: number }) {
  return (
    <div className="box-border shrink-0 flex flex-row gap-0 justify-center items-center bg-[var(--ag-input-bg)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]" style={{ width: size, height: size }}>
      <div className="text-[15px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-normal text-center [white-space:nowrap]" style={{ color }}>{glyph}</div>
    </div>
  );
}

export default function BillingContent() {
  return (
    <div className="box-border w-full [flex:1_1_0] flex flex-col gap-[14px] p-[16px_20px_18px_20px] justify-start items-start">
      {/* Header */}
      <div className="box-border w-fit shrink-0 h-fit flex flex-col gap-[4px] justify-start items-start">
        <div className="text-[24px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">Billing</div>
        <div className="text-[12px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
          Manage your subscription, usage, invoices, and payment methods.
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
      <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[12px] justify-start items-stretch">
        {METRICS.map((m) => (
          <div key={m.label} className={`${CARD} [flex:1_1_0] min-w-0 gap-[8px]`}>
            <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-start">
              <div className="text-[10px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{m.label}</div>
              <IconTile glyph={m.icon} color={m.iconColor} size={30} />
            </div>
            <div className="text-[22px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">{m.value}</div>
            <div className="text-[9px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]" style={{ color: m.subColor }}>{m.sub}</div>
          </div>
        ))}
      </div>

      {/* Usage + Spend */}
      <div className="box-border w-full h-[320px] shrink-0 flex flex-row gap-[12px] justify-start items-stretch">
        {/* Usage Overview */}
        <div className={`${CARD} [flex:1.4_1_0] min-w-0`}>
          <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
            <div className={CARD_TITLE}>Usage Overview</div>
            <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-0 p-[6px_10px] justify-between items-center bg-[var(--ag-input-bg)] [border:1px_solid_var(--ag-card-border)] rounded-[6px]">
              <div className="text-[10px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">This Month ⌄</div>
            </div>
          </div>
          <div className="box-border w-full [flex:1_1_0] flex flex-col gap-[16px] justify-center items-start">
            {USAGE.map((u) => (
              <div key={u.name} className="box-border w-full h-fit shrink-0 flex flex-row gap-[12px] justify-start items-center">
                <IconTile glyph={u.icon} color={u.color} size={34} />
                <div className="box-border w-[110px] shrink-0 h-fit flex flex-col gap-[3px] justify-start items-start">
                  <div className="text-[11px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">{u.name}</div>
                  <div className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{u.used}</div>
                </div>
                <div className="box-border [flex:1_1_0] min-w-0 h-[6px] bg-[var(--ag-input-bg)] rounded-[3px] overflow-hidden">
                  <div className="box-border h-full rounded-[3px]" style={{ width: `${u.pct}%`, backgroundColor: u.color }}></div>
                </div>
                <div className="text-[10px]/[normal] box-border w-[42px] shrink-0 text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-semibold text-right [white-space:nowrap]">{u.pct}%</div>
              </div>
            ))}
          </div>
        </div>
        {/* Spend Summary */}
        <div className={`${CARD} [flex:1_1_0] min-w-0`}>
          <div className={CARD_TITLE}>Spend Summary</div>
          <div className="box-border w-full [flex:1_1_0] flex flex-col gap-[12px] justify-start items-center">
            <DonutChart data={SPEND} size={130} thickness={20}>
              <div className="text-[15px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-center [white-space:nowrap]">$12,540.75</div>
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-center [white-space:nowrap]">Total Spend</div>
            </DonutChart>
            <div className="box-border w-full h-fit shrink-0 flex flex-col gap-[8px] justify-start items-start">
              {SPEND.map((s) => (
                <div key={s.label} className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
                  <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-[7px] justify-start items-center">
                    <div className="box-border w-[8px] shrink-0 h-[8px] rounded-full" style={{ backgroundColor: s.color }}></div>
                    <div className="text-[10px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{s.label}</div>
                  </div>
                  <div className="text-[10px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{s.amount} ({s.pct})</div>
                </div>
              ))}
            </div>
          </div>
          <div className="box-border w-full h-[32px] shrink-0 flex flex-row gap-0 justify-center items-center bg-[var(--ag-input-bg)] [border:1px_solid_var(--ag-card-border)] rounded-[6px]">
            <div className="text-[10px]/[normal] box-border text-[#C084FC] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">View Usage Details ›</div>
          </div>
        </div>
      </div>

      {/* Recent Invoices */}
      <div className={`${CARD} w-full [flex:1_1_0] gap-[10px]`}>
        <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
          <div className={CARD_TITLE}>Recent Invoices</div>
          <div className="text-[10px]/[normal] box-border text-[#C084FC] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">View all invoices</div>
        </div>
        {/* Header */}
        <div className="box-border w-full h-[30px] shrink-0 flex flex-row gap-0 justify-start items-center">
          {INV_COLS.map((c, i) => (
            <div key={c} className={`box-border ${i === 3 ? "[flex:1_1_0] min-w-0" : ["w-[150px]", "w-[120px]", "w-[100px]", "", "w-[130px]", "w-[130px]"][i] + " shrink-0"} h-full flex flex-row gap-0 justify-start items-center`}>
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">{c}</div>
            </div>
          ))}
        </div>
        {INVOICES.map((inv) => (
          <div key={inv.id} className="box-border w-full h-[34px] shrink-0 flex flex-row gap-0 justify-start items-center [border-width:1px_0px_0px_0px] [border-style:solid] [border-color:var(--ag2-border)]">
            <div className="box-border w-[150px] shrink-0 h-full flex flex-row gap-0 justify-start items-center">
              <div className="text-[10px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{inv.id}</div>
            </div>
            <div className="box-border w-[120px] shrink-0 h-full flex flex-row gap-0 justify-start items-center">
              <div className="text-[10px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{inv.date}</div>
            </div>
            <div className="box-border w-[100px] shrink-0 h-full flex flex-row gap-0 justify-start items-center">
              <div className="box-border w-fit h-fit shrink-0 flex flex-row gap-0 p-[3px_9px] justify-start items-start bg-[#0B3B2B] rounded-[4px]">
                <div className="text-[9px]/[normal] box-border text-[#22C55E] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">Paid</div>
              </div>
            </div>
            <div className="box-border [flex:1_1_0] min-w-0 h-full flex flex-row gap-0 justify-start items-center">
              <div className="text-[10px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">{inv.amount}</div>
            </div>
            <div className="box-border w-[130px] shrink-0 h-full flex flex-row gap-0 justify-start items-center">
              <div className="text-[10px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{inv.due}</div>
            </div>
            <div className="box-border w-[130px] shrink-0 h-full flex flex-row gap-[8px] justify-start items-center">
              <div className="box-border w-[26px] shrink-0 h-[24px] flex flex-row gap-0 justify-center items-center bg-[var(--ag-input-bg)] [border:1px_solid_var(--ag-card-border)] rounded-[5px]">
                <div className="text-[10px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">⬇</div>
              </div>
              <div className="box-border w-fit shrink-0 h-[24px] flex flex-row gap-0 p-[0px_12px] justify-center items-center bg-[var(--ag-input-bg)] [border:1px_solid_var(--ag-card-border)] rounded-[5px]">
                <div className="text-[9px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">View</div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
