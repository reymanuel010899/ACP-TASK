"use client";

import { useMemo, useState, type RefObject } from "react";
import { CAPABILITIES, type Capability } from "@/data/capabilities";

/**
 * Searchable capability table over the catalog (src/data/capabilities.ts).
 * Shared by both onboarding paths: creating a managed agent, and declaring what
 * an externally hosted (connected) agent offers.
 */

const CATEGORIES = ["All", ...Array.from(new Set(CAPABILITIES.map((c) => c.category)))];

export default function CapabilityPicker({
  selected,
  onToggle,
  showError = false,
  errorMsg = "Select at least one capability to continue.",
  heading = "Capabilities",
  headingRef,
  maxHeightClass = "max-h-[280px]",
}: {
  selected: string[];
  onToggle: (cap: Capability) => void;
  showError?: boolean;
  errorMsg?: string;
  heading?: string;
  headingRef?: RefObject<HTMLHeadingElement | null>;
  maxHeightClass?: string;
}) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("All");
  const selectedIds = useMemo(() => new Set(selected), [selected]);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return CAPABILITIES.filter((c) => {
      if (category !== "All" && c.category !== category) return false;
      if (!q) return true;
      return (
        c.label.toLowerCase().includes(q) ||
        c.id.toLowerCase().includes(q) ||
        c.category.toLowerCase().includes(q)
      );
    });
  }, [query, category]);

  return (
    <div className="box-border w-full flex flex-col gap-[12px]">
      <div className="box-border w-full flex flex-row gap-[8px] justify-between items-center">
        <h2
          ref={headingRef}
          tabIndex={-1}
          className="text-[14px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-left outline-none"
        >
          {heading}
        </h2>
        <div className="text-[11px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-right [white-space:nowrap]">
          {selected.length} selected
        </div>
      </div>

      <div className="box-border w-full flex flex-row gap-[8px] justify-start items-center">
        <div className="box-border [flex:1_1_0] h-[36px] flex flex-row gap-[8px] p-[0px_11px] justify-start items-center bg-[var(--ag2-input)] [border:1px_solid_var(--ag2-border)] rounded-[7px]">
          <div className="text-[14px] box-border text-[var(--ag2-dim)]">⌕</div>
          <input
            className="box-border [flex:1_1_0] min-w-0 h-full bg-transparent outline-none text-[12px] text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] placeholder:text-[var(--ag2-muted)]"
            placeholder="Search capabilities…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search capabilities"
          />
        </div>
        <select
          className="box-border w-fit h-[36px] p-[0px_10px] bg-[var(--ag2-surface)] [border:1px_solid_var(--ag2-border)] rounded-[7px] text-[11px] text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] outline-none cursor-pointer"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          aria-label="Filter by category"
        >
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </div>

      {showError && (
        <div className="text-[10px]/[normal] box-border text-[#F87171] font-[Inter,system-ui,sans-serif] font-normal text-left">
          {errorMsg}
        </div>
      )}

      <div className={`box-border w-full ${maxHeightClass} overflow-y-auto flex flex-col gap-0 [border:1px_solid_var(--ag2-border)] rounded-[9px]`}>
        <div className="box-border w-full sticky top-0 z-10 flex flex-row gap-[10px] p-[9px_12px] justify-start items-center bg-[var(--ag2-surface)] [border-width:0px_0px_1px_0px] [border-style:solid] [border-color:var(--ag2-border)]">
          <div className="box-border w-[18px] shrink-0" />
          <div className="box-border [flex:1_1_0] text-[10px]/[normal] text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-semibold [white-space:nowrap]">
            Capability
          </div>
          <div className="box-border w-[190px] shrink-0 text-[10px]/[normal] text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-semibold [white-space:nowrap]">
            ID
          </div>
          <div className="box-border w-[140px] shrink-0 text-[10px]/[normal] text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-semibold [white-space:nowrap]">
            Category
          </div>
        </div>
        {rows.length === 0 ? (
          <div className="box-border w-full p-[24px] text-center text-[11px] text-[var(--ag2-muted)] font-[Inter,system-ui,sans-serif]">
            No capabilities match “{query}”.
          </div>
        ) : (
          rows.map((c) => {
            const checked = selectedIds.has(c.id);
            return (
              <button
                key={c.id}
                type="button"
                onClick={() => onToggle(c)}
                className={`box-border w-full flex flex-row gap-[10px] p-[9px_12px] justify-start items-center text-left cursor-pointer [border-width:1px_0px_0px_0px] [border-style:solid] [border-color:var(--ag2-border)] first:[border-width:0px] hover:bg-[var(--ag2-surface)] ${
                  checked ? "bg-[#1c1636]" : ""
                }`}
              >
                <div
                  role="checkbox"
                  aria-checked={checked}
                  aria-label={c.label}
                  className={`box-border w-[16px] h-[16px] shrink-0 flex items-center justify-center rounded-[4px] text-[10px] ${
                    checked
                      ? "bg-[#5D20DC] text-white"
                      : "bg-[var(--ag2-input-deep)] [border:1px_solid_var(--ag2-border)] text-transparent"
                  }`}
                >
                  ✓
                </div>
                <div className="box-border [flex:1_1_0] min-w-0 text-[12px]/[normal] text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-medium overflow-hidden text-ellipsis [white-space:nowrap]">
                  {c.label}
                </div>
                <div className="box-border w-[190px] shrink-0 text-[10px]/[normal] text-[var(--ag2-muted)] font-mono overflow-hidden text-ellipsis [white-space:nowrap]">
                  {c.id}
                </div>
                <div className="box-border w-[140px] shrink-0 text-[10px]/[normal] text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal overflow-hidden text-ellipsis [white-space:nowrap]">
                  {c.category}
                </div>
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}
