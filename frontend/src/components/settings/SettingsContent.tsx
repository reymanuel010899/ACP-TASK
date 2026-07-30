/**
 * Settings — center column (matches the provided Settings screenshot).
 *
 * Dashboard `--ag-*` tokens for structure; accent hues literal. Built to the
 * richer screenshot layout (field grids, selects with icons, preference toggles
 * with icon tiles) using the Pencil export's exact colors and values.
 */

const TABS = ["General", "Team", "Notifications", "API & Webhooks", "Templates", "Data & Privacy", "Audit Logs", "Advanced"];

const REGIONAL: { label: string; value: string; icon: string }[] = [
  { label: "Language", value: "English (US)", icon: "⊕" },
  { label: "Timezone", value: "(GMT-04:00) America/New_York", icon: "◷" },
  { label: "Date Format", value: "May 19, 2024", icon: "▦" },
  { label: "Time Format", value: "12-hour (AM/PM)", icon: "◷" },
];

type Pref = { icon: string; name: string; desc: string; on: boolean };
const PREFERENCES: Pref[] = [
  { icon: "☾", name: "Dark Mode", desc: "Use dark theme across the platform", on: true },
  { icon: "☁", name: "Auto Save", desc: "Automatically save changes in forms", on: true },
  { icon: "▦", name: "Compact Mode", desc: "Use compact layout for dense information", on: false },
  { icon: "✓", name: "Confirm Actions", desc: "Show confirmation dialogs for important actions", on: true },
  { icon: "✦", name: "Animations", desc: "Enable UI animations and transitions", on: true },
  { icon: "▤", name: "Data Insights", desc: "Show smart insights and recommendations", on: true },
];

function Toggle({ on }: { on: boolean }) {
  return (
    <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-[8px] justify-start items-center">
      <div
        className={`box-border w-[38px] shrink-0 h-[21px] flex flex-row gap-0 p-[3px] items-center rounded-[11px] ${
          on ? "bg-[var(--ag-purple)] justify-end" : "bg-[#334155] justify-start"
        }`}
      >
        <div className="box-border w-[15px] shrink-0 h-[15px] bg-[#FFFFFF] rounded-full"></div>
      </div>
      <div className="text-[12px]/[normal] box-border text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
        ⌄
      </div>
    </div>
  );
}

function FieldLabel({ children }: { children: string }) {
  return (
    <div className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
      {children}
    </div>
  );
}

function Input({ label, value, chevron }: { label: string; value: string; chevron?: boolean }) {
  return (
    <div className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[5px] justify-start items-start">
      <FieldLabel>{label}</FieldLabel>
      <div className="box-border w-full h-[34px] shrink-0 flex flex-row gap-0 p-[0px_10px] justify-between items-center bg-[var(--ag-input-bg)] [border:1px_solid_var(--ag2-border)] rounded-[5px]">
        <div className="text-[10px]/[normal] box-border w-full text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [overflow:hidden] [text-overflow:ellipsis] [white-space:nowrap]">
          {value}
        </div>
        {chevron && (
          <div className="text-[11px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            ⌄
          </div>
        )}
      </div>
    </div>
  );
}

const CARD =
  "box-border w-full shrink-0 flex flex-col gap-[12px] p-[18px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]";
const CARD_TITLE =
  "text-[14px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]";
const CARD_DESC =
  "text-[10px]/[normal] box-border text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]";

