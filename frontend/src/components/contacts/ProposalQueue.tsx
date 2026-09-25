"use client";

// The review queue an agent proposal waits in (R12).
//
// It ships in the same unit as the propose capability, because without it
// `contacts.propose` writes records nobody can approve and the agent
// re-proposes the same person every turn.
//
// Two rules this component exists to make unavoidable:
//
// * **A destination is shown masked and never in full.** The server sends a
//   country code, trailing digits, a branch path and a fingerprint. There is
//   no prop here that could carry the digits, so no future edit can leak them
//   by wiring one field to another.
// * **Approving is a decision, not an acknowledgement.** A proposal that
//   claims consent cannot be approved until the evidence U6 requires is
//   present, because a grant recorded without it looks like permission and is
//   not. The button stays disabled and says why.

import { useState } from "react";

export type MaskedDestination = {
  channel: string;
  text: string;
  countryCode?: string | null;
  digitCount?: number | null;
  visibleTail?: string | null;
  fingerprint: string;
  branchPath?: string | null;
  lastContactedAt?: string | null;
};

export type ContactProposal = {
  proposalId: string;
  contactId: string;
  displayName: string;
  branchPath?: string | null;
  channel: string;
  destination: MaskedDestination;
  proposedByActorKind?: string | null;
  proposedByPrincipalId?: string | null;
  proposedAt?: string | null;
  // Purposes the agent claimed consent for. Claimed is not granted: each one
  // must be decided here, with evidence, or the proposal is not finished.
  pendingConsent: string[];
};

export type ConsentEvidenceDraft = {
  captureMethod: string;
  capturedAtLocal: string;
  captureTimezone: string;
  jurisdiction: string;
  disclosureText: string;
  legalBasis: string;
  defaultUnchecked: boolean;
};

export type ProposalDecision = {
  evidence?: ConsentEvidenceDraft;
  purposes: string[];
  reason?: string;
};

export type ProposalQueueProps = {
  proposals: ContactProposal[];
  onApprove: (proposalId: string, decision: ProposalDecision) => void | Promise<void>;
  onReject: (proposalId: string, reason: string) => void | Promise<void>;
  busyProposalId?: string | null;
  emptyMessage?: string;
};

// The capture methods that put a checkbox in front of somebody. For these the
// default-unchecked proof is mandatory rather than merely expected, which is
// the same rule `libs/contacts_consent.py` enforces on the way in.
const FORM_CAPTURE_METHODS = ["web_form", "embedded_form", "import_form"];

const CAPTURE_METHODS = [
  "web_form",
  "embedded_form",
  "import_form",
  "verbal_recorded",
  "inbound_keyword",
  "contract",
];

function emptyEvidence(): ConsentEvidenceDraft {
  return {
    captureMethod: "",
    capturedAtLocal: "",
    captureTimezone: "",
    jurisdiction: "",
    disclosureText: "",
    legalBasis: "",
    defaultUnchecked: false,
  };
}

// Which required fields are still absent, in a stable order. Mirrors U6's
// `ConsentEvidence.missing_fields` so a person is told here rather than
// discovering it from a rejected write.
export function missingEvidenceFields(evidence: ConsentEvidenceDraft): string[] {
  const missing = (
    [
      ["captureMethod", evidence.captureMethod],
      ["capturedAtLocal", evidence.capturedAtLocal],
      ["jurisdiction", evidence.jurisdiction],
      ["disclosureText", evidence.disclosureText],
      ["legalBasis", evidence.legalBasis],
    ] as Array<[string, string]>
  )
    .filter(([, value]) => !value.trim())
    .map(([name]) => name);
  if (FORM_CAPTURE_METHODS.includes(evidence.captureMethod) && !evidence.defaultUnchecked) {
    missing.push("defaultUnchecked");
  }
  return missing;
}

export function maskedLabel(destination: MaskedDestination) {
  const country = destination.countryCode ? `+${destination.countryCode}` : "";
  return [country, destination.text].filter(Boolean).join(" ");
}

