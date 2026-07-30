/**
 * Credentials Vault — right rail (Pencil "Credentials Vault" design):
 * vault summary donut, recent access requests, connected services, and a
 * security & compliance readout. Same theme-var conventions as VaultContent.
 */

import DonutChart, { type DonutSegment } from "@/components/charts/DonutChart";

const LEGEND: { label: string; value: string; color: string; count: number }[] = [
  { label: "● Active", value: "120 (85%)", color: "#35D78B", count: 120 },
  { label: "● Expiring Soon", value: "8 (6%)", color: "#FBBF24", count: 8 },
  { label: "● Revoked", value: "4 (3%)", color: "#EF4444", count: 4 },
  { label: "● Inactive", value: "10 (6%)", color: "#94A3B8", count: 10 },
];

const DONUT: DonutSegment[] = LEGEND.map((l) => ({ label: l.label, value: l.count, color: l.color }));

type Request = { icon: string; name: string; by: string; status: "Pending" | "Approved" };

const REQUESTS: Request[] = [
  { icon: "aws", name: "AWS Production Access", by: "Ana Martinez", status: "Pending" },
  { icon: "☁", name: "GCP Billing Admin", by: "Michael Chen", status: "Approved" },
  { icon: "S", name: "Stripe Live Key", by: "Sofia Rodriguez", status: "Pending" },
  { icon: "●", name: "MongoDB Cluster", by: "James Wilson", status: "Approved" },
];

const SERVICES = ["aws", "☁", "◉", "✿", "S", "●", "◒", "☁"];

const COMPLIANCE: { label: string; value: string; ok: boolean }[] = [
  { label: "Vault Encryption", value: "AES-256 ●", ok: true },
  { label: "Access Logging", value: "Enabled ●", ok: true },
  { label: "MFA Required", value: "Enabled ●", ok: true },
  { label: "◷ Last Audit", value: "2h ago", ok: false },
];

export default function VaultRightPanel() {
  return (
    <div className="box-border w-[300px] shrink-0 h-full flex flex-col gap-[12px] p-[16px_14px] justify-start items-start bg-[var(--ag-right-bg)] [border-width:0px_0px_0px_1px] [border-style:solid] [border-color:var(--ag-divider)] overflow-y-auto">
      {/* Vault summary */}
      <div className="box-border w-full shrink-0 flex flex-col gap-[12px] p-[16px] justify-start items-start bg-[var(--ag2-panel)] [border:1px_solid_var(--ag2-border)] rounded-[8px]">
        <div className="text-[14px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
          Vault Summary
        </div>
        <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[18px] justify-start items-center">
          {/* Donut */}
          <DonutChart data={DONUT} size={98} thickness={18}>
            <div className="text-[18px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-center [white-space:nowrap]">
              142
            </div>
            <div className="text-[9px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-center [white-space:nowrap]">
              Total
            </div>
          </DonutChart>
          {/* Legend */}
          <div className="box-border w-fit shrink-0 h-fit flex flex-col gap-[10px] justify-start items-start">
            {LEGEND.map((l) => (
              <div key={l.label} className="box-border w-full h-fit shrink-0 flex flex-row gap-[10px] justify-between items-start">
                <div
                  className="text-[10px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
                  style={{ color: l.color }}
                >
                  {l.label}
                </div>
                <div className="text-[10px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                  {l.value}
                </div>
              </div>
            ))}
          </div>
        </div>
        <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 p-[11px_8px] justify-center items-start bg-[#5D20DC] rounded-[6px]">
          <div className="text-[11px]/[normal] box-border text-[#F4F2FF] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
            View All Credentials
          </div>
        </div>
      </div>

      {/* Recent access requests */}
      <div className="box-border w-full shrink-0 flex flex-col gap-[12px] p-[15px] justify-start items-start bg-[var(--ag2-panel)] [border:1px_solid_var(--ag2-border)] rounded-[8px]">
        <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-start">
          <div className="text-[14px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
            Recent Access Requests
          </div>
          <div className="text-[10px]/[normal] box-border text-[#B267FF] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            View all
          </div>
        </div>
        {REQUESTS.map((r) => {
          const badgeBg = r.status === "Pending" ? "bg-[#5A3A06]" : "bg-[#073C31]";
          const badgeText = r.status === "Pending" ? "text-[#FBBF24]" : "text-[#35D78B]";
          return (
            <div key={r.name} className="box-border w-full h-fit shrink-0 flex flex-row gap-[9px] justify-start items-center">
              <div className="box-border w-[28px] shrink-0 h-[28px] flex flex-row gap-0 justify-center items-center bg-[var(--ag2-surface)] rounded-[6px]">
                <div className="text-[12px]/[normal] box-border text-[#B678FF] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
                  {r.icon}
                </div>
              </div>
              <div className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[3px] justify-start items-start">
                <div className="text-[10px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
                  {r.name}
                </div>
                <div className="text-[9px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                  Requested by {r.by}
                </div>
              </div>
              <div className={`box-border w-fit shrink-0 h-fit flex flex-row gap-0 p-[4px_6px] justify-start items-start ${badgeBg} rounded-[4px]`}>
                <div className={`text-[9px]/[normal] box-border ${badgeText} font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]`}>
                  {r.status}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Connected services */}
      <div className="box-border w-full h-[160px] shrink-0 flex flex-col gap-[11px] p-[15px] justify-start items-start bg-[var(--ag2-panel)] [border:1px_solid_var(--ag2-border)] rounded-[8px]">
        <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-start">
          <div className="text-[14px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
            Connected Services
          </div>
          <div className="text-[10px]/[normal] box-border text-[#B267FF] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            View all
          </div>
        </div>
        <div className="box-border w-full [flex:1_1_0] flex flex-row gap-[8px] justify-start items-start">
          {SERVICES.map((s, i) => (
            <div
              key={i}
              className="box-border [flex:1_1_0] h-full flex flex-row gap-0 justify-center items-center bg-[var(--ag2-surface)] [border:1px_solid_var(--ag2-border)] rounded-[6px]"
            >
              <div className="text-[12px]/[normal] box-border text-[#B678FF] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
                {s}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Security & compliance */}
      <div className="box-border w-full [flex:1_1_0] flex flex-col gap-[13px] p-[15px] justify-start items-start bg-[var(--ag2-panel)] [border:1px_solid_var(--ag2-border)] rounded-[8px]">
        <div className="text-[14px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
          Security &amp; Compliance
        </div>
        {COMPLIANCE.map((c) => (
          <div key={c.label} className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-start">
            <div className="text-[10px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
              {c.label}
            </div>
            <div
              className={`text-[10px]/[normal] box-border ${
                c.ok ? "text-[#35D78B]" : "text-[var(--ag2-dim)]"
              } font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]`}
            >
              {c.value}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
