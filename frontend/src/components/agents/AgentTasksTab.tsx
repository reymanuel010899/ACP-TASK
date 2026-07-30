"use client";

import { useState } from "react";

/**
 * Tasks tab. Merges the two backend work models this agent participates in:
 *  - marketplace task: status open → accepted → delivered → completed
 *  - gig (booking):     status active → completed
 * Fields mirror the servers: id, description, counterparty principal, price +
 * currency (from the negotiation Offer), created_at, status, outcome.
 */

type TaskStatus = "open" | "accepted" | "delivered" | "completed" | "active";

const STATUS_STYLE: Record<TaskStatus, { label: string; bg: string; text: string }> = {
  open: { label: "Open", bg: "#1E3A5F", text: "#7DD3FC" },
  accepted: { label: "Accepted", bg: "#35126E", text: "#D5AEFF" },
  delivered: { label: "Delivered", bg: "#3A2A0B", text: "#FBBF24" },
  active: { label: "Active", bg: "#3A2A0B", text: "#FBBF24" },
  completed: { label: "Completed", bg: "#073C31", text: "#38D996" },
};

type Kind = "task" | "gig";

type WorkItem = {
  id: string;
  kind: Kind;
  description: string;
  counterparty: string;
  price: number;
  currency: string;
  status: TaskStatus;
  createdAt: string;
  outcome: string | null;
};

const ITEMS: WorkItem[] = [
  {
    id: "b2f1…9ac4",
    kind: "task",
    description: "Deploy microservices to EKS with blue/green rollout",
    counterparty: "TechCorp Inc.",
    price: 1850,
    currency: "USD",
    status: "completed",
    createdAt: "May 20, 2024",
    outcome: "verified",
  },
  {
    id: "7c3d…1e08",
    kind: "task",
    description: "CI/CD pipeline optimization for monorepo",
    counterparty: "DataFlow Systems",
    price: 950,
    currency: "USD",
    status: "completed",
    createdAt: "May 18, 2024",
    outcome: "verified",
  },
  {
    id: "af52…6b71",
    kind: "gig",
    description: "Multi-environment Terraform setup (dev/stage/prod)",
    counterparty: "InnovateLabs",
    price: 2200,
    currency: "USD",
    status: "completed",
    createdAt: "May 15, 2024",
    outcome: "verified",
  },
  {
    id: "d901…33fa",
    kind: "task",
    description: "Harden IAM policies and rotate service credentials",
    counterparty: "SecureOps",
    price: 1400,
    currency: "USD",
    status: "delivered",
    createdAt: "May 22, 2024",
    outcome: null,
  },
  {
    id: "e4b8…70cd",
    kind: "task",
    description: "Set up Prometheus + Grafana observability stack",
    counterparty: "Growth Labs",
    price: 1100,
    currency: "USD",
    status: "accepted",
    createdAt: "May 23, 2024",
    outcome: null,
  },
  {
    id: "1a67…c2e9",
    kind: "gig",
    description: "Kubernetes cluster autoscaling review",
    counterparty: "FinSmart",
    price: 800,
    currency: "USD",
    status: "active",
    createdAt: "May 23, 2024",
    outcome: null,
  },
  {
    id: "9f04…ab15",
    kind: "task",
    description: "Migrate legacy VMs to containerized workloads",
    counterparty: "Research Hub",
    price: 3200,
    currency: "USD",
    status: "open",
    createdAt: "May 24, 2024",
    outcome: null,
  },
];

const FILTERS: { key: "all" | TaskStatus; label: string }[] = [
  { key: "all", label: "All" },
  { key: "open", label: "Open" },
  { key: "accepted", label: "Accepted" },
  { key: "delivered", label: "Delivered" },
  { key: "active", label: "Active" },
  { key: "completed", label: "Completed" },
];

