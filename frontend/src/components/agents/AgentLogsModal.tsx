"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Agent logs viewer (plan 2026-07-23-002, U7). Fetches
 * `GET /api/agents/{id}/logs` (the runner's captured process stdout/stderr) and
 * renders it in a scrollable mono box. Refresh + auto-tail; empty/error states.
 */
export default function AgentLogsModal({
  agent,
  onClose,
}: {
  agent: { id: string; name: string } | null;
  onClose: () => void;
}) {
  const [lines, setLines] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [auto, setAuto] = useState(true);
  const boxRef = useRef<HTMLDivElement | null>(null);

  const load = useCallback(async () => {
    if (!agent) return;
    try {
      const res = await fetch(`/api/agents/${encodeURIComponent(agent.id)}/logs?tail=400`, { cache: "no-store" });
      if (!res.ok) {
        setError(`Could not load logs (HTTP ${res.status}).`);
        return;
      }
      const data = (await res.json()) as { logs?: string[] };
      setError(null);
      setLines(Array.isArray(data.logs) ? data.logs : []);
    } catch {
      setError("Could not reach the runner.");
    } finally {
      setLoading(false);
    }
  }, [agent]);

  useEffect(() => {
    if (!agent) return;
    // load() sets loading=false in its finally; the initial state is true so the
    // first open shows a loading state without a synchronous setState here.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [agent, load, onClose]);

  useEffect(() => {
    if (!agent || !auto) return;
    const t = setInterval(() => void load(), 3000);
    return () => clearInterval(t);
  }, [agent, auto, load]);

  useEffect(() => {
    if (auto && boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight;
  }, [lines, auto]);

  if (!agent) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-[20px] bg-[rgba(4,3,12,0.62)]"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Logs for ${agent.name}`}
        className="box-border w-[820px] max-w-[94vw] h-[560px] max-h-[88vh] flex flex-col bg-[var(--ag2-panel)] [border:1px_solid_var(--ag2-border)] rounded-[12px] overflow-hidden shadow-2xl"
      >
        <div className="box-border w-full shrink-0 flex flex-row gap-0 p-[14px_18px] justify-between items-center [border-width:0px_0px_1px_0px] [border-style:solid] [border-color:var(--ag2-border)]">
          <div className="box-border flex flex-col gap-[2px]">
            <div className="text-[14px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
              Logs — {agent.name}
            </div>
            <div className="text-[10px]/[normal] box-border text-[var(--ag2-dim)] font-mono text-left [white-space:nowrap]">{agent.id}</div>
          </div>
          <div className="box-border flex flex-row gap-[8px] items-center">
            <button
              type="button"
              onClick={() => setAuto((v) => !v)}
              className={`box-border h-[28px] flex flex-row p-[0px_10px] justify-center items-center rounded-[6px] cursor-pointer text-[10px] font-semibold font-[Inter,system-ui,sans-serif] ${
                auto ? "bg-[#5D20DC] text-[#F4F2FF]" : "bg-[var(--ag2-surface)] [border:1px_solid_var(--ag2-border)] text-[var(--ag2-dim)]"
              }`}
            >
              {auto ? "Auto-tail on" : "Auto-tail off"}
            </button>
            <button type="button" onClick={() => void load()} className="box-border h-[28px] flex flex-row p-[0px_10px] justify-center items-center rounded-[6px] cursor-pointer text-[10px] font-semibold font-[Inter,system-ui,sans-serif] bg-[var(--ag2-surface)] [border:1px_solid_var(--ag2-border)] text-[var(--ag2-text)]">
              ↻ Refresh
            </button>
            <button type="button" onClick={onClose} aria-label="Close" className="box-border w-[28px] h-[28px] flex items-center justify-center rounded-[6px] bg-[var(--ag2-surface)] [border:1px_solid_var(--ag2-border)] text-[var(--ag2-dim)] text-[13px] cursor-pointer">
              ✕
            </button>
          </div>
        </div>
        <div ref={boxRef} className="box-border w-full [flex:1_1_0] min-h-0 overflow-auto p-[14px_16px] bg-[var(--ag2-input-deep)]">
          {loading ? (
            <div className="text-[11px] text-[var(--ag2-muted)] font-mono">Loading logs…</div>
          ) : error ? (
            <div className="text-[11px] text-[#F87171] font-mono">{error}</div>
          ) : lines.length === 0 ? (
            <div className="text-[11px] text-[var(--ag2-muted)] font-mono">No logs yet — start the agent to produce output.</div>
          ) : (
            lines.map((ln, i) => (
              <div key={i} className="text-[11px]/[1.5] box-border text-[var(--ag2-strong)] font-mono text-left break-all whitespace-pre-wrap">
                {ln || " "}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
