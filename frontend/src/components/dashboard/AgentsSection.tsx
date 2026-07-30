"use client";

// "Your Agents" dashboard strip — real agents from the runner (up to 4), not
// hardcoded. "View all agents" and the "Add New Agent" card both link to the
// full /agents console; each card opens that agent's detail page.

import Link from "next/link";
import { useAgentsList, type RunnerAgent } from "@/lib/agentQueries";
import { CAPABILITY_BY_ID } from "@/data/capabilities";

const AVATAR_COLORS = ["#3B82F6", "#F59E0B", "#22C55E", "#EF4444", "#8B5CF6", "#06B6D4"];

function avatarColor(id: string): string {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) | 0;
  return AVATAR_COLORS[Math.abs(h) % AVATAR_COLORS.length];
}

function statusOf(a: RunnerAgent): { label: string; color: string } {
  switch (a.runtime.status) {
    case "online":
      return { label: "Active", color: "#22C55E" };
    case "starting":
      return { label: "Busy", color: "#F59E0B" };
    case "error":
      return { label: "Error", color: "#EF4444" };
    case "offline":
      return { label: "Unreachable", color: "#EF4444" };
    default:
      return { label: "Idle", color: "#9CA3AF" };
  }
}

function subtitle(a: RunnerAgent): string {
  const first = (a.capabilities ?? [])[0];
  if (!first) return a.description || "No capabilities";
  return CAPABILITY_BY_ID[first]?.label ?? first;
}

export default function AgentsSection() {
  const { data, isLoading } = useAgentsList(1, "");
  const agents = (data?.agents ?? []).slice(0, 4);

  return (
    <div className="box-border w-full h-fit shrink-0 flex flex-col gap-[16px] justify-start items-start">
      {/* Header */}
      <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
        <div className="text-[18px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
          Your Agents
        </div>
        <Link
          href="/agents"
          className="box-border w-fit shrink-0 h-fit flex flex-row gap-[4px] justify-start items-center cursor-pointer group"
        >
          <div className="text-[13px]/[normal] box-border text-[#8B5CF6] group-hover:text-[#a985ff] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap] transition-colors">
            View all agents
          </div>
          <span className="text-[#8B5CF6] group-hover:text-[#a985ff] text-[13px] transition-colors">&rarr;</span>
        </Link>
      </div>

      {/* Cards */}
      <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[16px] justify-start items-stretch flex-wrap">
        {isLoading && agents.length === 0
          ? [0, 1, 2, 3].map((i) => (
              <div
                key={i}
                className="box-border [flex:1_1_220px] min-w-[220px] h-[140px] bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[12px] animate-pulse"
              />
            ))
          : agents.map((a) => {
              const st = statusOf(a);
              const caps = (a.capabilities ?? []).length;
              return (
                <Link
                  key={a.id}
                  href={`/agents/${encodeURIComponent(a.id)}`}
                  className="box-border [flex:1_1_220px] min-w-[220px] h-fit flex flex-col gap-[12px] p-[16px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[12px] cursor-pointer hover:[border-color:#5D20DC] transition-colors"
                >
                  <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[10px] justify-start items-center">
                    <div className="box-border w-[40px] shrink-0 h-[40px] rounded-full" style={{ backgroundColor: avatarColor(a.id) }} />
                    <div className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[3px] justify-start items-start">
                      <div className="text-[14px]/[normal] box-border w-full text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left truncate">
                        {a.name}
                      </div>
                      <div className="box-border w-fit h-fit shrink-0 flex flex-row gap-[4px] justify-start items-center">
                        <div className="box-border w-[6px] shrink-0 h-[6px] rounded-full" style={{ backgroundColor: st.color }} />
                        <div className="text-[11px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]" style={{ color: st.color }}>
                          {st.label}
                        </div>
                      </div>
                    </div>
                  </div>
                  <div className="text-[12px]/[normal] box-border w-full text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left truncate">
                    {subtitle(a)}
                  </div>
                  <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
                    {a.trust_tier === "verified" ? (
                      <span className="text-[11px]/[normal] box-border text-[#22C55E] font-[Inter,system-ui,sans-serif] font-medium">&#10003; Verified</span>
                    ) : (
                      <span className="text-[11px]/[normal] box-border text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-medium">Discovery</span>
                    )}
                    <span className="text-[11px]/[normal] box-border text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif]">
                      {caps} cap{caps === 1 ? "" : "s"}
                    </span>
                  </div>
                </Link>
              );
            })}
      </div>
    </div>
  );
}
