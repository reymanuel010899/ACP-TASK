"use client";

import { useState } from "react";
import AgentOverviewTab from "@/components/agents/AgentOverviewTab";
import AgentCapabilitiesTab from "@/components/agents/AgentCapabilitiesTab";
import AgentPerformanceTab from "@/components/agents/AgentPerformanceTab";
import AgentTasksTab from "@/components/agents/AgentTasksTab";
import AgentCredentialsTab from "@/components/agents/AgentCredentialsTab";
import AgentReviewsTab from "@/components/agents/AgentReviewsTab";
import AgentActivityTab from "@/components/agents/AgentActivityTab";
import AgentSettingsTab from "@/components/agents/AgentSettingsTab";

/**
 * Agent detail page (Pencil "Sidebar 2" design). Client container that owns the
 * active-tab state and renders the matching panel. The header (avatar, name,
 * status, actions) is shared across every tab; each tab body lives in its own
 * `Agent<Name>Tab.tsx` component. Presentational mock data throughout, matching
 * the rest of the app — hybrid model: real domain fields (skills, reputation,
 * audit activity types, vault grants...) with mock values.
 */

type TabKey =
  | "overview"
  | "capabilities"
  | "performance"
  | "tasks"
  | "credentials"
  | "reviews"
  | "activity"
  | "settings";

const TABS: { key: TabKey; label: string }[] = [
  { key: "overview", label: "Overview" },
  { key: "capabilities", label: "Capabilities" },
  { key: "performance", label: "Performance" },
  { key: "tasks", label: "Tasks" },
  { key: "credentials", label: "Credentials" },
  { key: "reviews", label: "Reviews" },
  { key: "activity", label: "Activity" },
  { key: "settings", label: "Settings" },
];

export default function AgentContent() {
  const [tab, setTab] = useState<TabKey>("overview");

  return (
    <div className="box-border w-full [flex:1_1_0] flex flex-col gap-[14px] p-[20px_24px_18px_24px] justify-start items-start">
      {/* Breadcrumb */}
      <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[7px] justify-start items-center">
        <div className="text-[13px]/[normal] box-border text-[#7C3AED] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
          ✧
        </div>
        <div className="text-[12px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
          Agents
        </div>
        <div className="text-[12px]/[normal] box-border text-[var(--ag2-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
          /
        </div>
        <div className="text-[12px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
          DevOps Agent
        </div>
      </div>

      {/* Header */}
      <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 p-[4px_0px_10px_0px] justify-between items-center">
        <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-[16px] justify-start items-center">
          <div className="box-border w-[72px] shrink-0 h-[72px] [background-image:radial-gradient(ellipse_50%_50%_at_50%_50%,_#A855F7_0%,_#321168_100%)] bg-no-repeat bg-[length:100%_100%] [border:1px_solid_#8B5CF6] rounded-full"></div>
          <div className="box-border w-fit shrink-0 h-fit flex flex-col gap-[5px] justify-start items-start">
            <div className="box-border w-fit h-fit shrink-0 flex flex-row gap-[12px] justify-start items-center">
              <div className="text-[25px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
                DevOps Agent
              </div>
              <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-0 p-[4px_8px] justify-start items-start bg-[#073C31] rounded-[5px]">
                <div className="text-[11px]/[normal] box-border text-[#47E7A7] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
                  Active
                </div>
              </div>
            </div>
            <div className="text-[13px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
              Infrastructure &amp; Deployment Specialist
            </div>
            <div className="box-border w-fit h-fit shrink-0 flex flex-row gap-[7px] justify-start items-center">
              <div className="text-[15px]/[normal] box-border text-[#FBBF24] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                ★
              </div>
              <div className="text-[12px]/[normal] box-border text-[var(--ag2-strong)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                4.9 (128 reviews)
              </div>
            </div>
          </div>
        </div>
        <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-[10px] justify-start items-center">
          <button
            type="button"
            className="box-border w-fit shrink-0 h-fit flex flex-row gap-0 p-[10px_13px] justify-start items-start bg-[var(--ag2-surface)] [border:1px_solid_var(--ag2-border)] rounded-[7px] cursor-pointer"
          >
            <div className="text-[12px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
              ▣ Message Agent
            </div>
          </button>
          <button
            type="button"
            className="box-border w-fit shrink-0 h-fit flex flex-row gap-[8px] p-[10px_13px] justify-start items-start bg-[#5720D7] rounded-[7px] cursor-pointer"
          >
            <div className="text-[12px]/[normal] box-border text-[#F4F2FF] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
              Actions
            </div>
            <div className="text-[14px]/[normal] box-border text-[#F4F2FF] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
              ⌄
            </div>
          </button>
        </div>
      </div>

      {/* Tab bar */}
      <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[29px] p-[10px_0px_11px_0px] justify-start items-start [border-width:0px_0px_1px_0px] [border-style:solid] [border-color:var(--ag2-border)]">
        {TABS.map((t) => {
          const isActive = t.key === tab;
          return (
            <button
              key={t.key}
              type="button"
              onClick={() => setTab(t.key)}
              className={`box-border w-fit shrink-0 h-fit flex flex-row gap-0 p-[0px_0px_9px_0px] justify-start items-start cursor-pointer [border-width:0px_0px_2px_0px] [border-style:solid] ${
                isActive ? "[border-color:#8B5CF6]" : "[border-color:#00000000]"
              }`}
            >
              <div
                className={`text-[12px]/[normal] box-border font-[Inter,system-ui,sans-serif] text-left [white-space:nowrap] ${
                  isActive
                    ? "text-[#B36BFF] font-semibold"
                    : "text-[var(--ag2-dim)] font-normal"
                }`}
              >
                {t.label}
              </div>
            </button>
          );
        })}
      </div>

      {/* Active tab */}
      {tab === "overview" && <AgentOverviewTab />}
      {tab === "capabilities" && <AgentCapabilitiesTab />}
      {tab === "performance" && <AgentPerformanceTab />}
      {tab === "tasks" && <AgentTasksTab />}
      {tab === "credentials" && <AgentCredentialsTab />}
      {tab === "reviews" && <AgentReviewsTab />}
      {tab === "activity" && <AgentActivityTab />}
      {tab === "settings" && <AgentSettingsTab />}
    </div>
  );
}
