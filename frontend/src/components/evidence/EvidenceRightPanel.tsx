/**
 * Evidence & Audit — right rail (Pencil "Evidence Right" design): compliance &
 * integrity ring (canvas), quick filters, and recent evidence. Dashboard
 * `--ag-*` tokens for structure; accent hues literal.
 */

import DonutChart, { type DonutSegment } from "@/components/charts/DonutChart";

// A single full green segment reads as the "100% integrity" ring.
const INTEGRITY: DonutSegment[] = [{ label: "Integrity", value: 100, color: "#22C55E" }];

const COMPLIANCE = ["Data Integrity", "Retention Policy", "Access Controls", "Audit Coverage", "Encryption"];

const FILTERS: { label: string; value: string }[] = [
  { label: "All Evidence", value: "3,842" },
  { label: "Critical Events", value: "342" },
  { label: "User Actions", value: "1,248" },
  { label: "System Events", value: "1,125" },
  { label: "Data Changes", value: "897" },
  { label: "Access Events", value: "230" },
];

const EVIDENCE: { name: string; detail: string; color: string }[] = [
  { name: "Contract C-883 Signed", detail: "PDF · 2.4 MB", color: "#EF4444" },
  { name: "Task Execution T-1289", detail: "JSON · 18 KB", color: "#2563EB" },
  { name: "Approval A-554 Screenshot", detail: "PNG · 1.2 MB", color: "#22C55E" },
  { name: "System Log Export", detail: "LOG · 4.6 MB", color: "#7C3AED" },
  { name: "Audit Trail Export", detail: "ZIP · 12.8 MB", color: "#F59E0B" },
];

const TITLE =
  "text-[14px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]";
const PILL =
  "box-border w-full h-[32px] shrink-0 flex flex-row gap-0 justify-center items-center bg-[var(--ag-input-bg)] [border:1px_solid_var(--ag-card-border)] rounded-[5px]";

export default function EvidenceRightPanel() {
  return (
    <div className="box-border w-[260px] shrink-0 h-full flex flex-col gap-[12px] p-[14px] justify-start items-start bg-[var(--ag-right-bg)] [border-width:0px_0px_0px_1px] [border-style:solid] [border-color:var(--ag-divider)] overflow-y-auto">
      {/* Compliance & integrity */}
      <div className="box-border w-full h-[270px] shrink-0 flex flex-col gap-[12px] p-[14px] justify-start items-center bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]">
        <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-start items-center">
          <div className={TITLE}>Compliance &amp; Integrity</div>
        </div>
        <DonutChart data={INTEGRITY} size={92} thickness={13}>
          <div className="text-[13px]/[normal] box-border text-[#22C55E] font-[Inter,system-ui,sans-serif] font-bold text-center [white-space:nowrap]">
            ✓
          </div>
        </DonutChart>
        <div className="box-border w-full h-fit shrink-0 flex flex-col gap-[5px] justify-start items-start">
          {COMPLIANCE.map((c) => (
            <div key={c} className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
              <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-[7px] justify-start items-center">
                <div className="box-border w-[7px] shrink-0 h-[7px] rounded-full bg-[#22C55E]"></div>
                <div className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                  {c}
                </div>
              </div>
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
                100%
              </div>
            </div>
          ))}
        </div>
        <div className={PILL} style={{ height: 24 }}>
          <div className="text-[10px]/[normal] box-border text-[#C084FC] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
            View Compliance Report
          </div>
        </div>
      </div>

      {/* Quick filters */}
      <div className="box-border w-full h-[252px] shrink-0 flex flex-col gap-[10px] p-[14px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]">
        <div className={TITLE}>Quick Filters</div>
        {FILTERS.map((f) => (
          <div key={f.label} className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
            <div className="text-[10px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
              {f.label}
            </div>
            <div className="text-[10px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
              {f.value}
            </div>
          </div>
        ))}
        <div className={PILL}>
          <div className="text-[10px]/[normal] box-border text-[#C084FC] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
            Advanced Filters ›
          </div>
        </div>
      </div>

      {/* Recent evidence */}
      <div className="box-border w-full [flex:1_1_0] flex flex-col gap-[10px] p-[14px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]">
        <div className={TITLE}>Recent Evidence</div>
        {EVIDENCE.map((e) => (
          <div key={e.name} className="box-border w-full h-[39px] shrink-0 flex flex-row gap-[9px] justify-start items-center">
            <div className="box-border w-[28px] shrink-0 h-[28px] rounded-[6px]" style={{ backgroundColor: e.color }}></div>
            <div className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[3px] justify-start items-start">
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
                {e.name}
              </div>
              <div className="text-[8px]/[normal] box-border text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                {e.detail}
              </div>
            </div>
            <div className="text-[8px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
              2h ago
            </div>
          </div>
        ))}
        <div className="box-border w-full h-[34px] shrink-0 flex flex-row gap-0 justify-center items-center bg-[var(--ag-input-bg)] [border:1px_solid_var(--ag-card-border)] rounded-[5px]">
          <div className="text-[10px]/[normal] box-border text-[#C084FC] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
            ▢ Browse Evidence Store ›
          </div>
        </div>
      </div>
    </div>
  );
}
