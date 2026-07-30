"use client";

// Floating "client console" — a conversation with the LLM concierge orchestrator
// (`agents/orchestrator` via `web/concierge.py`). You describe what you need in
// plain language; the concierge turns it into intent, discovers candidate
// agents, negotiates, gates spend, executes, and replies. Multi-turn: if it
// needs more detail it asks, and you answer in the next message. The console
// never orchestrates itself — it just shows the concierge's replies.

import { useEffect, useRef, useState } from "react";
import WorkflowPreviewCard, { type WorkflowPreview } from "@/components/concierge/WorkflowPreviewCard";

type Brain = "claude" | "groq" | "rule";
type Reply = {
  status?: string;
  reply?: string;
  evidence?: Record<string, unknown>;
  brain?: Brain;
  workflow?: WorkflowPreview;
};
type LogItem = { type: "user"; text: string } | { type: "concierge"; reply: Reply };

export const CHAT_INACTIVITY_MS = 3 * 60 * 1000;

const EXAMPLES = [
  "necesito enviar un paquete a Santiago",
  "busco a alguien que me genere infraestructura terraform",
  "necesito que hagan una tarea del marketplace",
];

const STATUS_LABEL: Record<string, { text: string; cls: string }> = {
  verified: { text: "VERIFIED", cls: "bg-[color-mix(in_srgb,var(--ag-green)_18%,transparent)] text-[var(--ag-green)]" },
  done: { text: "DONE", cls: "bg-[color-mix(in_srgb,var(--ag-green)_18%,transparent)] text-[var(--ag-green)]" },
  completed: { text: "DONE", cls: "bg-[color-mix(in_srgb,var(--ag-green)_18%,transparent)] text-[var(--ag-green)]" },
  cancelled: { text: "CANCELLED", cls: "bg-[var(--ag-chip)] text-[var(--ag-text-muted)]" },
  declined: { text: "DECLINED", cls: "bg-[color-mix(in_srgb,var(--ag-orange)_18%,transparent)] text-[var(--ag-orange)]" },
  needs_clarification: { text: "NEEDS INFO", cls: "bg-[color-mix(in_srgb,var(--ag-orange)_18%,transparent)] text-[var(--ag-orange)]" },
  needs_approval: { text: "APPROVAL", cls: "bg-[color-mix(in_srgb,var(--ag-orange)_18%,transparent)] text-[var(--ag-orange)]" },
  workflow_preview: { text: "PLAN", cls: "bg-[color-mix(in_srgb,var(--ag-purple)_18%,transparent)] text-[var(--ag-purple)]" },
  needs_info: { text: "NEEDS INFO", cls: "bg-[color-mix(in_srgb,var(--ag-orange)_18%,transparent)] text-[var(--ag-orange)]" },
  no_candidate: { text: "NO AGENTS", cls: "bg-[var(--ag-chip)] text-[var(--ag-text-muted)]" },
  no_candidates: { text: "NO AGENTS", cls: "bg-[var(--ag-chip)] text-[var(--ag-text-muted)]" },
  failed: { text: "FAILED", cls: "bg-[color-mix(in_srgb,var(--ag-red)_18%,transparent)] text-[var(--ag-red)]" },
};

