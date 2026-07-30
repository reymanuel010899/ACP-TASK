/**
 * Contracts — center column (Pencil "Contracts" design).
 *
 * Dashboard `--ag-*` design language: card/border/text tokens are theme vars;
 * accent + status hues stay literal. The design used Geist for a few headings;
 * this app ships Inter everywhere, so we keep Inter for consistency.
 */

const TABS = ["All Contracts", "Active", "Pending", "Expired", "Draft", "Archived"];

const METRICS: { label: string; value: string; trend: string; trendColor: string }[] = [
  { label: "Total Contracts", value: "128", trend: "↑ 18% vs last 30 days", trendColor: "#6D3CE0" },
  { label: "Active Contracts", value: "68", trend: "↑ 14% vs last 30 days", trendColor: "#06B6D4" },
  { label: "Total Value", value: "$2,450,680", trend: "↑ 22% vs last 30 days", trendColor: "#22C55E" },
  { label: "Pending Signature", value: "12", trend: "Requires action", trendColor: "#F59E0B" },
  { label: "Expiring Soon", value: "7", trend: "Next 30 days", trendColor: "#EC4899" },
];

const SELECTS = [
  { label: "All Status", width: "w-[110px]" },
  { label: "All Types", width: "w-[105px]" },
  { label: "All Parties", width: "w-[130px]" },
  { label: "More Filters", width: "w-[110px]" },
];

const COLS: { label: string; width: string; flex?: boolean; alignEnd?: boolean }[] = [
  { label: "Contract", width: "w-[225px]", flex: true },
  { label: "Parties", width: "w-[180px]" },
  { label: "Type", width: "w-[88px]" },
  { label: "Value", width: "w-[87px]" },
  { label: "Status", width: "w-[90px]" },
  { label: "Start Date", width: "w-[88px]" },
  { label: "End Date", width: "w-[88px]" },
  { label: "Actions", width: "w-[45px]", alignEnd: true },
];

const ACTIVE = "#22C55E";
const PENDING = "#F59E0B";
const COMPLETED = "#3B82F6";

type Contract = {
  name: string;
  id: string;
  party: string;
  type: string;
  value: string;
  status: string;
  statusColor: string;
  start: string;
  end: string;
};

const CONTRACTS: Contract[] = [
  { name: "Web Development Agreement", id: "C-884", party: "DevCraft Labs", type: "Service", value: "$24,500.00", status: "● Active", statusColor: ACTIVE, start: "May 1, 2024", end: "Oct 31, 2024" },
  { name: "Marketing Campaign Contract", id: "C-883", party: "Marketify Agency", type: "Service", value: "$18,000.00", status: "● Active", statusColor: ACTIVE, start: "Apr 15, 2024", end: "Jul 15, 2024" },
  { name: "AI Analytics Platform License", id: "C-882", party: "DataMind AI", type: "License", value: "$36,000.00", status: "● Pending", statusColor: PENDING, start: "May 20, 2024", end: "May 19, 2025" },
  { name: "Cloud Infrastructure Agreement", id: "C-881", party: "Amazon Web Services", type: "Service", value: "$12,750.00", status: "● Active", statusColor: ACTIVE, start: "Apr 1, 2024", end: "Mar 31, 2025" },
  { name: "Consulting Services Agreement", id: "C-880", party: "ConsultPro", type: "Service", value: "$8,500.00", status: "● Completed", statusColor: COMPLETED, start: "Jan 10, 2024", end: "Apr 10, 2024" },
  { name: "Data Processing Agreement", id: "C-879", party: "SecureData Inc.", type: "DPA", value: "$0.00", status: "● Active", statusColor: ACTIVE, start: "Mar 5, 2024", end: "Mar 4, 2025" },
  { name: "Software Subscription Agreement", id: "C-878", party: "Atlassian", type: "Subscription", value: "$6,239.88", status: "● Active", statusColor: ACTIVE, start: "Feb 1, 2024", end: "Jan 31, 2025" },
];

