"use client";

import { useState } from "react";

/**
 * Capabilities tab. Surfaces the agent card `skills[]` (id / name / description /
 * tags) joined to per-capability reputation (`tasks_verified`, `tasks_rejected`,
 * `verification_rate`). A zero-task capability is NEUTRAL — verification_rate is
 * null (unknown), never 0, matching the backend ReputationRecord rule.
 */

type Capability = {
  id: string;
  name: string;
  description: string;
  icon: string;
  tags: string[];
  tasksVerified: number;
  tasksRejected: number;
  /** 0..1 or null when there is no task history yet. */
  verificationRate: number | null;
};

const CAPABILITIES: Capability[] = [
  {
    id: "infrastructure.deploy",
    name: "Infrastructure Deployment",
    description: "Provisions and deploys cloud infrastructure across AWS, GCP and Azure.",
    icon: "☁",
    tags: ["aws", "iac", "cloud"],
    tasksVerified: 142,
    tasksRejected: 3,
    verificationRate: 0.979,
  },
  {
    id: "kubernetes.manage",
    name: "Kubernetes Management",
    description: "Cluster provisioning, scaling, rollouts and workload orchestration.",
    icon: "✦",
    tags: ["kubernetes", "containers", "scaling"],
    tasksVerified: 98,
    tasksRejected: 2,
    verificationRate: 0.98,
  },
  {
    id: "terraform.generate",
    name: "Terraform Automation",
    description: "Generates and validates Terraform modules from declarative specs.",
    icon: "✥",
    tags: ["terraform", "iac", "codegen"],
    tasksVerified: 76,
    tasksRejected: 5,
    verificationRate: 0.938,
  },
  {
    id: "cicd.pipeline",
    name: "CI/CD Pipeline Setup",
    description: "Builds continuous integration and delivery pipelines end to end.",
    icon: "◉",
    tags: ["cicd", "automation", "github"],
    tasksVerified: 64,
    tasksRejected: 4,
    verificationRate: 0.941,
  },
  {
    id: "cloud.architecture",
    name: "Cloud Architecture",
    description: "Designs resilient, cost-aware multi-region cloud architectures.",
    icon: "☁",
    tags: ["cloud", "architecture", "aws"],
    tasksVerified: 51,
    tasksRejected: 3,
    verificationRate: 0.944,
  },
  {
    id: "monitoring.observability",
    name: "Monitoring & Logging",
    description: "Instruments metrics, tracing and log aggregation for observability.",
    icon: "▣",
    tags: ["monitoring", "observability"],
    tasksVerified: 47,
    tasksRejected: 2,
    verificationRate: 0.959,
  },
  {
    id: "security.hardening",
    name: "Security Implementation",
    description: "Applies least-privilege IAM, secret rotation and policy hardening.",
    icon: "◈",
    tags: ["security", "iam", "compliance"],
    tasksVerified: 38,
    tasksRejected: 1,
    verificationRate: 0.974,
  },
  {
    id: "performance.optimization",
    name: "Performance Optimization",
    description: "Profiles workloads and tunes for latency, cost and throughput.",
    icon: "◌",
    tags: ["performance", "cost", "tuning"],
    tasksVerified: 0,
    tasksRejected: 0,
    verificationRate: null,
  },
];

const ALL_TAGS = ["all", ...Array.from(new Set(CAPABILITIES.flatMap((c) => c.tags)))];

function ratePct(rate: number | null): string {
  return rate === null ? "—" : `${(rate * 100).toFixed(1)}%`;
}