export default function AgentTasksTab() {
  const [filter, setFilter] = useState<"all" | TaskStatus>("all");
  const shown = filter === "all" ? ITEMS : ITEMS.filter((i) => i.status === filter);

  return (
    <div className="box-border w-full h-fit shrink-0 flex flex-col gap-[12px] justify-start items-start">
      {/* Header + status filter */}
      <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[10px] justify-between items-center">
        <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-[8px] justify-start items-center">
          <div className="text-[16px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
            Tasks
          </div>
          <div className="text-[11px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            {shown.length} of {ITEMS.length}
          </div>
        </div>
        <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-[6px] justify-end items-center [flex-wrap:wrap]">
          {FILTERS.map((f) => {
            const active = f.key === filter;
            return (
              <button
                key={f.key}
                type="button"
                onClick={() => setFilter(f.key)}
                className={`box-border w-fit shrink-0 h-fit flex flex-row gap-0 p-[5px_10px] justify-start items-start rounded-[5px] cursor-pointer text-[10px] font-medium ${
                  active
                    ? "bg-[#421A97] [border:1px_solid_#7C3AED] text-[#F4F2FF]"
                    : "bg-[var(--ag2-surface)] [border:1px_solid_var(--ag2-border)] text-[var(--ag2-dim)]"
                }`}
              >
                {f.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Table */}
      <div className="box-border w-full h-fit shrink-0 flex flex-col gap-0 justify-start items-start bg-[var(--ag2-panel)] [border:1px_solid_var(--ag2-border)] rounded-[9px] overflow-hidden">
        <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[10px] p-[11px_16px] justify-start items-center bg-[var(--ag2-surface)]">
          <HeaderCell className="[flex:1_1_0] min-w-0" label="Task" />
          <HeaderCell className="w-[60px]" label="Type" />
          <HeaderCell className="w-[150px]" label="Counterparty" />
          <HeaderCell className="w-[100px]" label="Status" />
          <HeaderCell className="w-[90px]" label="Price" />
          <HeaderCell className="w-[110px]" label="Created" />
        </div>
        {shown.map((i) => {
          const s = STATUS_STYLE[i.status];
          return (
            <div
              key={i.id}
              className="box-border w-full h-fit shrink-0 flex flex-row gap-[10px] p-[12px_16px] justify-start items-center [border-width:1px_0px_0px_0px] [border-style:solid] [border-color:var(--ag2-border)]"
            >
              <div className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[3px] justify-start items-start">
                <div className="text-[12px]/[normal] box-border w-full text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-medium text-left overflow-hidden text-ellipsis [white-space:nowrap]">
                  {i.description}
                </div>
                <div className="text-[9px]/[normal] box-border text-[var(--ag2-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap] font-mono">
                  {i.id}
                  {i.outcome && <span className="text-[#35D78B]"> · {i.outcome}</span>}
                </div>
              </div>
              <div className="box-border w-[60px] shrink-0 h-fit">
                <div className="box-border w-fit h-fit flex flex-row gap-0 p-[3px_7px] justify-start items-start bg-[var(--ag2-chip)] rounded-[4px]">
                  <div className="text-[9px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]">
                    {i.kind}
                  </div>
                </div>
              </div>
              <div className="box-border w-[150px] shrink-0 h-fit text-[11px]/[normal] text-[var(--ag2-strong)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap] overflow-hidden text-ellipsis">
                {i.counterparty}
              </div>
              <div className="box-border w-[100px] shrink-0 h-fit">
                <div
                  className="box-border w-fit h-fit flex flex-row gap-0 p-[4px_8px] justify-start items-start rounded-[4px]"
                  style={{ backgroundColor: s.bg }}
                >
                  <div
                    className="text-[10px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]"
                    style={{ color: s.text }}
                  >
                    {s.label}
                  </div>
                </div>
              </div>
              <div className="box-border w-[90px] shrink-0 h-fit text-[12px]/[normal] text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
                ${i.price.toLocaleString()}
                <span className="text-[9px] text-[var(--ag2-muted)]"> {i.currency}</span>
              </div>
              <div className="box-border w-[110px] shrink-0 h-fit text-[10px]/[normal] text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                {i.createdAt}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function HeaderCell({ label, className }: { label: string; className: string }) {
  return (
    <div className={`box-border ${className} h-fit flex flex-row gap-0 justify-start items-center`}>
      <div className="text-[10px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
        {label}
      </div>
    </div>
  );
}
