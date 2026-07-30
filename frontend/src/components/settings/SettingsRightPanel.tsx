/**
 * Settings — right rail (matches the provided Settings screenshot): account
 * information, subscription plan, storage usage, and danger zone. Dashboard
 * `--ag-*` tokens for structure; accent hues literal.
 */

const ACCOUNT_ROWS: { icon: string; label: string; value?: string; valueColor?: string }[] = [
  { icon: "🔒", label: "Change Password" },
  { icon: "🛡", label: "Two-Factor Authentication", value: "Enabled", valueColor: "#22C55E" },
  { icon: "🖥", label: "Active Sessions", value: "4", valueColor: "var(--ag-text-secondary)" },
];

const FEATURES = ["Unlimited Agents", "Advanced Security", "Custom Integrations", "Priority Support", "SLA 99.9% Uptime"];

const STORAGE: { label: string; value: string; color: string }[] = [
  { label: "Documents", value: "142.4 GB", color: "#8B5CF6" },
  { label: "Logs", value: "68.7 GB", color: "#3B82F6" },
  { label: "Backups", value: "37.5 GB", color: "#22C55E" },
];

const CARD =
  "box-border w-full shrink-0 flex flex-col gap-[12px] p-[14px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]";
const TITLE =
  "text-[14px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]";

export default function SettingsRightPanel() {
  return (
    <div className="box-border w-[300px] shrink-0 h-full flex flex-col gap-[12px] p-[14px] justify-start items-start bg-[var(--ag-right-bg)] [border-width:0px_0px_0px_1px] [border-style:solid] [border-color:var(--ag-divider)] overflow-y-auto">
      {/* Account Information */}
      <div className={CARD}>
        <div className={TITLE}>Account Information</div>
        <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[10px] justify-start items-center">
          <div className="box-border w-[44px] shrink-0 h-[44px] bg-[#D99975] rounded-full"></div>
          <div className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[3px] justify-start items-start">
            <div className="text-[12px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
              Rey Ferreras
            </div>
            <div className="text-[10px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
              admin@console.com
            </div>
            <div className="box-border w-fit h-fit shrink-0 flex flex-row gap-0 p-[3px_7px] justify-start items-start bg-[#2A1859] rounded-[4px]">
              <div className="text-[9px]/[normal] box-border text-[#C69AFF] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
                Super Admin
              </div>
            </div>
          </div>
        </div>
        {ACCOUNT_ROWS.map((r) => (
          <div key={r.label} className="box-border w-full h-fit shrink-0 flex flex-row gap-[8px] p-[9px_10px] justify-start items-center bg-[var(--ag-input-bg)] [border:1px_solid_var(--ag-card-border)] rounded-[6px]">
            <div className="text-[11px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
              {r.icon}
            </div>
            <div className="text-[10px]/[normal] box-border [flex:1_1_0] min-w-0 text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
              {r.label}
            </div>
            {r.value && (
              <div className="text-[10px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]" style={{ color: r.valueColor }}>
                {r.value}
              </div>
            )}
            <div className="text-[11px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
              ›
            </div>
          </div>
        ))}
      </div>

      {/* Subscription Plan */}
      <div className={CARD}>
        <div className={TITLE}>Subscription Plan</div>
        <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[10px] justify-start items-center">
          <div className="box-border w-[36px] shrink-0 h-[36px] flex flex-row gap-0 justify-center items-center bg-[#2A1859] rounded-[8px]">
            <div className="text-[16px]/[normal] box-border text-[#B276FF] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
              ✦
            </div>
          </div>
          <div className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-row gap-0 justify-between items-center">
            <div className="text-[13px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
              Enterprise Plan
            </div>
            <div className="text-[10px]/[normal] box-border text-[#22C55E] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
              Active
            </div>
          </div>
        </div>
        <div className="box-border w-full h-fit shrink-0 flex flex-col gap-[7px] justify-start items-start">
          {FEATURES.map((f) => (
            <div key={f} className="box-border w-full h-fit shrink-0 flex flex-row gap-[8px] justify-start items-center">
              <div className="text-[11px]/[normal] box-border text-[#22C55E] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                ✓
              </div>
              <div className="text-[11px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                {f}
              </div>
            </div>
          ))}
        </div>
        <div className="box-border w-full h-[34px] shrink-0 flex flex-row gap-0 justify-center items-center bg-[var(--ag-input-bg)] [border:1px_solid_var(--ag-card-border)] rounded-[6px]">
          <div className="text-[11px]/[normal] box-border text-[#C084FC] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
            Manage Subscription
          </div>
        </div>
      </div>

      {/* Storage Usage */}
      <div className={CARD}>
        <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
          <div className={TITLE}>Storage Usage</div>
          <div className="text-[10px]/[normal] box-border text-[#C084FC] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            View Details
          </div>
        </div>
        <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
          <div className="text-[10px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            248.6 GB of 1 TB used
          </div>
          <div className="text-[10px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            24.9%
          </div>
        </div>
        <div className="box-border w-full h-[6px] shrink-0 bg-[var(--ag-input-bg)] rounded-[3px] overflow-hidden">
          <div className="box-border w-[24.9%] h-full bg-[var(--ag-purple)] rounded-[3px]"></div>
        </div>
        {STORAGE.map((s) => (
          <div key={s.label} className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
            <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-[8px] justify-start items-center">
              <div className="box-border w-[8px] shrink-0 h-[8px] rounded-full" style={{ backgroundColor: s.color }}></div>
              <div className="text-[10px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                {s.label}
              </div>
            </div>
            <div className="text-[10px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
              {s.value}
            </div>
          </div>
        ))}
      </div>

      {/* Danger Zone */}
      <div className="box-border w-full [flex:1_1_0] flex flex-col gap-[10px] p-[14px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]">
        <div className="text-[14px]/[normal] box-border text-[#EF4444] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
          Danger Zone
        </div>
        <div className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
          These actions are irreversible. Please proceed with caution.
        </div>
        <div className="box-border w-full h-[34px] shrink-0 flex flex-row gap-[6px] justify-center items-center [border:1px_solid_#EF4444] rounded-[5px]">
          <div className="text-[10px]/[normal] box-border text-[#EF4444] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
            🗑 Delete Organization
          </div>
        </div>
      </div>
    </div>
  );
}
