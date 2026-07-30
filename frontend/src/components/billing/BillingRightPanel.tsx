/**
 * Billing — right rail (matches the provided Billing screenshot): plan summary,
 * payment method, billing details, quick actions, and support. Dashboard
 * `--ag-*` tokens for structure; accent hues literal.
 */

const FEATURES = ["Unlimited Agents", "Advanced Security", "Custom Integrations", "Priority Support", "SLA 99.9% Uptime"];

const DETAILS: { label: string; value: string }[] = [
  { label: "Billing Email", value: "billing@console.com" },
  { label: "Billing Address", value: "123 Tech Street, Suite 500 New York, NY 10001, USA" },
  { label: "Tax ID", value: "98-7654321" },
];

const ACTIONS = ["Download Invoices", "View Usage Details", "Add Payment Method"];
const ACTION_ICONS = ["⬇", "▤", "▣"];

const CARD =
  "box-border w-full shrink-0 flex flex-col gap-[12px] p-[16px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]";
const TITLE =
  "text-[14px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]";

export default function BillingRightPanel() {
  return (
    <div className="box-border w-[320px] shrink-0 h-full flex flex-col gap-[12px] p-[14px] justify-start items-start bg-[var(--ag-right-bg)] [border-width:0px_0px_0px_1px] [border-style:solid] [border-color:var(--ag-divider)] overflow-y-auto">
      {/* Your Plan */}
      <div className={CARD}>
        <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-start relative">
          <div className="box-border w-fit shrink-0 h-fit flex flex-col gap-[8px] justify-start items-start relative [z-index:1]">
            <div className="text-[12px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">Your Plan</div>
            <div className="text-[22px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">Enterprise</div>
          </div>
          <div className="box-border w-[70px] shrink-0 h-[70px] flex flex-row gap-0 justify-center items-center [background-image:linear-gradient(135deg,_#6D3CE0_0%,_#3A1A82_100%)] rounded-[12px] relative [z-index:0]">
            <div className="text-[30px]/[normal] box-border text-[#C69AFF] font-[Inter,system-ui,sans-serif] font-normal text-center [white-space:nowrap]">◈</div>
          </div>
        </div>
        <div className="box-border w-full h-fit shrink-0 flex flex-col gap-[8px] justify-start items-start">
          {FEATURES.map((f) => (
            <div key={f} className="box-border w-full h-fit shrink-0 flex flex-row gap-[8px] justify-start items-center">
              <div className="text-[11px]/[normal] box-border text-[#22C55E] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">✓</div>
              <div className="text-[11px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{f}</div>
            </div>
          ))}
        </div>
        <div className="box-border w-full h-[34px] shrink-0 flex flex-row gap-0 justify-center items-center bg-[var(--ag-input-bg)] [border:1px_solid_var(--ag-card-border)] rounded-[6px]">
          <div className="text-[11px]/[normal] box-border text-[#C084FC] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">Manage Plan</div>
        </div>
      </div>

      {/* Payment Method */}
      <div className={CARD}>
        <div className={TITLE}>Payment Method</div>
        <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[10px] justify-start items-center">
          <div className="box-border w-[40px] shrink-0 h-[26px] flex flex-row gap-0 justify-center items-center bg-[#1A1F71] rounded-[4px]">
            <div className="text-[9px]/[normal] box-border text-[#FFFFFF] font-[Inter,system-ui,sans-serif] font-bold [font-style:italic] text-center [white-space:nowrap]">VISA</div>
          </div>
          <div className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[2px] justify-start items-start">
            <div className="text-[11px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">•••• •••• •••• 4242</div>
            <div className="text-[9px]/[normal] box-border text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">Expires 04/27</div>
          </div>
          <div className="box-border w-[26px] shrink-0 h-[26px] flex flex-row gap-0 justify-center items-center bg-[var(--ag-input-bg)] [border:1px_solid_var(--ag-card-border)] rounded-[6px]">
            <div className="text-[10px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">✎</div>
          </div>
        </div>
      </div>

      {/* Billing Details */}
      <div className={CARD}>
        <div className={TITLE}>Billing Details</div>
        {DETAILS.map((d) => (
          <div key={d.label} className="box-border w-full h-fit shrink-0 flex flex-row gap-[12px] justify-between items-start">
            <div className="text-[10px]/[normal] box-border shrink-0 text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{d.label}</div>
            <div className="text-[10px]/[15px] box-border [flex:1_1_0] min-w-0 text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-right">{d.value}</div>
          </div>
        ))}
        <div className="box-border w-full h-[34px] shrink-0 flex flex-row gap-0 justify-center items-center bg-[var(--ag-input-bg)] [border:1px_solid_var(--ag-card-border)] rounded-[6px]">
          <div className="text-[11px]/[normal] box-border text-[#C084FC] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">Edit Details</div>
        </div>
      </div>

      {/* Quick Actions */}
      <div className={CARD}>
        <div className={TITLE}>Quick Actions</div>
        {ACTIONS.map((a, i) => (
          <div key={a} className="box-border w-full h-fit shrink-0 flex flex-row gap-[10px] p-[9px_10px] justify-start items-center bg-[var(--ag-input-bg)] [border:1px_solid_var(--ag-card-border)] rounded-[6px]">
            <div className="text-[11px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{ACTION_ICONS[i]}</div>
            <div className="text-[10px]/[normal] box-border [flex:1_1_0] min-w-0 text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">{a}</div>
            <div className="text-[11px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">›</div>
          </div>
        ))}
      </div>

      {/* Need help */}
      <div className="box-border w-full [flex:1_1_0] flex flex-col gap-[10px] p-[16px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]">
        <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[9px] justify-start items-center">
          <div className="text-[16px]/[normal] box-border text-[#A78BFA] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">☎</div>
          <div className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[2px] justify-start items-start">
            <div className="text-[11px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">Need help?</div>
            <div className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">Contact our billing team for assistance.</div>
          </div>
        </div>
        <div className="box-border w-full h-[34px] shrink-0 flex flex-row gap-0 justify-center items-center bg-[var(--ag-purple)] rounded-[6px]">
          <div className="text-[11px]/[normal] box-border text-[#FFFFFF] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">Contact Support</div>
        </div>
      </div>
    </div>
  );
}