export default function ContractsContent() {
  return (
    <div className="box-border w-full [flex:1_1_0] flex flex-col gap-[14px] p-[16px_28px_20px_28px] justify-start items-start">
      {/* Header */}
      <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
        <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-[12px] justify-start items-center">
          <div className="box-border w-[30px] shrink-0 h-[30px] flex flex-row gap-0 justify-center items-center bg-[#25124F] rounded-[7px]"></div>
          <div className="box-border w-fit shrink-0 h-fit flex flex-col gap-[4px] justify-start items-start">
            <div className="text-[24px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
              Contracts
            </div>
            <div className="text-[12px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
              Manage all contracts across your ecosystem.
            </div>
          </div>
        </div>
        <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-[10px] justify-start items-start">
          {["Export", "Filters"].map((b) => (
            <div key={b} className="box-border w-fit shrink-0 h-[34px] flex flex-row gap-[7px] p-[0px_14px] justify-start items-center bg-[var(--ag-input-bg)] [border:1px_solid_var(--ag2-border)] rounded-[6px]">
              <div className="text-[12px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
                {b}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Tabs */}
      <div className="box-border w-full h-[38px] shrink-0 flex flex-row gap-[30px] justify-start items-center [border-width:0px_0px_1px_0px] [border-style:solid] [border-color:var(--ag-divider)]">
        {TABS.map((tab, i) => (
          <div
            key={tab}
            className={
              i === 0
                ? "text-[12px]/[normal] box-border text-[#A78BFA] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]"
                : "text-[12px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
            }
          >
            {tab}
          </div>
        ))}
      </div>

      {/* Metrics */}
      <div className="box-border w-full h-[112px] shrink-0 flex flex-row gap-[10px] justify-start items-start">
        {METRICS.map((m) => (
          <div key={m.label} className="box-border [flex:1_1_0] h-full flex flex-col gap-[9px] p-[14px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[7px]">
            <div className="text-[11px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
              {m.label}
            </div>
            <div className="text-[23px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
              {m.value}
            </div>
            <div
              className="text-[10px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
              style={{ color: m.trendColor }}
            >
              {m.trend}
            </div>
          </div>
        ))}
      </div>

      {/* Filters */}
      <div className="box-border w-full h-[38px] shrink-0 flex flex-row gap-[10px] justify-start items-start">
        <div className="box-border w-[290px] shrink-0 h-full flex flex-row gap-[8px] p-[0px_12px] justify-start items-center bg-[var(--ag-input-bg)] [border:1px_solid_var(--ag2-border)] rounded-[6px]">
          <div className="text-[13px]/[normal] box-border text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            ⌕
          </div>
          <div className="text-[11px]/[normal] box-border text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            Search contracts by name, ID, parties...
          </div>
        </div>
        {SELECTS.map((s) => (
          <div key={s.label} className={`box-border ${s.width} shrink-0 h-full flex flex-row gap-0 p-[0px_12px] justify-between items-center bg-[var(--ag-input-bg)] [border:1px_solid_var(--ag2-border)] rounded-[6px]`}>
            <div className="text-[11px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
              {s.label}
            </div>
            <div className="text-[11px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
              ⌄
            </div>
          </div>
        ))}
      </div>

      {/* Table */}
      <div className="box-border w-full [flex:1_1_0] flex flex-col gap-0 justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[7px] overflow-hidden">
        {/* Header */}
        <div className="box-border w-full h-[42px] shrink-0 flex flex-row gap-0 p-[0px_16px] justify-start items-center [border-width:0px_0px_1px_0px] [border-style:solid] [border-color:var(--ag-card-border)]">
          {COLS.map((c) => (
            <div
              key={c.label}
              className={`box-border ${c.flex ? "[flex:1_1_0] min-w-0" : `${c.width} shrink-0`} h-full flex flex-row gap-0 ${c.alignEnd ? "justify-end" : "justify-start"} items-center`}
            >
              <div className="text-[10px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
                {c.label}
              </div>
            </div>
          ))}
        </div>
        {/* Rows */}
        {CONTRACTS.map((c) => (
          <div key={c.id} className="box-border w-full h-[54px] shrink-0 flex flex-row gap-0 p-[0px_16px] justify-start items-center [border-width:0px_0px_1px_0px] [border-style:solid] [border-color:var(--ag2-border)]">
            {/* Contract */}
            <div className="box-border [flex:1_1_0] min-w-0 h-full flex flex-col gap-[3px] justify-center items-start">
              <div className="text-[11px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
                {c.name}
              </div>
              <div className="text-[10px]/[normal] box-border text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                {c.id}
              </div>
            </div>
            {/* Parties */}
            <div className="box-border w-[180px] shrink-0 h-full flex flex-row gap-[7px] justify-start items-center">
              <div className="box-border w-[22px] shrink-0 h-[22px] bg-[#1E40AF] rounded-full"></div>
              <div className="text-[10px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                {c.party}
              </div>
            </div>
            {/* Type */}
            <div className="box-border w-[88px] shrink-0 h-full flex flex-row gap-0 justify-start items-center">
              <div className="text-[10px]/[normal] box-border text-[#B894FF] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                {c.type}
              </div>
            </div>
            {/* Value */}
            <div className="box-border w-[87px] shrink-0 h-full flex flex-col gap-0 justify-center items-start">
              <div className="text-[10px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
                {c.value}
              </div>
            </div>
            {/* Status */}
            <div className="box-border w-[90px] shrink-0 h-full flex flex-row gap-0 justify-start items-center">
              <div
                className="text-[10px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
                style={{ color: c.statusColor }}
              >
                {c.status}
              </div>
            </div>
            {/* Start */}
            <div className="box-border w-[88px] shrink-0 h-full flex flex-row gap-0 justify-start items-center">
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                {c.start}
              </div>
            </div>
            {/* End */}
            <div className="box-border w-[88px] shrink-0 h-full flex flex-row gap-0 justify-start items-center">
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                {c.end}
              </div>
            </div>
            {/* Actions */}
            <div className="box-border w-[45px] shrink-0 h-full flex flex-row gap-0 justify-end items-center">
              <div className="text-[13px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                •••
              </div>
            </div>
          </div>
        ))}
        {/* Footer */}
        <div className="box-border w-full h-[40px] shrink-0 flex flex-row gap-0 p-[0px_16px] justify-between items-center">
          <div className="text-[10px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            Showing 1 to 8 of 128 contracts
          </div>
          <div className="text-[11px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            ‹ 1 2 3 4 … 16 ›
          </div>
        </div>
      </div>
    </div>
  );
}
