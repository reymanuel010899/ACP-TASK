/**
 * Capabilities — center column (Pencil "Capabilities" design).
 *
 * This screen uses the dashboard `--ag-*` design language (card/border/text
 * tokens) rather than the `--ag2-*` set, matching the sibling dashboard
 * components. Structural colors go through the theme vars; accent/status hues
 * (and the colored capability icon tiles) stay literal, the same convention
 * StatsRow.tsx uses.
 */

const METRICS: { icon: string; iconColor: string; label: string; value: string; delta: string }[] = [
  { icon: "♟", iconColor: "#3B82F6", label: "Total Capabilities", value: "248", delta: "↑ 12% vs last 30 days" },
  { icon: "▣", iconColor: "#06B6D4", label: "Active Capabilities", value: "186", delta: "↑ 15% vs last 30 days" },
  { icon: "▧", iconColor: "#F59E0B", label: "Used in Tasks", value: "1,248", delta: "↑ 18% vs last 30 days" },
  { icon: "♧", iconColor: "#22C55E", label: "Verified Capabilities", value: "132", delta: "↑ 20% vs last 30 days" },
  { icon: "★", iconColor: "#FBBF24", label: "Avg. Rating", value: "4.8 / 5", delta: "↑ 0.3 vs last 30 days" },
];

const TABS = ["All Capabilities", "My Capabilities", "Categories"];

const COLUMNS: { key: string; label: string; width: string; flex?: boolean }[] = [
  { key: "capability", label: "Capability", width: "w-[390px]", flex: true },
  { key: "category", label: "Category", width: "w-[130px]" },
  { key: "used", label: "Used In", width: "w-[100px]" },
  { key: "rating", label: "Rating", width: "w-[140px]" },
  { key: "status", label: "Status", width: "w-[110px]" },
  { key: "actions", label: "Actions", width: "w-[60px]" },
];

type Status = { label: string; bg: string; color: string };
const ACTIVE: Status = { label: "Active", bg: "#123827", color: "#22C55E" };
const DRAFT: Status = { label: "Draft", bg: "#132A52", color: "#3B82F6" };
const PENDING: Status = { label: "Pending Review", bg: "#352712", color: "#F59E0B" };

type Row = {
  name: string;
  desc: string;
  iconBox: string;
  icon: string;
  category: string;
  usage: string;
  rating: string;
  status: Status;
};

const ROWS: Row[] = [
  { name: "Kubernetes Deployment", desc: "Deploy and manage applications on Kubernetes clusters.", iconBox: "#1D4ED8", icon: "✧", category: "DevOps", usage: "342 tasks", rating: "★ 4.9", status: ACTIVE },
  { name: "AWS Infrastructure Setup", desc: "Provision and configure AWS infrastructure.", iconBox: "#14532D", icon: "☁", category: "Cloud", usage: "289 tasks", rating: "★ 4.8", status: ACTIVE },
  { name: "Security Vulnerability Assessment", desc: "Identify and analyze security vulnerabilities.", iconBox: "#4C1D95", icon: "♢", category: "Security", usage: "198 tasks", rating: "★ 4.7", status: ACTIVE },
  { name: "API Development", desc: "Design and build robust RESTful APIs.", iconBox: "#4A1641", icon: "</>", category: "Development", usage: "456 tasks", rating: "★ 4.8", status: ACTIVE },
  { name: "Financial Analysis", desc: "Analyze financial data and generate insights.", iconBox: "#4A3210", icon: "▥", category: "Finance", usage: "312 tasks", rating: "★ 4.6", status: ACTIVE },
  { name: "UI/UX Design", desc: "Create modern and intuitive user interfaces.", iconBox: "#16464C", icon: "✎", category: "Design", usage: "267 tasks", rating: "★ 4.9", status: DRAFT },
  { name: "Digital Marketing Campaign", desc: "Plan and execute digital marketing campaigns.", iconBox: "#3A1A62", icon: "⚑", category: "Marketing", usage: "185 tasks", rating: "★ 4.5", status: PENDING },
];

const PAGES = ["‹", "1", "2", "3", "…", "›"];