export default function SettingsContent() {
  return (
    <div className="box-border w-full [flex:1_1_0] flex flex-col gap-[12px] p-[16px_30px_18px_30px] justify-start items-start">
      {/* Heading */}
      <div className="text-[24px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
        Settings
      </div>
      <div className="text-[12px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
        Manage your organization settings and preferences.
      </div>

      {/* Tabs */}
      <div className="box-border w-full h-[34px] shrink-0 flex flex-row gap-[30px] justify-start items-center [border-width:0px_0px_1px_0px] [border-style:solid] [border-color:var(--ag-divider)]">
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
                  ? "text-[10px]/[normal] box-border text-[#C084FC] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]"
                  : "text-[10px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
              }
            >
              {tab}
            </div>
          </div>
        ))}
      </div>

      {/* Organization Settings */}
      <div className={CARD}>
        <div className={CARD_TITLE}>Organization Settings</div>
        <div className={CARD_DESC}>Update your organization information and preferences.</div>
        <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[18px] justify-start items-start">
          {/* Logo */}
          <div className="box-border w-[132px] shrink-0 h-[128px] flex flex-col gap-[10px] p-[10px] justify-start items-start bg-[var(--ag-input-bg)] rounded-[6px]">
            <div className="box-border w-full [flex:1_1_0] flex flex-row gap-0 justify-center items-center bg-[#5B21D7] rounded-[6px]">
              <div className="text-[24px]/[normal] box-border text-[#FFFFFF] font-[Inter,system-ui,sans-serif] font-bold text-center [white-space:nowrap]">
                AC
              </div>
            </div>
            <div className="text-[10px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-center [white-space:nowrap]">
              Change Logo
            </div>
          </div>
          {/* Fields */}
          <div className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[10px] justify-start items-start">
            <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[18px] justify-start items-start">
              <Input label="Organization Name" value="Console Corp" />
              <Input label="Slug" value="console-corp" />
            </div>
            <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[18px] justify-start items-start">
              <Input label="Industry" value="Technology" chevron />
              <Input label="Website" value="https://console.com" />
            </div>
          </div>
        </div>
        <FieldLabel>Description</FieldLabel>
        <div className="box-border w-full h-[56px] shrink-0 flex flex-row gap-0 p-[10px_12px] justify-start items-start bg-[var(--ag-input-bg)] [border:1px_solid_var(--ag2-border)] rounded-[5px]">
          <div className="text-[10px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            Console Corp is building the future of agent collaboration and autonomous operations.
          </div>
        </div>
        <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-end items-center">
          <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-0 p-[9px_16px] justify-center items-center bg-[var(--ag-purple)] rounded-[6px]">
            <div className="text-[10px]/[normal] box-border text-[#FFFFFF] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
              Save Changes
            </div>
          </div>
        </div>
      </div>

      {/* Regional & Language */}
      <div className={CARD}>
        <div className={CARD_TITLE}>Regional &amp; Language</div>
        <div className={CARD_DESC}>Configure your region, language, and timezone preferences.</div>
        <div className="box-border w-full h-fit shrink-0 flex flex-col gap-[12px] justify-start items-start">
          {[REGIONAL.slice(0, 2), REGIONAL.slice(2, 4)].map((pair, ri) => (
            <div key={ri} className="box-border w-full h-fit shrink-0 flex flex-row gap-[18px] justify-start items-start">
              {pair.map((r) => (
                <div key={r.label} className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[5px] justify-start items-start">
                  <FieldLabel>{r.label}</FieldLabel>
                  <div className="box-border w-full h-[38px] shrink-0 flex flex-row gap-[8px] p-[0px_12px] justify-start items-center bg-[var(--ag-input-bg)] [border:1px_solid_var(--ag2-border)] rounded-[6px]">
                    <div className="text-[12px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                      {r.icon}
                    </div>
                    <div className="text-[11px]/[normal] box-border [flex:1_1_0] min-w-0 text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [overflow:hidden] [text-overflow:ellipsis] [white-space:nowrap]">
                      {r.value}
                    </div>
                    <div className="text-[11px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                      ⌄
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ))}
        </div>
      </div>

      {/* System Preferences */}
      <div className={CARD}>
        <div className={CARD_TITLE}>System Preferences</div>
        <div className={CARD_DESC}>Customize how Console works for your organization.</div>
        {[PREFERENCES.slice(0, 2), PREFERENCES.slice(2, 4), PREFERENCES.slice(4, 6)].map((pair, ri) => (
          <div key={ri} className="box-border w-full h-fit shrink-0 flex flex-row gap-[18px] justify-start items-start">
            {pair.map((p) => (
              <div key={p.name} className="box-border [flex:1_1_0] min-w-0 h-[46px] flex flex-row gap-[10px] justify-between items-center">
                <div className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-row gap-[10px] justify-start items-center">
                  <div className="box-border w-[34px] shrink-0 h-[34px] flex flex-row gap-0 justify-center items-center bg-[var(--ag-input-bg)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]">
                    <div className="text-[14px]/[normal] box-border text-[#A78BFA] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                      {p.icon}
                    </div>
                  </div>
                  <div className="box-border w-fit shrink-0 h-fit flex flex-col gap-[3px] justify-start items-start">
                    <div className="text-[10px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
                      {p.name}
                    </div>
                    <div className="text-[8px]/[normal] box-border text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                      {p.desc}
                    </div>
                  </div>
                </div>
                <Toggle on={p.on} />
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
