"use client";

import { useState } from "react";
import { readStoredCsrfToken } from "@/lib/agentSession";

export type ActionProposalView = {
  proposalId: string;
  version: number;
  capabilityId: string;
  agentName: string;
  connectedAccount: string;
  expiresAt: string;
  risk: string;
  summary: string;
  participants?: string[];
  recipients?: string[];
  timeZone?: string;
  content?: string;
  files?: string[];
  permissions?: string[];
};

export default function ActionApprovalCard({
  proposal,
  onDecision,
}: {
  proposal: ActionProposalView;
  onDecision?: (approved: boolean) => void;
}) {
  const [status, setStatus] = useState<"idle" | "saving" | "approved" | "rejected" | "failed">("idle");

  async function decide(approved: boolean) {
    const csrf = readStoredCsrfToken();
    if (!csrf) {
      setStatus("failed");
      return;
    }
    setStatus("saving");
    try {
      const response = await fetch(
        `/api/actions/${encodeURIComponent(proposal.proposalId)}/approve`,
        {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": csrf,
          },
          body: JSON.stringify({ approved, version: proposal.version }),
        },
      );
      if (!response.ok) throw new Error("decision failed");
      setStatus(approved ? "approved" : "rejected");
      onDecision?.(approved);
    } catch {
      setStatus("failed");
    }
  }

  const details = [
    ["Agent", proposal.agentName],
    ["Account", proposal.connectedAccount],
    ["Time zone", proposal.timeZone],
    ["Risk", proposal.risk],
    ["Expires", proposal.expiresAt],
  ].filter((item): item is [string, string] => Boolean(item[1]));

  return (
    <section
      aria-labelledby={`proposal-${proposal.proposalId}`}
      className="w-full max-w-full rounded-[12px] border border-amber-500/40 bg-[var(--ag-card)] p-[16px]"
    >
      <div className="min-w-0">
        <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-amber-400">
          Approval required
        </p>
        <h3 id={`proposal-${proposal.proposalId}`} className="mt-[4px] break-words text-[15px] font-semibold text-[var(--ag-text)]">
          {proposal.summary}
        </h3>
        <dl className="mt-[12px] grid grid-cols-1 gap-[8px] sm:grid-cols-2">
          {details.map(([label, value]) => (
            <div key={label} className="min-w-0">
              <dt className="text-[11px] text-[var(--ag-text-secondary)]">{label}</dt>
              <dd className="break-words text-[12px] text-[var(--ag-text)]">{value}</dd>
            </div>
          ))}
        </dl>
        {proposal.recipients?.length ? (
          <p className="mt-[10px] break-words text-[12px] text-[var(--ag-text)]">
            Recipients: {proposal.recipients.join(", ")}
          </p>
        ) : null}
        {proposal.participants?.length ? (
          <p className="mt-[10px] break-words text-[12px] text-[var(--ag-text)]">
            Participants: {proposal.participants.join(", ")}
          </p>
        ) : null}
        {proposal.content ? (
          <pre className="mt-[10px] max-h-[180px] overflow-auto whitespace-pre-wrap break-words rounded-[8px] bg-black/20 p-[10px] text-[11px] text-[var(--ag-text)]">
            {proposal.content}
          </pre>
        ) : null}
      </div>
      <div className="mt-[14px] flex flex-wrap gap-[8px]">
        <button
          type="button"
          disabled={status !== "idle" && status !== "failed"}
          onClick={() => void decide(true)}
          className="rounded-[7px] bg-[var(--ag-purple)] px-[13px] py-[8px] text-[12px] font-semibold text-white disabled:opacity-50"
        >
          Approve exact action
        </button>
        <button
          type="button"
          disabled={status !== "idle" && status !== "failed"}
          onClick={() => void decide(false)}
          className="rounded-[7px] border border-[var(--ag-card-border)] px-[13px] py-[8px] text-[12px] text-[var(--ag-text)] disabled:opacity-50"
        >
          Reject
        </button>
      </div>
      <p role={status === "failed" ? "alert" : "status"} aria-live="polite" className="mt-[10px] text-[12px] text-[var(--ag-text-secondary)]">
        {status === "saving" && "Saving your decision…"}
        {status === "approved" && "Approved for one execution."}
        {status === "rejected" && "Action rejected. Nothing was executed."}
        {status === "failed" && "Could not save the decision. Refresh your secure session and retry."}
      </p>
    </section>
  );
}