export default function AgentCapabilitiesTab() {
  const [tag, setTag] = useState("all");
  const shown = tag === "all" ? CAPABILITIES : CAPABILITIES.filter((c) => c.tags.includes(tag));

  return (
    <div className="box-border w-full h-fit shrink-0 flex flex-col gap-[14px] justify-start items-start">
      {/* Header + tag filter */}
      <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[10px] justify-between items-center">
        <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-[8px] justify-start items-center">
          <div className="text-[16px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
            Capabilities
          </div>
          <div className="text-[11px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            {shown.length} skills
          </div>
        </div>
        <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-[6px] justify-end items-center [flex-wrap:wrap]">
          {ALL_TAGS.map((t) => {
            const active = t === tag;
            return (
              <button
                key={t}
                type="button"
                onClick={() => setTag(t)}
                className={`box-border w-fit shrink-0 h-fit flex flex-row gap-0 p-[5px_10px] justify-start items-start rounded-[5px] cursor-pointer ${
                  active
                    ? "bg-[#421A97] [border:1px_solid_#7C3AED]"
                    : "bg-[var(--ag2-surface)] [border:1px_solid_var(--ag2-border)]"
                }`}
              >
                <div
                  className={`text-[10px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap] ${
                    active ? "text-[#F4F2FF]" : "text-[var(--ag2-dim)]"
                  }`}
                >
                  {t === "all" ? "All" : t}
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {/* Capability grid */}
      <div className="box-border w-full h-fit shrink-0 grid grid-cols-2 gap-[12px]">
        {shown.map((c) => (
          <div
            key={c.id}
            className="box-border w-full h-fit flex flex-col gap-[10px] p-[14px] justify-start items-start bg-[var(--ag2-panel)] [border:1px_solid_var(--ag2-border)] rounded-[9px]"
          >
            <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[10px] justify-start items-center">
              <div className="box-border w-[38px] shrink-0 h-[38px] flex flex-row gap-0 justify-center items-center bg-[var(--ag2-tile)] rounded-[9px]">
                <div className="text-[18px]/[normal] box-border text-[#B266FF] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                  {c.icon}
                </div>
              </div>
              <div className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[2px] justify-start items-start">
                <div className="text-[13px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
                  {c.name}
                </div>
                <div className="text-[10px]/[normal] box-border text-[var(--ag2-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap] font-mono">
                  {c.id}
                </div>
              </div>
            </div>
            <div className="text-[11px]/[normal] box-border w-full text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left">
              {c.description}
            </div>
            <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[5px] justify-start items-center [flex-wrap:wrap]">
              {c.tags.map((t) => (
                <div
                  key={t}
                  className="box-border w-fit shrink-0 h-fit flex flex-row gap-0 p-[4px_7px] justify-start items-start bg-[var(--ag2-chip)] rounded-[4px]"
                >
                  <div className="text-[9px]/[normal] box-border text-[#A78BFA] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]">
                    {t}
                  </div>
                </div>
              ))}
            </div>
            {/* Verification rate bar */}
            <div className="box-border w-full h-fit shrink-0 flex flex-col gap-[5px] p-[10px_0px_0px_0px] justify-start items-start [border-width:1px_0px_0px_0px] [border-style:solid] [border-color:var(--ag2-border)]">
              <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
                <div className="text-[10px]/[normal] box-border text-[var(--ag2-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                  Verification rate
                </div>
                <div
                  className={`text-[11px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-semibold text-right [white-space:nowrap] ${
                    c.verificationRate === null ? "text-[var(--ag2-muted)]" : "text-[#35D78B]"
                  }`}
                >
                  {ratePct(c.verificationRate)}
                </div>
              </div>
              <div className="box-border w-full h-[5px] shrink-0 bg-[var(--ag2-input-deep)] rounded-full overflow-hidden">
                <div
                  className="box-border h-full bg-[#35D78B] rounded-full"
                  style={{ width: c.verificationRate === null ? "0%" : `${c.verificationRate * 100}%` }}
                ></div>
              </div>
              <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[12px] justify-start items-center">
                <div className="text-[9px]/[normal] box-border text-[#35D78B] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                  ✓ {c.tasksVerified} verified
                </div>
                <div className="text-[9px]/[normal] box-border text-[#F87171] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                  ✕ {c.tasksRejected} rejected
                </div>
                {c.verificationRate === null && (
                  <div className="text-[9px]/[normal] box-border text-[var(--ag2-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                    No history yet
                  </div>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
