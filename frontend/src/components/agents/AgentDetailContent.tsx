"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useSession } from "@/lib/SessionProvider";
import { useAgentDetail, useAgentActions } from "@/lib/agentQueries";
import { CAPABILITY_BY_ID } from "@/data/capabilities";
import AgentOverviewTab from "@/components/agents/AgentOverviewTab";
import AgentPerformanceTab from "@/components/agents/AgentPerformanceTab";
import AgentTasksTab from "@/components/agents/AgentTasksTab";
import AgentCredentialsTab from "@/components/agents/AgentCredentialsTab";
import AgentReviewsTab from "@/components/agents/AgentReviewsTab";
import AgentActivityTab from "@/components/agents/AgentActivityTab";
import AgentSettingsTab from "@/components/agents/AgentSettingsTab";

/**
 * Agent detail — REAL data for the clicked agent, fetched from the runner via
 * `GET /api/agents/{id}`. Shows identity, endpoint, trust tier and lifecycle
 * controls. Overview, Capabilities and Logs render this agent's real data;
 * the remaining tabs keep their full UI but are not wired to a data source yet,
 * so they carry a "sample data" banner (see SAMPLE_TABS) rather than passing
 * placeholder figures off as this agent's real activity.
 */

type RuntimeStatus = "online" | "starting" | "stopped" | "offline" | "error";

type Agent = {
  id: string;
  /** principal_id of the USER who added this agent; only they may mutate it. */
  owner_principal_id?: string | null;
  kind: "managed" | "connected";
  trust_tier?: "verified" | "basic";
  name: string;
  description?: string;
  version?: string;
  template: string | null;
  endpoint_url: string | null;
  capabilities: string[];
  list_price: number | null;
  min_price: number | null;
  created_at: string;
  runtime: {
    status: RuntimeStatus;
    pid: number | null;
    port: number | null;
    url: string | null;
    principal_id: string | null;
    error: string | null;
  };
};

const STATUS_STYLE: Record<RuntimeStatus, { label: string; color: string }> = {
  online: { label: "Online", color: "#22C55E" },
  starting: { label: "Starting…", color: "#F59E0B" },
  stopped: { label: "Stopped", color: "#6B7280" },
  offline: { label: "Unreachable", color: "#EF4444" },
  error: { label: "Error", color: "#EF4444" },
};

type TabKey =
  | "overview"
  | "capabilities"
  | "performance"
  | "tasks"
  | "credentials"
  | "reviews"
  | "activity"
  | "settings"
  | "logs";

/**
 * Tabs whose content is not yet wired to the backend. They keep their full UI,
 * but carry a banner so nobody reads sample figures as this agent's real
 * numbers. Remove a key from here once its data source lands.
 */
const SAMPLE_TABS: TabKey[] = ["performance", "tasks", "credentials", "reviews", "activity", "settings"];

function SampleNotice() {
  return (
    <div className="box-border w-full flex flex-row gap-[8px] p-[9px_12px] mb-[12px] bg-[#2A2208] [border:1px_solid_#5a4a1a] rounded-[8px] items-center">
      <div className="text-[12px] text-[#FBBF24]">⚠</div>
      <div className="text-[11px]/[1.5] box-border text-[#FDE68A] font-[Inter,system-ui,sans-serif]">
        <b>Sample data</b> — this view isn&apos;t wired to the backend yet, so the figures below are placeholders,
        not this agent&apos;s real activity.
      </div>
    </div>
  );
}