export default function ProposalQueue({
  proposals,
  onApprove,
  onReject,
  busyProposalId = null,
  emptyMessage = "No hay propuestas esperando revisión.",
}: ProposalQueueProps) {
  if (proposals.length === 0) {
    return (
      <p role="status" className="text-[11px] text-[var(--ag-text-muted)]">
        {emptyMessage}
      </p>
    );
  }
  return (
    <section aria-label="Propuestas pendientes" className="flex flex-col gap-[10px]">
      <p role="status" className="text-[11px] text-[var(--ag-text-muted)]">
        {proposals.length === 1
          ? "1 propuesta esperando tu decisión"
          : `${proposals.length} propuestas esperando tu decisión`}
      </p>
      <ul className="flex flex-col gap-[10px]">
        {proposals.map((proposal) => (
          <ProposalCard
            key={proposal.proposalId}
            proposal={proposal}
            onApprove={onApprove}
            onReject={onReject}
            busy={busyProposalId === proposal.proposalId}
          />
        ))}
      </ul>
    </section>
  );
}

function ProposalCard({
  proposal,
  onApprove,
  onReject,
  busy,
}: {
  proposal: ContactProposal;
  onApprove: ProposalQueueProps["onApprove"];
  onReject: ProposalQueueProps["onReject"];
  busy: boolean;
}) {
  const [evidence, setEvidence] = useState<ConsentEvidenceDraft>(emptyEvidence);
  const [reason, setReason] = useState("");
  const claimsConsent = proposal.pendingConsent.length > 0;
  const missing = claimsConsent ? missingEvidenceFields(evidence) : [];
  const blocked = claimsConsent && missing.length > 0;

  const set = <K extends keyof ConsentEvidenceDraft>(key: K, value: ConsentEvidenceDraft[K]) =>
    setEvidence((current) => ({ ...current, [key]: value }));

  return (
    <li className="box-border flex flex-col gap-[8px] rounded-[10px] border border-[var(--ag-card-border)] bg-[var(--ag-card)] p-[12px]">
      <div className="flex flex-col gap-[2px]">
        <span className="text-[12px] font-semibold text-[var(--ag-text)]">{proposal.displayName}</span>
        <span className="text-[10px] text-[var(--ag-text-muted)]">
          {proposal.branchPath ?? "sin rama"} · {proposal.channel}
        </span>
      </div>

      <dl className="grid grid-cols-[auto_1fr] gap-x-[10px] gap-y-[2px] text-[10px] text-[var(--ag-text-secondary)]">
        <dt className="text-[var(--ag-text-muted)]">Destino</dt>
        <dd data-testid="masked-destination">{maskedLabel(proposal.destination)}</dd>
        <dt className="text-[var(--ag-text-muted)]">Huella</dt>
        <dd className="font-mono">{proposal.destination.fingerprint}</dd>
        <dt className="text-[var(--ag-text-muted)]">Propuesto por</dt>
        <dd>
          {proposal.proposedByActorKind ?? "desconocido"}
          {proposal.proposedByPrincipalId ? ` · ${proposal.proposedByPrincipalId}` : ""}
        </dd>
      </dl>

      {claimsConsent ? (
        <fieldset className="flex flex-col gap-[6px] rounded-[8px] border border-[var(--ag-divider)] p-[8px]">
          <legend className="px-[4px] text-[10px] text-[var(--ag-orange)]">
            Consentimiento reclamado: {proposal.pendingConsent.join(", ")}
          </legend>
          <label className="flex flex-col gap-[2px] text-[10px] text-[var(--ag-text-muted)]">
            Método de captura
            <select
              value={evidence.captureMethod}
              onChange={(event) => set("captureMethod", event.target.value)}
              className="rounded border border-[var(--ag2-border)] bg-[var(--ag2-input)] px-[6px] py-[4px] text-[11px] text-[var(--ag-text)]"
            >
              <option value="">—</option>
              {CAPTURE_METHODS.map((method) => (
                <option key={method} value={method}>
                  {method}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-[2px] text-[10px] text-[var(--ag-text-muted)]">
            Fecha y hora locales
            <input
              value={evidence.capturedAtLocal}
              onChange={(event) => set("capturedAtLocal", event.target.value)}
              className="rounded border border-[var(--ag2-border)] bg-[var(--ag2-input)] px-[6px] py-[4px] text-[11px] text-[var(--ag-text)]"
            />
          </label>
          <label className="flex flex-col gap-[2px] text-[10px] text-[var(--ag-text-muted)]">
            Zona horaria
            <input
              value={evidence.captureTimezone}
              onChange={(event) => set("captureTimezone", event.target.value)}
              className="rounded border border-[var(--ag2-border)] bg-[var(--ag2-input)] px-[6px] py-[4px] text-[11px] text-[var(--ag-text)]"
            />
          </label>
          <label className="flex flex-col gap-[2px] text-[10px] text-[var(--ag-text-muted)]">
            Jurisdicción
            <input
              value={evidence.jurisdiction}
              onChange={(event) => set("jurisdiction", event.target.value)}
              className="rounded border border-[var(--ag2-border)] bg-[var(--ag2-input)] px-[6px] py-[4px] text-[11px] text-[var(--ag-text)]"
            />
          </label>
          <label className="flex flex-col gap-[2px] text-[10px] text-[var(--ag-text-muted)]">
            Texto mostrado
            <textarea
              value={evidence.disclosureText}
              onChange={(event) => set("disclosureText", event.target.value)}
              className="rounded border border-[var(--ag2-border)] bg-[var(--ag2-input)] px-[6px] py-[4px] text-[11px] text-[var(--ag-text)]"
            />
          </label>
          <label className="flex flex-col gap-[2px] text-[10px] text-[var(--ag-text-muted)]">
            Base legal
            <input
              value={evidence.legalBasis}
              onChange={(event) => set("legalBasis", event.target.value)}
              className="rounded border border-[var(--ag2-border)] bg-[var(--ag2-input)] px-[6px] py-[4px] text-[11px] text-[var(--ag-text)]"
            />
          </label>
          <label className="flex items-center gap-[6px] text-[10px] text-[var(--ag-text-muted)]">
            <input
              type="checkbox"
              checked={evidence.defaultUnchecked}
              onChange={(event) => set("defaultUnchecked", event.target.checked)}
            />
            La casilla empezó vacía
          </label>
          {blocked ? (
            <p role="status" className="text-[10px] text-[var(--ag-orange)]">
              Falta evidencia: {missing.join(", ")}
            </p>
          ) : null}
        </fieldset>
      ) : null}

      <label className="flex flex-col gap-[2px] text-[10px] text-[var(--ag-text-muted)]">
        Motivo
        <input
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          className="rounded border border-[var(--ag2-border)] bg-[var(--ag2-input)] px-[6px] py-[4px] text-[11px] text-[var(--ag-text)]"
        />
      </label>

      <div className="flex flex-row gap-[8px]">
        <button
          type="button"
          disabled={busy || blocked}
          onClick={() =>
            void onApprove(proposal.proposalId, {
              evidence: claimsConsent ? evidence : undefined,
              purposes: proposal.pendingConsent,
              reason: reason.trim() || undefined,
            })
          }
          className="rounded-[8px] bg-[#5D20DC] px-[12px] py-[6px] text-[11px] font-semibold text-white hover:bg-[#6d2ee8] disabled:cursor-not-allowed disabled:opacity-40"
        >
          Aprobar y activar
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => void onReject(proposal.proposalId, reason.trim() || "rechazado en revisión")}
          className="rounded-[8px] border border-[var(--ag-card-border)] px-[12px] py-[6px] text-[11px] text-[var(--ag-text-secondary)] hover:text-[var(--ag-text)] disabled:cursor-not-allowed disabled:opacity-40"
        >
          Rechazar
        </button>
      </div>
    </li>
  );
}
