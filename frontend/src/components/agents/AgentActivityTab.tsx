"use client";

import { useState } from "react";

/**
 * Activity tab. Renders the append-only audit log for this principal. Each entry
 * mirrors the backend AuditStore: activity_type (open vocabulary), timestamp,
 * resource_id, status, details. Newest-first, filterable by activity family.
 */

type ActivityStatus = "ok" | "granted" | "denied" | "pending";

const STATUS_STYLE: Record<ActivityStatus, { bg: string; text: string }> = {
  ok: { bg: "#073C31", text: "#38D996" },
  granted: { bg: "#073C31", text: "#38D996" },
  pending: { bg: "#3A2A0B", text: "#FBBF24" },
  denied: { bg: "#3A1414", text: "#F87171" },
};

type Entry = {
  entryId: string;
  activityType: string;
  resourceId: string | null;
  status: ActivityStatus;
  timestamp: string;
  details: string;
};

/** Maps an activity_type to its display family + icon/color. */
function familyOf(type: string): string {
  return type.split(".")[0];
}
const FAMILY_ICON: Record<string, { icon: string; color: string }> = {
  task: { icon: "▤", color: "#60A5FA" },
  work: { icon: "◉", color: "#B266FF" },
  agent: { icon: "✧", color: "#C69AFF" },
  credential: { icon: "◇", color: "#34D399" },
  reputation: { icon: "★", color: "#FBBF24" },
  keyring: { icon: "⚿", color: "#F59E0B" },
  permission: { icon: "◈", color: "#7DD3FC" },
};

const ENTRIES: Entry[] = [
  { entryId: "e_01", activityType: "work.complete", resourceId: "task b2f1…9ac4", status: "ok", timestamp: "2 min ago", details: "Deploy microservices to EKS marked complete" },
  { entryId: "e_02", activityType: "task.result", resourceId: "task b2f1…9ac4", status: "ok", timestamp: "8 min ago", details: "Submitted work result with 4 artifact hashes" },
  { entryId: "e_03", activityType: "reputation.update", resourceId: "infrastructure.deploy", status: "ok", timestamp: "8 min ago", details: "verification_rate 0.978 → 0.979 (+1 verified)" },
  { entryId: "e_04", activityType: "credential.access", resourceId: "cr_9f2a…", status: "granted", timestamp: "12 min ago", details: "Read AWS Deploy Role within scope deploy:eks,ecr" },
  { entryId: "e_05", activityType: "task.accept", resourceId: "task e4b8…70cd", status: "ok", timestamp: "1 h ago", details: "Accepted offer $1,100 USD from Growth Labs" },
  { entryId: "e_06", activityType: "task.offer", resourceId: "task e4b8…70cd", status: "pending", timestamp: "1 h ago", details: "Sent offer for observability stack setup" },
  { entryId: "e_07", activityType: "credential.access", resourceId: "cr_7e90…", status: "denied", timestamp: "3 h ago", details: "Kubeconfig (prod) access denied — grant revoked" },
  { entryId: "e_08", activityType: "agent.hire", resourceId: "z6Mk…70cd", status: "granted", timestamp: "5 h ago", details: "Hired by Growth Labs with credential scope" },
  { entryId: "e_09", activityType: "work.submit", resourceId: "task d901…33fa", status: "ok", timestamp: "yesterday", details: "Delivered IAM hardening work for review" },
  { entryId: "e_10", activityType: "keyring.rotate", resourceId: null, status: "ok", timestamp: "2 days ago", details: "Session key rotated (reason: scheduled)" },
];

const FAMILIES = ["all", "task", "work", "credential", "reputation", "agent", "keyring"];

export default function AgentActivityTab() {
  const [family, setFamily] = useState("all");
  const shown = family === "all" ? ENTRIES : ENTRIES.filter((e) => familyOf(e.activityType) === family);

  return (
    <div className="box-border w-full h-fit shrink-0 flex flex-col gap-[12px] justify-start items-start">
      {/* Header + family filter */}
      <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[10px] justify-between items-center">
        <div className="text-[16px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
          Activity
        </div>
        <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-[6px] justify-end items-center [flex-wrap:wrap]">
          {FAMILIES.map((f) => {
            const active = f === family;
            return (
              <button
                key={f}
                type="button"
                onClick={() => setFamily(f)}
                className={`box-border w-fit shrink-0 h-fit flex flex-row gap-0 p-[5px_10px] justify-start items-start rounded-[5px] cursor-pointer text-[10px] font-medium ${
                  active
                    ? "bg-[#421A97] [border:1px_solid_#7C3AED] text-[#F4F2FF]"
                    : "bg-[var(--ag2-surface)] [border:1px_solid_var(--ag2-border)] text-[var(--ag2-dim)]"
                }`}
              >
                {f === "all" ? "All" : f}
              </button>
            );
          })}
        </div>
      </div>

      {/* Timeline */}
      <div className="box-border w-full h-fit shrink-0 flex flex-col gap-0 justify-start items-start bg-[var(--ag2-panel)] [border:1px_solid_var(--ag2-border)] rounded-[9px] overflow-hidden">
        {shown.map((e, idx) => {
          const fam = FAMILY_ICON[familyOf(e.activityType)] ?? { icon: "•", color: "#9CA3AF" };
          const s = STATUS_STYLE[e.status];
          return (
            <div
              key={e.entryId}
              className={`box-border w-full h-fit shrink-0 flex flex-row gap-[12px] p-[13px_16px] justify-start items-center ${
                idx === 0 ? "" : "[border-width:1px_0px_0px_0px] [border-style:solid] [border-color:var(--ag2-border)]"
              }`}
            >
              <div
                className="box-border w-[32px] shrink-0 h-[32px] flex flex-row gap-0 justify-center items-center rounded-[8px]"
                style={{ backgroundColor: "var(--ag2-tile)" }}
              >
                <div
                  className="text-[14px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
                  style={{ color: fam.color }}
                >
                  {fam.icon}
                </div>
              </div>
              <div className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[3px] justify-start items-start">
                <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[8px] justify-start items-center">
                  <div className="text-[11px]/[normal] box-border text-[#A78BFA] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap] font-mono">
                    {e.activityType}
                  </div>
                  <div
                    className="box-border w-fit h-fit flex flex-row gap-0 p-[2px_7px] justify-start items-start rounded-[4px]"
                    style={{ backgroundColor: s.bg }}
                  >
                    <div
                      className="text-[9px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]"
                      style={{ color: s.text }}
                    >
                      {e.status}
                    </div>
                  </div>
                </div>
                <div className="text-[11px]/[normal] box-border w-full text-[var(--ag2-strong)] font-[Inter,system-ui,sans-serif] font-normal text-left">
                  {e.details}
                </div>
                {e.resourceId && (
                  <div className="text-[9px]/[normal] box-border text-[var(--ag2-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap] font-mono">
                    → {e.resourceId}
                  </div>
                )}
              </div>
              <div className="box-border w-[90px] shrink-0 h-fit text-[10px]/[normal] text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-right [white-space:nowrap]">
                {e.timestamp}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