function capLabel(id: string): string {
  return CAPABILITY_BY_ID[id]?.label ?? id;
}
function fmtDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? "—"
    : d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export default function AgentDetailContent({ agentId }: { agentId: string }) {
  const router = useRouter();
  const { session } = useSession();
  const [tab, setTab] = useState<TabKey>("overview");
  const [logs, setLogs] = useState<string[] | null>(null);

  // Server-state via TanStack Query: the detail is cached and shares
  // invalidation with the list — a lifecycle action refreshes both at once.
  const detailQuery = useAgentDetail(agentId);
  const { lifecycle, disconnect: disconnectMut, claim: claimMut } = useAgentActions();
  const agent = (detailQuery.data ?? null) as Agent | null;
  const loading = detailQuery.isLoading;
  const error = detailQuery.error ? (detailQuery.error as Error).message : null;
  const busy = lifecycle.isPending || disconnectMut.isPending || claimMut.isPending;
  const runFetch = () => void detailQuery.refetch();

  const loadLogs = useCallback(async () => {
    try {
      const res = await fetch(`/api/agents/${encodeURIComponent(agentId)}/logs?tail=300`, { cache: "no-store" });
      const data = (await res.json()) as { logs?: string[] };
      setLogs(Array.isArray(data.logs) ? data.logs : []);
    } catch {
      setLogs([]);
    }
  }, [agentId]);

  useEffect(() => {
    if (tab !== "logs") return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadLogs();
  }, [tab, loadLogs]);

  function act(action: "start" | "stop" | "restart") {
    lifecycle.mutate({ id: agentId, action });
  }

  function disconnect() {
    disconnectMut.mutate(agentId, { onSuccess: () => router.push("/agents") });
  }

  if (loading) {
    return <Shell><StateCard>Loading agent…</StateCard></Shell>;
  }
  if (error || !agent) {
    return (
      <Shell>
        <div className="box-border w-full flex flex-col gap-[10px] p-[40px] justify-center items-center bg-[var(--ag2-panel)] [border:1px_solid_var(--ag2-border)] rounded-[9px]">
          <div className="text-[13px] text-[#F87171] font-[Inter,system-ui,sans-serif] font-medium">{error}</div>
          <Link href="/agents" className="text-[11px] text-[#B267FF] font-[Inter,system-ui,sans-serif] font-semibold">
            ← Back to agents
          </Link>
        </div>
      </Shell>
    );
  }

  const st = STATUS_STYLE[agent.runtime.status];
  const isOnline = agent.runtime.status === "online";
  const isManaged = agent.kind === "managed";
  // Ownership (mirrors the runner's 403): only the owner mutates. Unclaimed
  // legacy agents can be claimed by a signed-in user; until then, locked.
  const isOwner = !!session && agent.owner_principal_id === session.principalId;
  const isUnclaimed = !agent.owner_principal_id;
  const claim = () => claimMut.mutate(agentId);
  const TABS: { key: TabKey; label: string }[] = [
    { key: "overview", label: "Overview" },
    { key: "capabilities", label: "Capabilities" },
    { key: "performance", label: "Performance" },
    { key: "tasks", label: "Tasks" },
    { key: "credentials", label: "Credentials" },
    { key: "reviews", label: "Reviews" },
    { key: "activity", label: "Activity" },
    { key: "settings", label: "Settings" },
    ...(isManaged ? [{ key: "logs" as TabKey, label: "Logs" }] : []),
  ];

  return (
    <Shell>
      {/* Breadcrumb */}
      <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[7px] justify-start items-center">
        <div className="text-[13px] box-border text-[#7C3AED]">✧</div>
        <Link href="/agents" className="text-[12px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] hover:text-[var(--ag2-text)]">
          Agents
        </Link>
        <div className="text-[12px] box-border text-[var(--ag2-muted)]">/</div>
        <div className="text-[12px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-semibold [white-space:nowrap]">
          {agent.name}
        </div>
      </div>

      {/* Header */}
      <div className="box-border w-full max-w-full h-fit shrink-0 flex flex-row gap-[16px] p-[4px_0px_10px_0px] justify-start items-start">
        <div className="box-border w-[64px] shrink-0 h-[64px] [background-image:radial-gradient(ellipse_50%_50%_at_50%_50%,_#A855F7_0%,_#321168_100%)] [border:1px_solid_#8B5CF6] rounded-full"></div>
        <div className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[6px] justify-start items-start">
            {/* name, badges and the lifecycle actions share one wrapping row so
                a long description can never push the buttons off-screen */}
            <div className="box-border w-full flex flex-row gap-[10px] items-center [flex-wrap:wrap]">
              <div className="text-[24px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold">
                {agent.name}
              </div>
              <Badge tone={agent.kind === "connected" ? "blue" : "purple"}>
                {agent.kind === "connected" ? "Connected" : "Managed"}
              </Badge>
              {agent.trust_tier && (
                <Badge tone={agent.trust_tier === "verified" ? "green" : "amber"}>
                  {agent.trust_tier === "verified" ? "✓ Transactable" : "Discovery only"}
                </Badge>
              )}
              <div className="box-border w-fit flex flex-row gap-[8px] items-center [flex-wrap:wrap]">
                {/* Ownership: only the owner mutates (runner 403 enforces).
                    Unclaimed legacy agents show Claim to a signed-in user. */}
                {isManaged ? (
                  isOwner ? (
                    <>
                      {isOnline ? (
                        <Action label="Stop" tone="danger" disabled={busy} onClick={() => act("stop")} />
                      ) : (
                        <Action label={busy ? "…" : "Start"} tone="primary" disabled={busy} onClick={() => act("start")} />
                      )}
                      <Action label="Restart" tone="ghost" disabled={busy} onClick={() => act("restart")} />
                    </>
                  ) : isUnclaimed && session ? (
                    <Action label={busy ? "…" : "Claim"} tone="primary" disabled={busy} onClick={claim} />
                  ) : (
                    <OwnerOnly />
                  )
                ) : (
                  <>
                    <Action label="Recheck" tone="ghost" disabled={busy} onClick={() => void runFetch()} />
                    {isOwner ? (
                      <Action label="Disconnect" tone="danger" disabled={busy} onClick={disconnect} />
                    ) : isUnclaimed && session ? (
                      <Action label={busy ? "…" : "Claim"} tone="primary" disabled={busy} onClick={claim} />
                    ) : (
                      <OwnerOnly />
                    )}
                  </>
                )}
              </div>
            </div>
            <div className="text-[12px]/[1.5] box-border w-full max-w-[860px] text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif]">
              {agent.description || "No description published."}
            </div>
            <div className="box-border flex flex-row gap-[7px] items-center">
              <div className="box-border w-[7px] h-[7px] rounded-full" style={{ backgroundColor: st.color }}></div>
              <div className="text-[12px]/[normal] box-border text-[var(--ag2-strong)] font-[Inter,system-ui,sans-serif]">
                {st.label}
              </div>
              {agent.runtime.error && (
                <div className="text-[11px]/[normal] box-border text-[#F87171] font-[Inter,system-ui,sans-serif]">
                  · {agent.runtime.error}
                </div>
              )}
            </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[22px] [flex-wrap:wrap] p-[10px_0px_11px_0px] justify-start items-start [border-width:0px_0px_1px_0px] [border-style:solid] [border-color:var(--ag2-border)]">
        {TABS.map((tb) => {
          const active = tb.key === tab;
          return (
            <button
              key={tb.key}
              type="button"
              onClick={() => setTab(tb.key)}
              className={`box-border w-fit h-fit flex flex-row p-[0px_0px_9px_0px] cursor-pointer [border-width:0px_0px_2px_0px] [border-style:solid] ${
                active ? "[border-color:#8B5CF6]" : "[border-color:#00000000]"
              }`}
            >
              <div
                className={`text-[12px]/[normal] box-border font-[Inter,system-ui,sans-serif] [white-space:nowrap] ${
                  active ? "text-[#B36BFF] font-semibold" : "text-[var(--ag2-dim)] font-normal"
                }`}
              >
                {tb.label}
              </div>
            </button>
          );
        })}
      </div>

      {tab === "overview" && (
        <>
          {/* This agent's real, backend-backed facts sit above the rich
              overview, which is still sample content. */}
          <div className="box-border w-full flex flex-row gap-[12px] items-start [flex-wrap:wrap]">
          <Panel title="Identity">
            <Field label="Agent ID" value={agent.id} mono />
            <Field label="Principal ID" value={agent.runtime.principal_id ?? "— assigned on deploy"} mono />
            <Field label="Trust tier" value={agent.trust_tier === "verified" ? "Verified · transactable" : "Basic · discovery only"} />
            <Field label="Registered" value={fmtDate(agent.created_at)} />
          </Panel>
          <Panel title={isManaged ? "Runtime" : "Endpoint"}>
            {isManaged ? (
              <>
                <Field label="Template" value={agent.template ?? "—"} mono />
                <Field label="Endpoint" value={agent.runtime.url ?? "— not running"} mono />
                <Field label="Process" value={agent.runtime.pid ? `pid ${agent.runtime.pid} · port ${agent.runtime.port}` : "— not running"} />
                <Field label="Pricing" value={`list ${agent.list_price ?? "—"} · min ${agent.min_price ?? "—"}`} />
              </>
            ) : (
              <>
                <Field label="Hosted at" value={agent.endpoint_url ?? "—"} mono />
                <Field label="Version" value={agent.version ?? "—"} />
                <div className="text-[10px]/[1.5] box-border text-[var(--ag2-muted)] font-[Inter,system-ui,sans-serif]">
                  Runs on its owner&apos;s infrastructure. We track its health; requesters call it directly at this URL.
                </div>
              </>
            )}
          </Panel>
          </div>
          <SampleNotice />
          <AgentOverviewTab />
        </>
      )}

      {tab === "capabilities" && (
        <div className="box-border w-full flex flex-col gap-[10px] p-[16px] bg-[var(--ag2-panel)] [border:1px_solid_var(--ag2-border)] rounded-[9px]">
          <div className="text-[13px] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold">
            Declared capabilities ({agent.capabilities.length})
          </div>
          {agent.capabilities.length === 0 ? (
            <div className="text-[11px] text-[var(--ag2-muted)] font-[Inter,system-ui,sans-serif]">None declared.</div>
          ) : (
            <div className="box-border w-full flex flex-col gap-[6px]">
              {agent.capabilities.map((id) => (
                <div key={id} className="box-border w-full flex flex-row gap-[10px] p-[8px_10px] justify-start items-center bg-[var(--ag2-surface)] rounded-[6px]">
                  <div className="box-border [flex:1_1_0] text-[12px] text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-medium">
                    {capLabel(id)}
                  </div>
                  <div className="box-border w-fit text-[10px] text-[var(--ag2-muted)] font-mono">{id}</div>
                </div>
              ))}
            </div>
          )}
          <div className="text-[10px]/[1.5] box-border text-[var(--ag2-muted)] font-[Inter,system-ui,sans-serif] pt-[4px]">
            These are published to the registry, so requesters discover this agent by them.
          </div>
        </div>
      )}

      {SAMPLE_TABS.includes(tab) && (
        <div className="box-border w-full flex flex-col">
          <SampleNotice />
          {tab === "performance" && <AgentPerformanceTab />}
          {tab === "tasks" && <AgentTasksTab />}
          {tab === "credentials" && <AgentCredentialsTab />}
          {tab === "reviews" && <AgentReviewsTab />}
          {tab === "activity" && <AgentActivityTab />}
          {tab === "settings" && <AgentSettingsTab />}
        </div>
      )}

      {tab === "logs" && (
        <div className="box-border w-full flex flex-col gap-[8px]">
          <div className="box-border w-full flex flex-row justify-between items-center">
            <div className="text-[13px] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold">Process logs</div>
            <Action label="↻ Refresh" tone="ghost" onClick={() => void loadLogs()} />
          </div>
          <div className="box-border w-full max-h-[380px] overflow-auto p-[12px_14px] bg-[var(--ag2-input-deep)] [border:1px_solid_var(--ag2-border)] rounded-[9px]">
            {logs === null ? (
              <div className="text-[11px] text-[var(--ag2-muted)] font-mono">Loading…</div>
            ) : logs.length === 0 ? (
              <div className="text-[11px] text-[var(--ag2-muted)] font-mono">No logs yet — start the agent to produce output.</div>
            ) : (
              logs.map((ln, i) => (
                <div key={i} className="text-[11px]/[1.5] box-border text-[var(--ag2-strong)] font-mono break-all whitespace-pre-wrap">
                  {ln || " "}
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="box-border w-full max-w-full min-w-0 [flex:1_1_0] flex flex-col gap-[14px] p-[20px_24px_24px_24px] justify-start items-start overflow-x-hidden">
      {children}
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="box-border [flex:1_1_320px] min-w-[300px] flex flex-col gap-[10px] p-[16px] bg-[var(--ag2-panel)] [border:1px_solid_var(--ag2-border)] rounded-[9px]">
      <div className="text-[13px] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold">{title}</div>
      {children}
    </div>
  );
}

function Field({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="box-border w-full flex flex-col gap-[2px]">
      <div className="text-[10px] box-border text-[var(--ag2-muted)] font-[Inter,system-ui,sans-serif]">{label}</div>
      <div className={`text-[12px]/[normal] box-border w-full text-[var(--ag2-strong)] break-all ${mono ? "font-mono" : "font-[Inter,system-ui,sans-serif] font-medium"}`}>
        {value}
      </div>
    </div>
  );
}

/** Shown in place of mutating actions when the viewer doesn't own the agent. */
function OwnerOnly() {
  return (
    <span
      title="Only the user who added this agent can manage it"
      className="box-border w-fit h-fit flex flex-row gap-[4px] px-[10px] py-[6px] items-center rounded-full bg-[var(--ag2-chip)] [border:1px_solid_var(--ag2-border)] text-[11px] text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] select-none"
    >
      🔒 Owner only
    </span>
  );
}

function Badge({ tone, children }: { tone: "blue" | "purple" | "green" | "amber"; children: React.ReactNode }) {
  const cls = {
    blue: "bg-[#1E3A5F] text-[#7DD3FC]",
    purple: "bg-[#2A1859] text-[#C69AFF]",
    green: "bg-[#073C31] text-[#38D996]",
    amber: "bg-[#3A2A0B] text-[#FBBF24]",
  }[tone];
  return (
    <div className={`box-border w-fit flex flex-row p-[3px_8px] rounded-[4px] text-[10px] font-semibold font-[Inter,system-ui,sans-serif] [white-space:nowrap] ${cls}`}>
      {children}
    </div>
  );
}

function Action({
  label,
  onClick,
  disabled,
  tone,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  tone: "primary" | "danger" | "ghost";
}) {
  const cls =
    tone === "primary"
      ? "bg-[#5D20DC] text-[#F4F2FF]"
      : tone === "danger"
        ? "bg-[#2A1518] [border:1px_solid_#5a2330] text-[#F87171]"
        : "bg-[var(--ag2-surface)] [border:1px_solid_var(--ag2-border)] text-[var(--ag2-strong)]";
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`box-border w-fit h-fit flex flex-row p-[8px_13px] justify-center items-center rounded-[7px] cursor-pointer text-[11px] font-semibold font-[Inter,system-ui,sans-serif] disabled:opacity-50 disabled:cursor-not-allowed ${cls}`}
    >
      {label}
    </button>
  );
}

function StateCard({ children }: { children: React.ReactNode }) {
  return (
    <div className="box-border w-full flex flex-col gap-[8px] p-[40px] justify-center items-center bg-[var(--ag2-panel)] [border:1px_solid_var(--ag2-border)] rounded-[9px]">
      <div className="text-[12px] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif]">{children}</div>
    </div>
  );
}
