"use client";

// "Discover Capabilities" — the real capability catalog (registry /capabilities,
// derived from agent cards): what agents in this ecosystem can actually do, and
// how many offer each. Only capabilities with at least one agent are shown
// (actionable). "View marketplace" and each card link to the marketplace.

import Link from "next/link";
import { useCapabilities, type CatalogCapability } from "@/lib/capabilityQueries";

const TINTS = [
  { bg: "#3B82F620", fg: "#3B82F6" },
  { bg: "#22C55E20", fg: "#22C55E" },
  { bg: "#F59E0B20", fg: "#F59E0B" },
  { bg: "#8B5CF620", fg: "#8B5CF6" },
  { bg: "#EF444420", fg: "#EF4444" },
  { bg: "#06B6D420", fg: "#06B6D4" },
];

function tint(id: string) {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) | 0;
  return TINTS[Math.abs(h) % TINTS.length];
}

function title(c: CatalogCapability): string {
  return c.name || c.capability_id;
}
function category(c: CatalogCapability): string {
  if (c.tags && c.tags.length) return c.tags[0].replace(/\b\w/g, (m) => m.toUpperCase());
  return c.capability_id.includes(".") ? c.capability_id.split(".")[0] : "Capability";
}
function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

export default function CapabilitiesSection() {
  const { data, isLoading } = useCapabilities();
  // Only capabilities someone actually offers are worth discovering.
  const caps = (data ?? []).filter((c) => c.agents.length > 0).slice(0, 4);

  return (
    <div className="box-border w-full h-fit shrink-0 flex flex-col gap-[16px] justify-start items-start">
      {/* Header */}
      <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
        <div className="box-border w-fit shrink-0 h-fit flex flex-col gap-[4px] justify-start items-start">
          <div className="text-[18px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
            Discover Capabilities
          </div>
          <div className="text-[13px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            Find the perfect agent or service for your needs
          </div>
        </div>
        <Link href="/marketplace" className="box-border w-fit shrink-0 h-fit flex flex-row gap-[4px] justify-start items-center cursor-pointer group">
          <div className="text-[13px]/[normal] box-border text-[#8B5CF6] group-hover:text-[#a985ff] font-[Inter,system-ui,sans-serif] font-normal [white-space:nowrap] transition-colors">
            View marketplace
          </div>
          <span className="text-[#8B5CF6] group-hover:text-[#a985ff] text-[13px] transition-colors">&rarr;</span>
        </Link>
      </div>

      {/* Cards */}
      <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[16px] justify-start items-stretch flex-wrap">
        {isLoading && caps.length === 0 ? (
          [0, 1, 2, 3].map((i) => (
            <div key={i} className="box-border [flex:1_1_220px] min-w-[220px] h-[104px] bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[12px] animate-pulse" />
          ))
        ) : caps.length === 0 ? (
          <div className="box-border w-full h-fit flex flex-col gap-[6px] p-[28px] justify-center items-center bg-[var(--ag-card)] [border:1px_dashed_var(--ag-card-border)] rounded-[12px]">
            <div className="text-[13px] text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-semibold">No capabilities offered yet</div>
            <div className="text-[11px] text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif]">Connect or deploy an agent — its capabilities appear here.</div>
          </div>
        ) : (
          caps.map((c) => {
            const t = tint(c.capability_id);
            const n = c.agents.length;
            return (
              <Link
                key={c.capability_id}
                href={`/marketplace?capability=${encodeURIComponent(c.capability_id)}`}
                title={c.description || undefined}
                className="box-border [flex:1_1_220px] min-w-[220px] h-fit flex flex-col gap-[12px] p-[16px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[12px] cursor-pointer hover:[border-color:#5D20DC] transition-colors"
              >
                <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[10px] justify-start items-center">
                  <div className="box-border w-[40px] shrink-0 h-[40px] flex justify-center items-center rounded-[10px] text-[13px] font-bold font-[Inter,system-ui,sans-serif]" style={{ backgroundColor: t.bg, color: t.fg }}>
                    {initials(title(c))}
                  </div>
                  <div className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[2px] justify-start items-start">
                    <div className="text-[14px]/[normal] box-border w-full text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left truncate">
                      {title(c)}
                    </div>
                    <div className="text-[12px]/[normal] box-border w-full text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left truncate">
                      {category(c)}
                    </div>
                  </div>
                </div>
                <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
                  <span className="text-[11px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-medium">
                    {n} agent{n === 1 ? "" : "s"}
                  </span>
                  <span className="box-border px-[8px] py-[2px] rounded-full text-[10px] font-[Inter,system-ui,sans-serif]" style={{ backgroundColor: t.bg, color: t.fg }}>
                    {c.capability_id}
                  </span>
                </div>
              </Link>
            );
          })
        )}
      </div>
    </div>
  );
}