export default function ClientConsole() {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [log, setLog] = useState<LogItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [brain, setBrain] = useState<Brain | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [log, loading]);

  useEffect(() => {
    // A session becomes idle only after the concierge has answered and is
    // waiting for the user. Sending another message cancels and restarts this
    // clock after the next answer arrives.
    const lastItem = log[log.length - 1];
    if (!open || loading || lastItem?.type !== "concierge") return;

    const timeout = window.setTimeout(() => {
      setOpen(false);
      setText("");
      setLog([]);
      setBrain(null);
    }, CHAT_INACTIVITY_MS);

    return () => window.clearTimeout(timeout);
  }, [open, loading, log]);

  const send = async (value?: string) => {
    const message = (value ?? text).trim();
    if (!message || loading) return;
    // Prior turns become conversation memory the concierge reasons over.
    const history = log.map((item) =>
      item.type === "user"
        ? { role: "user", text: item.text }
        : { role: "concierge", text: item.reply.reply ?? "" },
    );
    setLog((l) => [...l, { type: "user", text: message }]);
    setText("");
    setLoading(true);
    try {
      const res = await fetch("/api/client/request", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, history }),
      });
      const reply = (await res.json()) as Reply;
      if (reply.brain) setBrain(reply.brain);
      setLog((l) => [...l, { type: "concierge", reply }]);
    } catch (err) {
      setLog((l) => [...l, { type: "concierge", reply: { status: "failed", reply: err instanceof Error ? err.message : String(err) } }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      {open && (
        <div className="fixed bottom-[92px] right-6 z-[60] box-border w-[400px] max-w-[calc(100vw-32px)] h-[560px] max-h-[calc(100vh-140px)] flex flex-col bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[14px] shadow-[0_20px_60px_rgba(0,0,0,0.45)] overflow-hidden font-[Inter,system-ui,sans-serif]">
          {/* header */}
          <div className="box-border shrink-0 p-[14px_16px] flex flex-row items-center justify-between [border-bottom:1px_solid_var(--ag-divider)] bg-[var(--ag-sidebar)]">
            <div className="flex flex-col gap-[2px]">
              <div className="text-[13px] font-semibold text-[var(--ag-text)] flex items-center gap-[7px]">
                <span className="inline-block w-[7px] h-[7px] rounded-full bg-[var(--ag-green)]" />
                Concierge
              </div>
              <div className="text-[11px] text-[var(--ag-text-muted)]">
                Ask for anything — I find the agent, negotiate, and get it done
                {brain === "rule" && <span className="text-[var(--ag-orange)]"> · rule brain (offline)</span>}
                {brain === "groq" && <span className="text-[var(--ag-green)]"> · Groq (test)</span>}
                {brain === "claude" && <span className="text-[var(--ag-green)]"> · Claude Opus</span>}
              </div>
            </div>
            <button onClick={() => setOpen(false)} className="text-[var(--ag-text-muted)] hover:text-[var(--ag-text)] text-[18px] leading-none px-[6px]" aria-label="Close">
              ×
            </button>
          </div>

          {/* conversation */}
          <div ref={scrollRef} className="box-border [flex:1_1_0] min-h-0 overflow-y-auto p-[12px] flex flex-col gap-[10px] bg-[var(--ag-bg)]">
            {log.length === 0 && (
              <div className="m-auto text-center px-3 flex flex-col gap-[12px]">
                <div className="text-[12px] text-[var(--ag-text-muted)] leading-[1.6]">
                  Describe lo que necesitas en lenguaje natural.<br />El concierge descubre agentes, negocia y ejecuta por ti.
                </div>
                <div className="flex flex-col gap-[6px]">
                  {EXAMPLES.map((ex) => (
                    <button
                      key={ex}
                      onClick={() => send(ex)}
                      className="box-border px-[10px] py-[7px] rounded-[8px] text-[11px] text-[var(--ag-text-secondary)] bg-[var(--ag-chip)] [border:1px_solid_var(--ag-card-border)] hover:text-[var(--ag-text)] hover:[border-color:#5D20DC] cursor-pointer text-left"
                    >
                      “{ex}”
                    </button>
                  ))}
                </div>
              </div>
            )}
            {log.map((item, i) => (
              <MessageBubble key={i} item={item} />
            ))}
            {loading && <div className="text-[11px] text-[var(--ag-text-muted)] italic self-start">el concierge está pensando…</div>}
          </div>

          {/* composer */}
          <div className="box-border shrink-0 p-[10px_12px] flex flex-row gap-[8px] items-center [border-top:1px_solid_var(--ag-divider)] bg-[var(--ag-sidebar)]">
            <input
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && send()}
              placeholder="¿Qué necesitas?"
              className="box-border [flex:1_1_0] min-w-0 p-[9px_11px] bg-[var(--ag2-input)] [border:1px_solid_var(--ag2-border)] rounded-[8px] text-[12px] text-[var(--ag-text)] outline-none focus:[border-color:#5D20DC] placeholder:text-[var(--ag-text-muted)]"
            />
            <button
              onClick={() => send()}
              disabled={loading || !text.trim()}
              className="box-border shrink-0 px-[14px] py-[9px] rounded-[8px] text-[12px] font-semibold text-white bg-[#5D20DC] hover:bg-[#6d2ee8] disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
            >
              Send
            </button>
          </div>
        </div>
      )}

      {/* Floating action button */}
      <button
        onClick={() => setOpen((o) => !o)}
        aria-label="Open concierge"
        className="fixed bottom-6 right-6 z-[60] box-border w-[56px] h-[56px] rounded-full bg-[#5D20DC] hover:bg-[#6d2ee8] shadow-[0_10px_30px_rgba(93,32,220,0.5)] flex items-center justify-center cursor-pointer transition-transform hover:scale-105 active:scale-95"
      >
        {open ? (
          <span className="text-white text-[22px] leading-none">×</span>
        ) : (
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
          </svg>
        )}
      </button>
    </>
  );
}

function MessageBubble({ item }: { item: LogItem }) {
  if (item.type === "user") {
    return (
      <div className="flex flex-col items-end gap-[3px] self-end max-w-[85%]">
        <div className="box-border p-[9px_12px] rounded-[12px_12px_2px_12px] bg-[#5D20DC] text-white text-[12px] leading-[1.5]">{item.text}</div>
        <span className="text-[10px] text-[var(--ag-text-muted)]">tú</span>
      </div>
    );
  }
  const r = item.reply;
  const badge = r.status ? STATUS_LABEL[r.status] : undefined;
  return (
    <div className="flex flex-col items-start gap-[3px] self-start max-w-[90%]">
      <div className="box-border p-[10px_12px] rounded-[12px_12px_12px_2px] bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] text-[12px] leading-[1.55] text-[var(--ag-text)] flex flex-col gap-[7px]">
        {badge && <span className={`box-border self-start px-[8px] py-[2px] rounded-full text-[9px] font-semibold tracking-wide ${badge.cls}`}>{badge.text}</span>}
        <div>{r.reply}</div>
        {r.workflow ? <WorkflowPreviewCard workflow={r.workflow} /> : null}
      </div>
      <span className="text-[10px] text-[var(--ag-text-muted)]">concierge</span>
    </div>
  );
}