export default function CapabilitiesContent() {
  return (
    <div className="box-border w-full [flex:1_1_0] flex flex-col gap-[14px] p-[14px_18px_18px_18px] justify-start items-start">
      {/* Heading */}
      <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-start">
        <div className="box-border w-fit shrink-0 h-fit flex flex-col gap-[4px] justify-start items-start">
          <div className="text-[24px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
            Capabilities
          </div>
          <div className="text-[12px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            Manage capabilities available in your ecosystem.
          </div>
        </div>
        <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-[8px] p-[11px_16px] justify-start items-center bg-[var(--ag-purple)] rounded-[7px]">
          <div className="text-[17px]/[normal] box-border text-[#FFFFFF] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            +
          </div>
          <div className="text-[12px]/[normal] box-border text-[#FFFFFF] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
            Create Capability
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[28px] p-[0px_0px_8px_0px] justify-start items-start [border-width:0px_0px_1px_0px] [border-style:solid] [border-color:var(--ag2-border)]">
        {TABS.map((tab, i) => (
          <div
            key={tab}
            className={
              i === 0
                ? "text-[12px]/[normal] box-border text-[#8B5CF6] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]"
                : "text-[12px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
            }
          >
            {tab}
          </div>
        ))}
      </div>

      {/* Metrics */}
      <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[10px] justify-start items-start">
        {METRICS.map((m) => (
          <div
            key={m.label}
            className="box-border [flex:1_1_0] h-[82px] flex flex-col gap-[7px] p-[13px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]"
          >
            <div className="box-border w-fit h-fit shrink-0 flex flex-row gap-[9px] justify-start items-center">
              <div
                className="text-[18px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
                style={{ color: m.iconColor }}
              >
                {m.icon}
              </div>
              <div className="box-border w-fit shrink-0 h-fit flex flex-col gap-[3px] justify-start items-start">
                <div className="text-[10px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                  {m.label}
                </div>
                <div className="text-[21px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
                  {m.value}
                </div>
              </div>
            </div>
            <div className="text-[9px]/[normal] box-border text-[#22C55E] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
              {m.delta}
            </div>
          </div>
        ))}
      </div>

      {/* Filters bar */}
      <div className="box-border w-full h-[54px] shrink-0 flex flex-row gap-[12px] p-[10px] justify-start items-center bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]">
        <div className="box-border [flex:1_1_0] h-fit flex flex-row gap-[8px] p-[8px_10px] justify-start items-center bg-[var(--ag-input-bg)] [border:1px_solid_var(--ag2-border)] rounded-[6px]">
          <div className="text-[17px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            ⌕
          </div>
          <div className="text-[11px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            Search capabilities by name, keyword or tag...
          </div>
        </div>
        {[
          { label: "All Categories" },
          { label: "All Status" },
        ].map((sel) => (
          <div
            key={sel.label}
            className="box-border w-[165px] shrink-0 h-fit flex flex-row gap-0 p-[8px_11px] justify-between items-center bg-[var(--ag-input-bg)] [border:1px_solid_var(--ag2-border)] rounded-[6px]"
          >
            <div className="text-[11px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
              {sel.label}
            </div>
            <div className="text-[13px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
              ⌄
            </div>
          </div>
        ))}
        <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-[7px] p-[8px_12px] justify-start items-center bg-[#15142C] [border:1px_solid_#302C52] rounded-[6px]">
          <div className="text-[13px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            ⚱
          </div>
          <div className="text-[11px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            Filters
          </div>
        </div>
      </div>

      {/* Table */}
      <div className="box-border w-full [flex:1_1_0] flex flex-col gap-0 justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px] overflow-hidden">
        {/* Header */}
        <div className="box-border w-full h-[38px] shrink-0 flex flex-row gap-0 justify-start items-start [border-width:0px_0px_1px_0px] [border-style:solid] [border-color:var(--ag2-border)]">
          {COLUMNS.map((c) => (
            <div
              key={c.key}
              className={`box-border ${c.flex ? "[flex:1_1_0] min-w-0" : `${c.width} shrink-0`} h-full flex flex-row gap-0 p-[0px_8px] justify-start items-center`}
            >
              <div className="text-[10px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
                {c.label} ↕
              </div>
            </div>
          ))}
        </div>
        {/* Rows */}
        {ROWS.map((r) => (
          <div
            key={r.name}
            className="box-border w-full h-[61px] shrink-0 flex flex-row gap-0 justify-start items-start [border-width:0px_0px_1px_0px] [border-style:solid] [border-color:var(--ag2-border)]"
          >
            {/* Capability */}
            <div className="box-border [flex:1_1_0] min-w-0 h-full flex flex-row gap-0 p-[0px_8px] justify-start items-center">
              <div
                className="box-border w-[36px] shrink-0 h-[36px] flex flex-row gap-0 justify-center items-center rounded-[7px]"
                style={{ backgroundColor: r.iconBox }}
              >
                <div className="text-[19px]/[normal] box-border text-[#FFFFFF] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
                  {r.icon}
                </div>
              </div>
              <div className="box-border w-fit shrink-0 h-fit flex flex-col gap-[3px] p-[0px_10px] justify-start items-start">
                <div className="box-border w-fit h-fit shrink-0 flex flex-row gap-[6px] justify-start items-center">
                  <div className="text-[12px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
                    {r.name}
                  </div>
                  <div className="text-[8px]/[normal] box-border text-[#8B5CF6] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                    ●
                  </div>
                </div>
                <div className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                  {r.desc}
                </div>
              </div>
            </div>
            {/* Category */}
            <div className="box-border w-[130px] shrink-0 h-full flex flex-row gap-0 p-[0px_8px] justify-start items-center">
              <div className="text-[11px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                {r.category}
              </div>
            </div>
            {/* Used In */}
            <div className="box-border w-[100px] shrink-0 h-full flex flex-row gap-0 p-[0px_8px] justify-start items-center">
              <div className="text-[11px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                {r.usage}
              </div>
            </div>
            {/* Rating */}
            <div className="box-border w-[140px] shrink-0 h-full flex flex-row gap-0 p-[0px_8px] justify-start items-center">
              <div className="box-border w-fit shrink-0 h-fit flex flex-col gap-[5px] justify-start items-start">
                <div className="text-[11px]/[normal] box-border text-[#FBBF24] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                  {r.rating}
                </div>
                <div className="box-border w-[110px] h-[3px] shrink-0 bg-[#6D3CE0] rounded-[2px]"></div>
              </div>
            </div>
            {/* Status */}
            <div className="box-border w-[110px] shrink-0 h-full flex flex-row gap-0 p-[0px_8px] justify-start items-center">
              <div
                className="box-border w-fit shrink-0 h-fit flex flex-row gap-0 p-[5px_9px] justify-start items-start rounded-[5px]"
                style={{ backgroundColor: r.status.bg }}
              >
                <div
                  className="text-[9px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]"
                  style={{ color: r.status.color }}
                >
                  {r.status.label}
                </div>
              </div>
            </div>
            {/* Actions */}
            <div className="box-border w-[60px] shrink-0 h-full flex flex-row gap-0 p-[0px_8px] justify-start items-center">
              <div className="box-border w-[34px] shrink-0 h-[30px] flex flex-row gap-0 justify-center items-center bg-[#16152D] [border:1px_solid_var(--ag2-border)] rounded-[6px]">
                <div className="text-[11px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                  •••
                </div>
              </div>
            </div>
          </div>
        ))}
        {/* Footer */}
        <div className="box-border w-full [flex:1_1_0] flex flex-row gap-0 p-[0px_16px] justify-between items-center">
          <div className="text-[10px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            Showing 1 to 10 of 248 capabilities
          </div>
          <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-[8px] justify-start items-center">
            {PAGES.map((p, i) => {
              const active = p === "1";
              return (
                <div
                  key={i}
                  className={`box-border w-[30px] shrink-0 h-[27px] flex flex-row gap-0 justify-center items-center ${
                    active ? "bg-[#6D3CE0]" : "bg-[#14132B]"
                  } rounded-[5px]`}
                >
                  <div
                    className={`text-[10px]/[normal] box-border ${
                      active
                        ? "text-[#FFFFFF] font-semibold"
                        : "text-[var(--ag-text-secondary)] font-normal"
                    } font-[Inter,system-ui,sans-serif] text-left [white-space:nowrap]`}
                  >
                    {p}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
