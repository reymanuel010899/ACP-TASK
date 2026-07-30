"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import CreateAgentModal from "@/components/agents/CreateAgentModal";
import ConnectAgentModal from "@/components/agents/ConnectAgentModal";
import AgentLogsModal from "@/components/agents/AgentLogsModal";
import { CAPABILITY_BY_ID } from "@/data/capabilities";
import { useSession } from "@/lib/SessionProvider";
import { useAgentsList, useAgentActions, type RuntimeStatus } from "@/lib/agentQueries";

/**
 * Agents listing — runner-backed (plan 2026-07-23-002, U6). Data comes from
 * `GET /api/agents` (the runner is the lifecycle source of truth, KTD3), so the
 * list reflects MANAGED agents with REAL status: online (process up + health
 * check), starting, stopped, or error. Per-row Start/Stop/Restart/Logs act on
 * the runner; the list polls while anything is transitioning. The registry
 * remains the discovery layer running agents self-register into.
 */

const STATUS_STYLE: Record<RuntimeStatus, { label: string; color: string }> = {
  online: { label: "Online", color: "#22C55E" },
  starting: { label: "Starting…", color: "#F59E0B" },
  stopped: { label: "Stopped", color: "#6B7280" },
  offline: { label: "Unreachable", color: "#EF4444" },
  error: { label: "Error", color: "#EF4444" },
};

const AVATAR_GRADS = [
  "radial-gradient(ellipse 50% 50% at 50% 50%, #A855F7 0%, #321168 100%)",
  "radial-gradient(ellipse 50% 50% at 50% 50%, #34D399 0%, #0B3B2E 100%)",
  "radial-gradient(ellipse 50% 50% at 50% 50%, #60A5FA 0%, #0F2547 100%)",
  "radial-gradient(ellipse 50% 50% at 50% 50%, #F472B6 0%, #3A1231 100%)",
  "radial-gradient(ellipse 50% 50% at 50% 50%, #FBBF24 0%, #3A2A0B 100%)",
  "radial-gradient(ellipse 50% 50% at 50% 50%, #22D3EE 0%, #0B3038 100%)",
];

function hashSeed(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return Math.abs(h);
}
function avatarGrad(seed: string): string {
  return AVATAR_GRADS[hashSeed(seed) % AVATAR_GRADS.length];
}
function shortId(id: string): string {
  return id.length > 16 ? `${id.slice(0, 10)}…${id.slice(-4)}` : id;
}
function capLabel(id: string): string {
  return CAPABILITY_BY_ID[id]?.label ?? id;
}
function fmtDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}
function sparkPoints(seed: string): number[] {
  const h = hashSeed(seed);
  const pts: number[] = [];
  for (let i = 0; i < 9; i++) {
    const wobble = (((h >> (i * 2)) & 7) / 7 - 0.5) * 0.5;
    pts.push(Math.max(0.1, Math.min(1, 0.5 + (i / 8) * 0.25 + wobble)));
  }
  return pts;
}

// Server-side pagination page size: the runner slices, we only render.
const PAGE_SIZE = 10;

