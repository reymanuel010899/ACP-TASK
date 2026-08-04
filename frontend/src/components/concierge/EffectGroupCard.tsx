"use client";

import { useEffect, useRef, useState } from "react";

export type EffectRow = {
  effectId: string;
  capabilityId: string;
  summary: string;
  status: string;
  reinforced: boolean;
  allowedActions: string[];
  detailsExpanded: boolean;
  recovery?: string;
};

export type EffectGroup = {
  groupId: string;
  effects: EffectRow[];
  summary: string;
};

const STATUS_LABELS: Record<string, string> = {
  awaiting_approval: "Waiting for you",
  approved: "Approved",
  rejected: "Rejected",
  blocked: "Waiting on an earlier step",
  succeeded: "Done",
  failed: "Failed",
  cancelled: "Cancelled",
};

function statusLabel(status: string) {
  return STATUS_LABELS[status] ?? status.replace(/_/g, " ");
}

export default function EffectGroupCard({
  group,
  onDecide,
  busy = false,
}: {
  group: EffectGroup;
  onDecide: (effectId: string, action: string) => void | Promise<void>;
  busy?: boolean;
}) {
  // Reinforced effects arrive expanded from the server: high risk should not
  // be one click away from invisible. A person may still collapse one.
  const [expanded, setExpanded] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(group.effects.map((effect) => [effect.effectId, effect.detailsExpanded])),
  );
  // Announce only when the text actually changes, or a poll that changed
  // nothing would still interrupt a screen reader every few seconds.
  const [announcement, setAnnouncement] = useState(group.summary);
  const lastAnnounced = useRef(group.summary);
  // Focus belongs where the person left it, not at the top of a card the
  // server happened to re-render underneath them.
  const lastInteracted = useRef<string | null>(null);

  useEffect(() => {
    if (group.summary !== lastAnnounced.current) {
      lastAnnounced.current = group.summary;
      setAnnouncement(group.summary);
    }
  }, [group.summary]);

  useEffect(() => {
    if (!lastInteracted.current) return;
    const target = document.getElementById(lastInteracted.current);
    if (target instanceof HTMLElement && document.activeElement !== target) {
      target.focus();
    }
  });

  function decide(effect: EffectRow, action: string, controlId: string) {
    lastInteracted.current = controlId;
    void onDecide(effect.effectId, action);
  }

  return (
    <section
      role="group"
      aria-label="Requested effects"
      className="rounded-[7px] border border-[var(--ag-card-border)] p-[8px]"
    >
      <p aria-live="polite" className="text-[10px] font-semibold text-[var(--ag-text)]">
        {announcement}
      </p>

      <ul className="mt-[6px] space-y-[6px]">
        {group.effects.map((effect) => {
          const detailsId = `${effect.effectId}-details`;
          const isOpen = expanded[effect.effectId] ?? effect.detailsExpanded;
          return (
            <li
              key={effect.effectId}
              className={`rounded-[6px] border p-[6px] ${
                effect.reinforced
                  ? "border-[#7F1D1D] bg-[#1B0D0D]"
                  : "border-[var(--ag-card-border)]"
              }`}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-[10px] text-[var(--ag-text)]">{effect.summary}</p>
                  <p className="text-[9px] text-[var(--ag-text-secondary)]">
                    {statusLabel(effect.status)}
                    {effect.reinforced ? " · needs you present" : ""}
                  </p>
                </div>
                <div className="flex shrink-0 gap-1">
                  {effect.allowedActions.includes("approve") && (
                    <button
                      type="button"
                      id={`${effect.effectId}-approve`}
                      disabled={busy}
                      onClick={() => decide(effect, "approve", `${effect.effectId}-approve`)}
                      className="rounded border border-[var(--ag-card-border)] px-2 py-1 text-[9px] text-[var(--ag-text)] disabled:opacity-50"
                    >
                      Approve
                    </button>
                  )}
                  {effect.allowedActions.includes("reject") && (
                    <button
                      type="button"
                      id={`${effect.effectId}-reject`}
                      disabled={busy}
                      onClick={() => decide(effect, "reject", `${effect.effectId}-reject`)}
                      className="rounded border border-[#7F1D1D] px-2 py-1 text-[9px] text-[#FCA5A5] disabled:opacity-50"
                    >
                      Reject
                    </button>
                  )}
                </div>
              </div>

              <button
                type="button"
                aria-expanded={isOpen}
                aria-controls={detailsId}
                onClick={() =>
                  setExpanded((current) => ({
                    ...current,
                    [effect.effectId]: !isOpen,
                  }))
                }
                className="mt-1 text-[9px] text-[var(--ag-text-secondary)] underline"
              >
                {isOpen ? "Hide details" : "Show details"}
              </button>
              {isOpen && (
                <dl id={detailsId} className="mt-1 text-[9px] text-[var(--ag-text-secondary)]">
                  <div className="flex gap-1">
                    <dt>Capability</dt>
                    <dd className="font-mono">{effect.capabilityId}</dd>
                  </div>
                  {effect.recovery && (
                    <div className="flex gap-1">
                      <dt>Recovery</dt>
                      <dd>{effect.recovery}</dd>
                    </div>
                  )}
                </dl>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
