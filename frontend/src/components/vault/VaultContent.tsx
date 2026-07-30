/**
 * Credentials Vault — center column (Pencil "Credentials Vault" design).
 *
 * Structural colors (text / panels / borders) go through the shared `--ag2-*`
 * theme vars so the screen tracks the light/dark toggle like every other page;
 * accent + status colors (purple, greens, amber, the primary button) are kept
 * as literals, matching the convention in the sibling screens.
 */

const METRICS: { label: string; value: string; trend: string; trendColor: string }[] = [
  { label: "Total Credentials", value: "142", trend: "↑ 15% vs last 30 days", trendColor: "#35D78B" },
  { label: "Active Credentials", value: "120", trend: "↑ 15% vs last 30 days", trendColor: "#35D78B" },
  { label: "Expiring Soon", value: "8", trend: "View all", trendColor: "#FBBF24" },
  { label: "Access Requests", value: "12", trend: "↑ 15% vs last 30 days", trendColor: "#35D78B" },
  { label: "Connected Services", value: "28", trend: "↑ 15% vs last 30 days", trendColor: "#35D78B" },
];

const TABS = ["Overview", "All Credentials", "Access Requests", "Policies", "Activity", "Settings"];

const FILTERS: { label: string; value: string }[] = [
  { label: "Category", value: "All Categorys ⌄" },
  { label: "Type", value: "All Types ⌄" },
  { label: "Environment", value: "All Environments ⌄" },
  { label: "Status", value: "All Statuss ⌄" },
  { label: "Access Level", value: "All Access Levels ⌄" },
];

type Credential = { icon: string; name: string };

// 12 credentials laid out across 4 columns of 3 (matching the design grid).
const CREDENTIAL_COLUMNS: Credential[][] = [
  [
    { icon: "aws", name: "AWS Production" },
    { icon: "☁", name: "GCP Billing Admin" },
    { icon: "◉", name: "GitHub Main Org" },
  ],
  [
    { icon: "✿", name: "Slack Workspace" },
    { icon: "S", name: "Stripe Live" },
    { icon: "▦", name: "SendGrid API" },
  ],
  [
    { icon: "●", name: "MongoDB Cluster" },
    { icon: "▤", name: "PostgreSQL DB" },
    { icon: "◎", name: "OpenAI API" },
  ],
  [
    { icon: "◒", name: "Docker Hub" },
    { icon: "☁", name: "Cloudflare DNS" },
    { icon: "✦", name: "Kubernetes Cluster" },
  ],
];

export default function VaultContent() {
  return (
    <div className="box-border w-full [flex:1_1_0] flex flex-col gap-[12px] p-[15px_18px] justify-start items-start">
      {/* Header */}
      <div className="box-border w-fit h-fit shrink-0 flex flex-col gap-[5px] justify-start items-start">
        <div className="text-[21px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
          ◈ Credentials Vault
        </div>
        <div className="text-[12px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
          Securely store, manage, and control access to all your credentials.
        </div>
      </div>

      {/* Tabs */}
      <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[30px] p-[8px_0px] justify-start items-start [border-width:0px_0px_1px_0px] [border-style:solid] [border-color:var(--ag2-border)]">
        {TABS.map((tab, i) => (
          <div
            key={tab}
            className={
              i === 0
                ? "text-[11px]/[normal] box-border text-[#B267FF] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]"
                : "text-[11px]/[normal] box-border text-[var(--ag2-nav)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
            }
          >
            {tab}
          </div>
        ))}
      </div>

      {/* Metrics */}
      <div className="box-border w-full h-[110px] shrink-0 flex flex-row gap-[10px] justify-start items-start">
        {METRICS.map((m) => (
          <div
            key={m.label}
            className="box-border [flex:1_1_0] h-full flex flex-col gap-[8px] p-[14px] justify-start items-start bg-[var(--ag2-panel)] [border:1px_solid_var(--ag2-border)] rounded-[8px]"
          >
            <div className="text-[10px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
              {m.label}
            </div>
            <div className="text-[22px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
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

      {/* Body: filters + credential grid */}
      <div className="box-border w-full [flex:1_1_0] flex flex-row gap-[12px] justify-start items-start">
        {/* Filters */}
        <div className="box-border w-[220px] shrink-0 h-full flex flex-col gap-[13px] p-[16px] justify-start items-start bg-[var(--ag2-panel)] [border:1px_solid_var(--ag2-border)] rounded-[8px]">
          <div className="text-[11px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            ⌕ Search credentials...
          </div>
          <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
            <div className="text-[12px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
              Filters
            </div>
            <div className="text-[10px]/[normal] box-border text-[#B267FF] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
              Clear all
            </div>
          </div>
          {FILTERS.map((f) => (
            <div key={f.label} className="box-border w-full h-fit shrink-0 flex flex-col gap-[6px] justify-start items-start">
              <div className="text-[10px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                {f.label}
              </div>
              <div className="text-[11px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                {f.value}
              </div>
            </div>
          ))}
          <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 p-[11px_8px] justify-center items-start bg-[#5D20DC] rounded-[6px]">
            <div className="text-[11px]/[normal] box-border text-[#F4F2FF] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
              ＋ Add Credential
            </div>
          </div>
        </div>

        {/* Credential grid */}
        <div className="box-border [flex:1_1_0] h-full flex flex-col gap-[10px] justify-start items-start">
          <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-start">
            <div className="text-[14px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
              All Credentials (142)
            </div>
            <div className="text-[10px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
              Sort by: Recently Updated ⌄
            </div>
          </div>
          <div className="box-border w-full [flex:1_1_0] flex flex-row gap-[10px] justify-start items-start">
            {CREDENTIAL_COLUMNS.map((column, ci) => (
              <div key={ci} className="box-border [flex:1_1_0] h-full flex flex-col gap-[10px] justify-start items-start">
                {column.map((cred) => (
                  <div
                    key={cred.name}
                    className="box-border w-full [flex:1_1_0] flex flex-col gap-[8px] p-[13px] justify-start items-start bg-[var(--ag2-input-deep)] [border:1px_solid_var(--ag2-border)] rounded-[8px]"
                  >
                    <div className="text-[20px]/[normal] box-border text-[#B678FF] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
                      {cred.icon}
                    </div>
                    <div className="text-[11px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
                      {cred.name}
                    </div>
                    <div className="text-[10px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                      API Key
                    </div>
                    <div className="box-border w-fit h-fit shrink-0 flex flex-row gap-0 p-[4px_6px] justify-start items-start bg-[#073C31] rounded-[4px]">
                      <div className="text-[9px]/[normal] box-border text-[#35D78B] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                        Production
                      </div>
                    </div>
                    <div className="text-[10px]/[normal] box-border text-[#35D78B] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                      ● Active
                    </div>
                    <div className="text-[9px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                      Updated 2d ago
                    </div>
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