export default function AgentListContent() {
  const router = useRouter();
  const { session } = useSession();
  const [createOpen, setCreateOpen] = useState(false);
  const [connectOpen, setConnectOpen] = useState(false);
  const [logsFor, setLogsFor] = useState<{ id: string; name: string } | null>(null);
  const [query, setQuery] = useState(""); // input value (immediate)
  const [search, setSearch] = useState(""); // debounced value that drives the query
  const [page, setPage] = useState(1);

  // Debounce the search box so we don't refetch on every keystroke; a new
  // search always starts back on page 1.
  useEffect(() => {
    const t = setTimeout(() => {
      setSearch(query.trim());
      setPage(1);
    }, 300);
    return () => clearTimeout(t);
  }, [query]);

  // Server-state via TanStack Query: cached + deduped. Poll only while
  // something is transitioning so the flip to Online stays live.
  const listQuery = useAgentsList(page, search);
  const anyStarting = (listQuery.data?.agents ?? []).some((a) => a.runtime.status === "starting");
  const polledQuery = useAgentsList(page, search, { poll: anyStarting });
  const data = polledQuery.data ?? listQuery.data;
  const { lifecycle, disconnect: disconnectMut, claim: claimMut } = useAgentActions();

  const agents = data?.agents ?? [];
  const meta = {
    total: data?.total ?? 0,
    totalPages: data?.total_pages ?? 1,
    stats: data?.stats ?? { total: 0, online: 0, stopped: 0, error: 0 },
  };
  const loading = listQuery.isLoading;
  const error = listQuery.error
    ? (listQuery.error as Error).message.includes("HTTP")
      ? (listQuery.error as Error).message
      : "Could not reach the runner. Is it running (port 8110)?"
    : null;

  // The server clamps out-of-range pages (e.g. after deletions); adopt its
  // answer so the UI and the data never disagree.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (data && data.page !== page) setPage(data.page);
  }, [data, page]);

  const reload = () => void listQuery.refetch();
  const busy: Record<string, boolean> = {};
  const disconnect = (id: string) => disconnectMut.mutate(id);
  const act = (id: string, action: "start" | "stop" | "restart") =>
    lifecycle.mutate({ id, action });
  const claim = (id: string) => claimMut.mutate(id);

  // Fleet-wide stats come from the backend (computed over ALL agents, not
  // just the page in view).
  const STATS: { icon: string; iconBg: string; iconColor: string; label: string; value: string }[] = [
    { icon: "◎", iconBg: "#2A1859", iconColor: "#B276FF", label: "Total Agents", value: String(meta.stats.total) },
    { icon: "⌁", iconBg: "#0B3B2E", iconColor: "#35D78B", label: "Online", value: String(meta.stats.online) },
    { icon: "◐", iconBg: "#2A2733", iconColor: "#9CA3AF", label: "Stopped", value: String(meta.stats.stopped) },
    { icon: "⚠", iconBg: "#3A1414", iconColor: "#EF4444", label: "Errors", value: String(meta.stats.error) },
  ];

  return (
    <div className="box-border w-full [flex:1_1_0] flex flex-col gap-[14px] p-[16px_22px] justify-start items-start">
      <CreateAgentModal open={createOpen} onClose={() => setCreateOpen(false)} onCreated={reload} />
      <ConnectAgentModal open={connectOpen} onClose={() => setConnectOpen(false)} onConnected={reload} />
      <AgentLogsModal agent={logsFor} onClose={() => setLogsFor(null)} />

      {/* Header */}
      <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-start">
        <div className="box-border w-fit shrink-0 h-fit flex flex-col gap-[5px] justify-start items-start">
          <div className="text-[22px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
            Agents
          </div>
          <div className="text-[12px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            Create, deploy and manage agents running in the protocol.
          </div>
        </div>
        <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-[10px] justify-start items-center">
          <button
            type="button"
            onClick={() => setConnectOpen(true)}
            className="box-border w-fit shrink-0 h-fit flex flex-row gap-0 p-[11px_15px] justify-start items-start bg-[var(--ag2-surface)] [border:1px_solid_var(--ag2-border)] rounded-[7px] cursor-pointer"
          >
            <div className="text-[12px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
              ⇲ Connect Agent
            </div>
          </button>
          <button
            type="button"
            onClick={() => setCreateOpen(true)}
            className="box-border w-fit shrink-0 h-fit flex flex-row gap-0 p-[11px_15px] justify-start items-start bg-[#5D20DC] rounded-[7px] cursor-pointer"
          >
            <div className="text-[12px]/[normal] box-border text-[#F4F2FF] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
              ＋ New Agent
            </div>
          </button>
        </div>
      </div>

      {/* Stat cards */}
      <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[10px] justify-start items-start">
        {STATS.map((s) => (
          <div
            key={s.label}
            className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-row gap-[11px] p-[13px_14px] justify-start items-center bg-[var(--ag2-panel)] [border:1px_solid_var(--ag2-border)] rounded-[9px]"
          >
            <div className="box-border w-[38px] shrink-0 h-[38px] flex flex-row gap-0 justify-center items-center rounded-[9px]" style={{ backgroundColor: s.iconBg }}>
              <div className="text-[17px]/[normal] box-border font-[Inter,system-ui,sans-serif]" style={{ color: s.iconColor }}>
                {s.icon}
              </div>
            </div>
            <div className="box-border w-fit min-w-0 shrink h-fit flex flex-col gap-[2px] justify-start items-start">
              <div className="text-[10px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]">
                {s.label}
              </div>
              <div className="text-[19px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
                {loading ? "…" : s.value}
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Toolbar */}
      <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[10px] justify-start items-center">
        <div className="box-border w-[260px] shrink-0 h-[38px] flex flex-row gap-[9px] p-[0px_12px] justify-start items-center bg-[var(--ag2-input)] [border:1px_solid_var(--ag2-border)] rounded-[7px]">
          <div className="text-[15px] box-border text-[var(--ag2-dim)]">⌕</div>
          <input
            className="box-border [flex:1_1_0] min-w-0 h-full bg-transparent outline-none text-[12px] text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] placeholder:text-[var(--ag2-muted)]"
            placeholder="Search agents, capabilities…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search agents"
          />
        </div>
        <button
          type="button"
          onClick={reload}
          className="box-border w-fit shrink-0 h-[38px] flex flex-row gap-[6px] p-[0px_13px] justify-center items-center bg-[var(--ag2-surface)] [border:1px_solid_var(--ag2-border)] rounded-[7px] cursor-pointer text-[12px] text-[var(--ag2-text)] font-medium font-[Inter,system-ui,sans-serif]"
        >
          ↻ Refresh
        </button>
      </div>

      {/* Body */}
      {loading ? (
        <StateCard>Loading agents…</StateCard>
      ) : error ? (
        <div className="box-border w-full h-fit flex flex-col gap-[10px] p-[40px] justify-center items-center bg-[var(--ag2-panel)] [border:1px_solid_var(--ag2-border)] rounded-[9px]">
          <div className="text-[13px] box-border text-[#F87171] font-[Inter,system-ui,sans-serif] font-medium text-center">{error}</div>
          <button type="button" onClick={reload} className="box-border w-fit h-fit flex flex-row p-[8px_14px] bg-[var(--ag2-surface)] [border:1px_solid_var(--ag2-border)] rounded-[7px] cursor-pointer text-[11px] text-[var(--ag2-text)] font-semibold font-[Inter,system-ui,sans-serif]">
            ↻ Retry
          </button>
        </div>
      ) : agents.length === 0 ? (
        <div className="box-border w-full h-fit flex flex-col gap-[10px] p-[48px] justify-center items-center bg-[var(--ag2-panel)] [border:1px_dashed_var(--ag2-border)] rounded-[9px]">
          <div className="text-[26px]">🤖</div>
          <div className="text-[14px] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold">
            {meta.stats.total === 0 ? "No agents yet" : "No agents match your search"}
          </div>
          <div className="text-[11px] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] text-center max-w-[400px]">
            {meta.stats.total === 0
              ? "Create an agent, then Start it to deploy a real process into the protocol."
              : "Try a different name or capability."}
          </div>
          {meta.stats.total === 0 && (
            <button type="button" onClick={() => setCreateOpen(true)} className="box-border w-fit h-fit flex flex-row p-[10px_16px] bg-[#5D20DC] rounded-[7px] cursor-pointer text-[12px] text-[#F4F2FF] font-semibold font-[Inter,system-ui,sans-serif] mt-[4px]">
              ＋ New Agent
            </button>
          )}
        </div>
      ) : (
        <div className="box-border w-full h-fit shrink-0 flex flex-col gap-0 justify-start items-start bg-[var(--ag2-panel)] [border:1px_solid_var(--ag2-border)] rounded-[9px] overflow-hidden">
          <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[10px] p-[11px_16px] justify-start items-center bg-[var(--ag2-surface)]">
            <HeaderCell className="[flex:1_1_0] min-w-0" label="Agent" />
            <HeaderCell className="w-[104px]" label="Status" />
            <HeaderCell className="w-[184px]" label="Capabilities" />
            <HeaderCell className="w-[96px]" label="Pricing" />
            <HeaderCell className="w-[72px]" label="Activity" />
            <HeaderCell className="w-[104px]" label="Registered" />
            <HeaderCell className="w-[190px]" label="Actions" />
          </div>
          {agents.map((a) => {
            const st = STATUS_STYLE[a.runtime.status];
            const caps = a.capabilities ?? [];
            const isBusy = !!busy[a.id];
            const isOnline = a.runtime.status === "online";
            // Ownership (mirrors the runner's 403): only the owner mutates.
            // Unclaimed legacy agents (no owner) can be CLAIMED by a signed-in
            // user; until then no one may disconnect/stop them.
            const isOwner = !!session && a.owner_principal_id === session.principalId;
            const isUnclaimed = !a.owner_principal_id;
            return (
              <div
                key={a.id}
                role="link"
                tabIndex={0}
                onClick={() => router.push(`/agents/${encodeURIComponent(a.id)}`)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") router.push(`/agents/${encodeURIComponent(a.id)}`);
                }}
                className="box-border w-full h-fit shrink-0 flex flex-row gap-[10px] p-[12px_16px] justify-start items-center [border-width:1px_0px_0px_0px] [border-style:solid] [border-color:var(--ag2-border)] cursor-pointer hover:bg-[var(--ag2-surface)] transition-colors"
              >
                <div className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-row gap-[10px] justify-start items-center">
                  <div className="box-border w-[34px] shrink-0 h-[34px] [border:1px_solid_#8B5CF6] rounded-full" style={{ backgroundImage: avatarGrad(a.id) }}></div>
                  <div className="box-border min-w-0 h-fit flex flex-col gap-[3px] justify-start items-start">
                    <div className="box-border flex flex-row gap-[6px] items-center">
                      <div className="text-[12px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
                        {a.name}
                      </div>
                      <div
                        className={`box-border w-fit flex flex-row p-[2px_6px] rounded-[4px] text-[9px] font-semibold font-[Inter,system-ui,sans-serif] [white-space:nowrap] ${
                          a.kind === "connected" ? "bg-[#1E3A5F] text-[#7DD3FC]" : "bg-[#2A1859] text-[#C69AFF]"
                        }`}
                      >
                        {a.kind === "connected" ? "Connected" : "Managed"}
                      </div>
                      {a.trust_tier && (
                        <div
                          title={
                            a.trust_tier === "verified"
                              ? "Transactable — speaks the negotiation protocol: agree a price, get evidence for the work, provable reputation."
                              : "Discovery only — listed and reachable, but it does not understand the negotiation payloads. No price negotiation, no verifiable result."
                          }
                          className={`box-border w-fit flex flex-row p-[2px_6px] rounded-[4px] text-[9px] font-semibold font-[Inter,system-ui,sans-serif] [white-space:nowrap] ${
                            a.trust_tier === "verified" ? "bg-[#073C31] text-[#38D996]" : "bg-[#3A2A0B] text-[#FBBF24]"
                          }`}
                        >
                          {a.trust_tier === "verified" ? "✓ Transactable" : "Discovery only"}
                        </div>
                      )}
                    </div>
                    <div className="text-[10px]/[normal] box-border text-[var(--ag2-muted)] font-mono text-left [white-space:nowrap] overflow-hidden text-ellipsis max-w-[300px]">
                      {a.kind === "connected"
                        ? a.endpoint_url
                        : `${a.version ? `v${a.version} · ` : ""}${a.runtime.principal_id ? shortId(a.runtime.principal_id) : a.template}`}
                    </div>
                  </div>
                </div>
                <div className="box-border w-[104px] shrink-0 h-fit flex flex-row gap-[6px] justify-start items-center">
                  <div className="box-border w-[7px] shrink-0 h-[7px] rounded-full" style={{ backgroundColor: st.color }}></div>
                  <div className="text-[11px]/[normal] box-border text-[var(--ag2-strong)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                    {st.label}
                  </div>
                </div>
                <div className="box-border w-[184px] shrink-0 h-fit flex flex-row gap-[5px] justify-start items-center [flex-wrap:nowrap] overflow-hidden">
                  {caps.slice(0, 2).map((id) => (
                    <div key={id} className="box-border w-fit shrink-0 h-fit flex flex-row p-[4px_7px] bg-[var(--ag2-chip)] rounded-[4px]">
                      <div className="text-[9px]/[normal] box-border text-[#A78BFA] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]">{capLabel(id)}</div>
                    </div>
                  ))}
                  {caps.length > 2 && (
                    <div className="box-border w-fit shrink-0 h-fit flex flex-row p-[4px_7px] bg-[var(--ag2-surface)] rounded-[4px]">
                      <div className="text-[9px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]">+{caps.length - 2}</div>
                    </div>
                  )}
                </div>
                <div className="box-border w-[96px] shrink-0 h-fit text-[11px]/[normal] text-[var(--ag2-strong)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                  {a.list_price ?? "—"}
                  <span className="text-[var(--ag2-muted)]"> / {a.min_price ?? "—"}</span>
                </div>
                <div className="box-border w-[72px] shrink-0 h-fit">
                  <Sparkline points={sparkPoints(a.id)} color={isOnline ? "#35D78B" : "var(--ag2-border)"} />
                </div>
                <div className="box-border w-[104px] shrink-0 h-fit text-[10px]/[normal] text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                  {fmtDate(a.created_at)}
                </div>
                <div className="box-border w-[190px] shrink-0 h-fit flex flex-row gap-[6px] justify-start items-center">
                  {a.kind === "connected" ? (
                    <>
                      {/* hosted elsewhere: we don't run it, we only track it */}
                      <ActionBtn label="Recheck" disabled={isBusy} onClick={reload} tone="ghost" />
                      {isOwner ? (
                        <ActionBtn label="Disconnect" disabled={isBusy} onClick={() => disconnect(a.id)} tone="danger" />
                      ) : isUnclaimed && session ? (
                        <ActionBtn label="Claim" disabled={isBusy} onClick={() => claim(a.id)} tone="primary" />
                      ) : (
                        <OwnerOnlyBadge />
                      )}
                    </>
                  ) : isOwner ? (
                    <>
                      {isOnline ? (
                        <ActionBtn label="Stop" disabled={isBusy} onClick={() => act(a.id, "stop")} tone="danger" />
                      ) : (
                        <ActionBtn label={isBusy ? "…" : "Start"} disabled={isBusy} onClick={() => act(a.id, "start")} tone="primary" />
                      )}
                      <ActionBtn label="Restart" disabled={isBusy} onClick={() => act(a.id, "restart")} tone="ghost" />
                      <ActionBtn label="Logs" onClick={() => setLogsFor({ id: a.id, name: a.name })} tone="ghost" />
                    </>
                  ) : isUnclaimed && session ? (
                    <ActionBtn label="Claim" disabled={isBusy} onClick={() => claim(a.id)} tone="primary" />
                  ) : (
                    <OwnerOnlyBadge />
                  )}
                </div>
              </div>
            );
          })}
          {meta.totalPages > 1 && (
            <Pagination
              page={page}
              totalPages={meta.totalPages}
              totalItems={meta.total}
              pageSize={PAGE_SIZE}
              onPage={setPage}
            />
          )}
        </div>
      )}
    </div>
  );
}

