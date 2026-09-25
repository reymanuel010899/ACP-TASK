/**
 * Integrations — center column (matches the provided Integrations screenshot).
 *
 * Dashboard `--ag-*` tokens for structure; accent/brand hues literal. Brand
 * marks are rendered as colored glyph tiles (no external logo assets).
 */

import CapabilityFamilyControls from "./CapabilityFamilyControls";
import ConnectGoogleCard from "./ConnectGoogleCard";
import ConnectSlackCard from "./ConnectSlackCard";
import ConnectTwilioCard from "./ConnectTwilioCard";

const TABS = ["Overview", "All Integrations", "Connected", "Available", "Categories", "Webhooks", "Settings"];

const METRICS: { icon: string; iconColor: string; label: string; value: string; trend: string; trendColor: string }[] = [
  { icon: "▣", iconColor: "#8B5CF6", label: "Total Integrations", value: "42", trend: "↑ 16% vs last 30 days", trendColor: "#22C55E" },
  { icon: "✓", iconColor: "#22C55E", label: "Connected", value: "28", trend: "↑ 12% vs last 30 days", trendColor: "#22C55E" },
  { icon: "⛓", iconColor: "#3B82F6", label: "Available", value: "14", trend: "— No change", trendColor: "var(--ag-text-muted)" },
  { icon: "⌁", iconColor: "#06B6D4", label: "Webhooks", value: "8", trend: "↑ 33% vs last 30 days", trendColor: "#22C55E" },
  { icon: "♢", iconColor: "#22C55E", label: "Success Rate", value: "99.9%", trend: "↑ 0.3% vs last 30 days", trendColor: "#22C55E" },
];

type Integration = {
  name: string; category: string; glyph: string; color: string; desc: string;
  connected: boolean; date?: string; extra?: string;
};

const INTEGRATIONS: Integration[] = [
  { name: "Slack", category: "Communication", glyph: "#", color: "#E01E5A", desc: "Send notifications and updates to Slack channels.", connected: false },
  { name: "GitHub", category: "Development", glyph: "◉", color: "#E6E1EE", desc: "Sync repositories, issues, and pull requests.", connected: true, date: "May 15, 2024" },
  { name: "AWS", category: "Cloud", glyph: "aws", color: "#FF9900", desc: "Manage AWS resources and automate workflows.", connected: true, date: "May 10, 2024", extra: "+1" },
  { name: "Stripe", category: "Payments", glyph: "S", color: "#635BFF", desc: "Process payments and manage subscriptions.", connected: true, date: "May 8, 2024" },
  { name: "Google Workspace", category: "Productivity", glyph: "G", color: "#4285F4", desc: "Sync docs, sheets, and calendar events.", connected: true, date: "May 15, 2024", extra: "+1" },
  { name: "Notion", category: "Productivity", glyph: "N", color: "#E6E1EE", desc: "Sync pages and databases with Notion.", connected: true, date: "Apr 30, 2024" },
  { name: "Zapier", category: "Automation", glyph: "✳", color: "#FF4A00", desc: "Automate workflows between apps.", connected: true, date: "Apr 25, 2024" },
  { name: "SendGrid", category: "Email", glyph: "▦", color: "#1A82E2", desc: "Send transactional emails and manage templates.", connected: false },
  { name: "Datadog", category: "Monitoring", glyph: "◍", color: "#8B5CF6", desc: "Monitor infrastructure and application metrics.", connected: false },
  { name: "Twilio", category: "Communication", glyph: "◉", color: "#F22F46", desc: "Send SMS, voice, and WhatsApp messages.", connected: false },
  { name: "MongoDB Atlas", category: "Database", glyph: "●", color: "#00ED64", desc: "Connect to MongoDB Atlas databases.", connected: false },
  { name: "HubSpot", category: "CRM", glyph: "✲", color: "#FF7A59", desc: "Sync contacts, deals, and marketing data.", connected: false },
];

const PAGES = ["‹", "1", "2", "3", "4", "…", "6", "›"];

function IconTile({ glyph, color, size = 34 }: { glyph: string; color: string; size?: number }) {
  return (
    <div
      className="box-border shrink-0 flex flex-row gap-0 justify-center items-center bg-[var(--ag-input-bg)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]"
      style={{ width: size, height: size }}
    >
      <div
        className="text-[13px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-bold text-center [white-space:nowrap]"
        style={{ color }}
      >
        {glyph}
      </div>
    </div>
  );
}

