/**
 * Security — right rail (matches the provided Security screenshot): security
 * posture, compliance status, and recent audit logs. Dashboard `--ag-*` tokens
 * for structure; accent/status hues literal.
 */

const POSTURE: { label: string; status: string; color: string }[] = [
  { label: "Multi-Factor Authentication", status: "Enforced", color: "#22C55E" },
  { label: "Single Sign-On (SSO)", status: "Enabled", color: "#22C55E" },
  { label: "Encryption", status: "AES-256", color: "var(--ag-text-secondary)" },
  { label: "Vulnerability Scanning", status: "Active", color: "var(--ag-text-secondary)" },
  { label: "Audit Logging", status: "Enabled", color: "var(--ag-text-secondary)" },
  { label: "Backup & Recovery", status: "Active", color: "var(--ag-text-secondary)" },
];

const COMPLIANCE: { label: string; status: string; ok: boolean }[] = [
  { label: "SOC 2 Type II", status: "Compliant", ok: true },
  { label: "ISO 27001", status: "Compliant", ok: true },
  { label: "GDPR", status: "Compliant", ok: true },
  { label: "HIPAA", status: "In Progress", ok: false },
];

const AUDIT: { icon: string; color: string; title: string; by: string; date: string }[] = [
  { icon: "✓", color: "#22C55E", title: "Admin login", by: "by Rey Ferreras", date: "May 19, 2024 10:24 AM" },
  { icon: "♙", color: "#3B82F6", title: "Role updated", by: "by Ana Martinez", date: "May 19, 2024 09:15 AM" },
  { icon: "⌁", color: "#F59E0B", title: "API key created", by: "by System", date: "May 18, 2024 08:45 PM" },
  { icon: "🛡", color: "#8B5CF6", title: "Policy updated", by: "by Sofia Rodriguez", date: "May 18, 2024 06:30 PM" },
];

const CARD =
  "box-border w-full shrink-0 flex flex-col gap-[12px] p-[14px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]";
const TITLE =
  "text-[14px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]";
const VIEWALL =
  "text-[10px]/[normal] box-border text-[#C084FC] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]";

export default function SecurityRightPanel() {
  return (
    <div className="box-border w-[300px] shrink-0 h-full flex flex-col gap-[12px] p-[14px] justify-start items-start bg-[var(--ag-right-bg)] [border-width:0px_0px_0px_1px] [border-style:solid] [border-color:var(--ag-divider)] overflow-y-auto">
      {/* Security Posture */}
      <div className={CARD}>
        <div className={TITLE}>Security Posture</div>
        {POSTURE.map((p) => (
          <div key={p.label} className="box-border w-full h-fit shrink-0 flex flex-row gap-[9px] justify-start items-center">
            <div className="text-[11px]/[normal] box-border text-[#22C55E] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">✓</div>
            <div className="text-[10px]/[normal] box-border [flex:1_1_0] min-w-0 text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{p.label}</div>
            <div className="text-[10px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]" style={{ color: p.color }}>{p.status}</div>
          </div>
        ))}
        <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-center items-center">
          <div className={VIEWALL}>View Security Settings →</div>
        </div>
      </div>

      {/* Compliance Status */}
      <div className={CARD}>
        <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
          <div className={TITLE}>Compliance Status</div>
          <div className={VIEWALL}>View all</div>
        </div>
        {COMPLIANCE.map((c) => (
          <div key={c.label} className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
            <div className="text-[11px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{c.label}</div>
            <div
              className="box-border w-fit h-fit shrink-0 flex flex-row gap-[5px] p-[3px_8px] justify-start items-center rounded-[4px]"
              style={{ backgroundColor: c.ok ? "#0B3B2B" : "#4A3210" }}
            >
              <div className="text-[9px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]" style={{ color: c.ok ? "#22C55E" : "#F59E0B" }}>
                {c.status}
              </div>
              <div className="text-[9px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]" style={{ color: c.ok ? "#22C55E" : "#F59E0B" }}>
                {c.ok ? "✓" : "◷"}
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Recent Audit Logs */}
      <div className="box-border w-full [flex:1_1_0] flex flex-col gap-[11px] p-[14px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]">
        <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
          <div className={TITLE}>Recent Audit Logs</div>
          <div className={VIEWALL}>View all</div>
        </div>
        {AUDIT.map((a) => (
          <div key={a.title} className="box-border w-full h-fit shrink-0 flex flex-row gap-[9px] justify-start items-center">
            <div className="box-border w-[26px] shrink-0 h-[26px] flex flex-row gap-0 justify-center items-center bg-[var(--ag-input-bg)] [border:1px_solid_var(--ag-card-border)] rounded-[6px]">
              <div className="text-[11px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-normal text-center [white-space:nowrap]" style={{ color: a.color }}>{a.icon}</div>
            </div>
            <div className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[3px] justify-start items-start">
              <div className="text-[10px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">{a.title}</div>
              <div className="text-[8px]/[normal] box-border text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{a.by}</div>
            </div>
            <div className="text-[8px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-right [white-space:nowrap]">{a.date}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