/** Sleek pagination footer: range summary on the left, pill controls on the
 * right — numbered pages with ellipsis windows, a glowing active pill, and
 * prev/next chevrons. Lives inside the table card, styled on the same
 * --ag2 tokens. */
function Pagination({
  page,
  totalPages,
  totalItems,
  pageSize,
  onPage,
}: {
  page: number;
  totalPages: number;
  totalItems: number;
  pageSize: number;
  onPage: (p: number) => void;
}) {
  const from = (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, totalItems);

  // Windowed page numbers: 1 … (page-1, page, page+1) … last
  const items: (number | "…")[] = [];
  for (let p = 1; p <= totalPages; p++) {
    if (p === 1 || p === totalPages || Math.abs(p - page) <= 1) {
      items.push(p);
    } else if (items[items.length - 1] !== "…") {
      items.push("…");
    }
  }

  const chevron =
    "box-border w-[32px] h-[32px] flex justify-center items-center rounded-full bg-[var(--ag2-surface)] [border:1px_solid_var(--ag2-border)] text-[var(--ag2-strong)] text-[13px] cursor-pointer transition-all duration-150 hover:[border-color:#5D20DC] hover:text-[#B276FF] disabled:opacity-35 disabled:cursor-not-allowed disabled:hover:[border-color:var(--ag2-border)] disabled:hover:text-[var(--ag2-strong)]";

  return (
    <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[10px] p-[12px_16px] justify-between items-center [border-top:1px_solid_var(--ag2-border)] bg-[var(--ag2-surface)]">
      <div className="text-[11px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif]">
        Showing <span className="text-[var(--ag2-text)] font-semibold">{from}–{to}</span> of{" "}
        <span className="text-[var(--ag2-text)] font-semibold">{totalItems}</span> agents
      </div>
      <div className="box-border w-fit h-fit flex flex-row gap-[6px] justify-end items-center">
        <button type="button" aria-label="Previous page" disabled={page === 1} onClick={() => onPage(page - 1)} className={chevron}>
          ‹
        </button>
        {items.map((it, i) =>
          it === "…" ? (
            <span key={`gap-${i}`} className="box-border w-[24px] text-center text-[12px] text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] select-none">
              …
            </span>
          ) : (
            <button
              key={it}
              type="button"
              aria-label={`Page ${it}`}
              aria-current={it === page ? "page" : undefined}
              onClick={() => onPage(it)}
              className={
                it === page
                  ? "box-border min-w-[32px] h-[32px] px-[6px] flex justify-center items-center rounded-full bg-[#5D20DC] text-[#F4F2FF] text-[12px] font-bold font-[Inter,system-ui,sans-serif] cursor-default shadow-[0_0_14px_rgba(93,32,220,0.55)]"
                  : "box-border min-w-[32px] h-[32px] px-[6px] flex justify-center items-center rounded-full bg-transparent text-[var(--ag2-dim)] text-[12px] font-semibold font-[Inter,system-ui,sans-serif] cursor-pointer transition-all duration-150 hover:bg-[var(--ag2-panel)] hover:text-[var(--ag2-text)]"
              }
            >
              {it}
            </button>
          ),
        )}
        <button type="button" aria-label="Next page" disabled={page === totalPages} onClick={() => onPage(page + 1)} className={chevron}>
          ›
        </button>
      </div>
    </div>
  );
}