export default function IntegrationsContent() {
  return (
    <div className="box-border w-full [flex:1_1_0] flex flex-col gap-[14px] p-[16px_20px_18px_20px] justify-start items-start">
      {/* Header */}
      <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-start">
        <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-[12px] justify-start items-center">
          <div className="text-[22px]/[normal] box-border text-[#A78BFA] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            ⛓
          </div>
          <div className="box-border w-fit shrink-0 h-fit flex flex-col gap-[4px] justify-start items-start">
            <div className="text-[24px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
              Integrations
            </div>
            <div className="text-[12px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
              Connect and manage third-party services and tools across your ecosystem.
            </div>
          </div>
        </div>
        <div className="box-border w-fit shrink-0 h-[36px] flex flex-row gap-[7px] p-[0px_16px] justify-center items-center bg-[var(--ag-purple)] rounded-[6px]">
          <div className="text-[12px]/[normal] box-border text-[#FFFFFF] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
            ＋ Add Integration
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="box-border w-full h-[34px] shrink-0 flex flex-row gap-[28px] justify-start items-center [border-width:0px_0px_1px_0px] [border-style:solid] [border-color:var(--ag-divider)]">
        {TABS.map((tab, i) => (
          <div
            key={tab}
            className={
              i === 0
                ? "box-border h-full flex flex-row items-center [border-width:0px_0px_2px_0px] [border-style:solid] [border-color:#A78BFA]"
                : "box-border h-full flex flex-row items-center"
            }
          >
            <div
              className={
                i === 0
                  ? "text-[11px]/[normal] box-border text-[#C084FC] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]"
                  : "text-[11px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
              }
            >
              {tab}
            </div>
          </div>
        ))}
      </div>

      {/* Metrics */}
      <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[10px] justify-start items-start">
        {METRICS.map((m) => (
          <div key={m.label} className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[8px] p-[14px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]">
            <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[8px] justify-start items-center">
              <IconTile glyph={m.icon} color={m.iconColor} size={26} />
              <div className="text-[10px]/[normal] box-border [flex:1_1_0] min-w-0 text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-semibold text-left [overflow:hidden] [text-overflow:ellipsis] [white-space:nowrap]">
                {m.label}
              </div>
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

      {/* Filter bar */}
      <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[10px] justify-start items-center">
        <div className="box-border [flex:1_1_0] min-w-0 h-[36px] flex flex-row gap-[8px] p-[0px_12px] justify-start items-center bg-[var(--ag-input-bg)] [border:1px_solid_var(--ag2-border)] rounded-[6px]">
          <div className="text-[13px]/[normal] box-border text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">⌕</div>
          <div className="text-[11px]/[normal] box-border text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            Search integrations...
          </div>
        </div>
        {["All Categories", "All Status"].map((s) => (
          <div key={s} className="box-border w-[150px] shrink-0 h-[36px] flex flex-row gap-0 p-[0px_12px] justify-between items-center bg-[var(--ag-input-bg)] [border:1px_solid_var(--ag2-border)] rounded-[6px]">
            <div className="text-[11px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{s}</div>
            <div className="text-[11px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">⌄</div>
          </div>
        ))}
        <div className="box-border w-fit shrink-0 h-[36px] flex flex-row gap-[7px] p-[0px_14px] justify-center items-center bg-[var(--ag-input-bg)] [border:1px_solid_var(--ag2-border)] rounded-[6px]">
          <div className="text-[11px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">⚱ Filters</div>
        </div>
      </div>

      {/* Grid header */}
      <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
        <div className="text-[14px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
          All Integrations (42)
        </div>
        <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-[10px] justify-start items-center">
          <div className="text-[10px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            Sort by: Recently Added ⌄
          </div>
          <div className="text-[12px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">▦ ☰</div>
        </div>
      </div>

      {/* Cards grid */}
      <div className="box-border w-full [flex:1_1_0] [display:grid] [grid-template-columns:repeat(4,minmax(0,1fr))] gap-[12px]">
        {INTEGRATIONS.map((it) =>
          it.name === "Slack" ? (
            <ConnectSlackCard key={it.name} />
          ) : it.name === "Google Workspace" ? (
            <ConnectGoogleCard key={it.name} layout="grid" />
          ) : it.name === "Twilio" ? (
            <ConnectTwilioCard key={it.name} />
          ) : (
            <div key={it.name} className="box-border w-full h-fit flex flex-col gap-[10px] p-[13px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]">
            <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[9px] justify-start items-start">
              <IconTile glyph={it.glyph} color={it.color} size={34} />
              <div className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[2px] justify-start items-start">
                <div className="text-[12px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
                  {it.name}
                </div>
                <div className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                  {it.category}
                </div>
              </div>
              <div className="text-[12px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">•••</div>
            </div>
            {it.connected && (
              <div className="box-border w-fit h-fit shrink-0 flex flex-row gap-0 p-[3px_8px] justify-start items-start bg-[#0B3B2B] rounded-[4px]">
                <div className="text-[9px]/[normal] box-border text-[#22C55E] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">Connected</div>
              </div>
            )}
            <div className="text-[10px]/[15px] box-border w-full text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left">
              {it.desc}
            </div>
            {it.connected ? (
              <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
                <div className="text-[9px]/[normal] box-border text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                  Connected on {it.date}
                </div>
                <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-[3px] justify-end items-center">
                  <div className="box-border w-[18px] shrink-0 h-[18px] bg-[#D99975] rounded-full [border:1.5px_solid_var(--ag-card)]"></div>
                  {it.extra && (
                    <div className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                      {it.extra}
                    </div>
                  )}
                </div>
              </div>
            ) : (
              <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-0 p-[7px_16px] justify-center items-center bg-[var(--ag-purple)] rounded-[6px]">
                <div className="text-[10px]/[normal] box-border text-[#FFFFFF] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">Connect</div>
              </div>
            )}
            </div>
          ),
        )}
      </div>

      {/* What this account currently allows, and the switch that halts it. */}
      <div className="box-border w-full h-fit shrink-0">
        <CapabilityFamilyControls />
      </div>

      {/* Pagination */}
      <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[8px] justify-center items-center">
        {PAGES.map((p, i) => {
          const active = p === "1";
          return (
            <div
              key={i}
              className={`box-border w-[28px] shrink-0 h-[26px] flex flex-row gap-0 justify-center items-center ${
                active ? "bg-[var(--ag-purple)]" : "bg-[var(--ag-input-bg)]"
              } rounded-[5px]`}
            >
              <div
                className={`text-[10px]/[normal] box-border ${
                  active ? "text-[#FFFFFF] font-semibold" : "text-[var(--ag-text-secondary)] font-normal"
                } font-[Inter,system-ui,sans-serif] text-left [white-space:nowrap]`}
              >
                {p}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