function ActionBtn({
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
      onClick={(e) => {
        e.stopPropagation(); // never let a row action navigate to the detail
        onClick();
      }}
      disabled={disabled}
      className={`box-border w-fit h-fit flex flex-row p-[6px_10px] justify-center items-center rounded-[6px] cursor-pointer text-[10px] font-semibold font-[Inter,system-ui,sans-serif] disabled:opacity-50 disabled:cursor-not-allowed ${cls}`}
    >
      {label}
    </button>
  );
}

/** Shown in place of mutating actions when the viewer doesn't own the agent. */
function OwnerOnlyBadge() {
  return (
    <span
      title="Only the user who added this agent can manage it"
      className="box-border w-fit h-fit flex flex-row gap-[4px] px-[9px] py-[5px] items-center rounded-full bg-[var(--ag2-chip)] [border:1px_solid_var(--ag2-border)] text-[10px] text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] select-none"
    >
      🔒 Owner only
    </span>
  );
}

function HeaderCell({ label, className }: { label: string; className: string }) {
  return (
    <div className={`box-border ${className} h-fit flex flex-row gap-0 justify-start items-center`}>
      <div className="text-[10px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">{label}</div>
    </div>
  );
}

function Sparkline({ points, color }: { points: number[]; color: string }) {
  const w = 60;
  const h = 20;
  const max = Math.max(...points);
  const min = Math.min(...points);
  const span = max - min || 1;
  const d = points
    .map((v, i) => {
      const x = (i / (points.length - 1)) * w;
      const y = h - ((v - min) / span) * (h - 3) - 1.5;
      return `${i === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg" className="box-border w-[60px] h-[20px] overflow-visible">
      <path d={d} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function StateCard({ children }: { children: React.ReactNode }) {
  return (
    <div className="box-border w-full h-fit flex flex-col gap-[8px] p-[40px] justify-center items-center bg-[var(--ag2-panel)] [border:1px_solid_var(--ag2-border)] rounded-[9px]">
      <div className="text-[12px] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif]">{children}</div>
    </div>
  );
}
