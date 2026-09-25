"use client";

// What a person authorizes before a file becomes part of the directory (R12).
//
// A thousand-row import cannot ask for a thousand clicks, so the batch is the
// unit of decision. What the batch must not become is an anonymous one: this
// screen names the principal who is about to authorize it, and the button says
// what the act is rather than "OK".
//
// Collisions are excluded from the batch on purpose. They are the rows where
// "apply the whole file" and "decide this case" genuinely differ -- somebody
// already holds this destination, in a branch the importer did not aim at --
// so each is answered one at a time, and "link" is unavailable to a reviewer
// who lacks edit authority where that person actually lives.
//
// Every destination here is masked. The person who uploaded the file has seen
// the digits; the person reviewing it frequently has not, and "they saw it
// once" is not an authority model.

import { useState } from "react";

import type { MaskedDestination } from "./ProposalQueue";

export type ImportRowView = {
  importRowId: string;
  rowNumber: number;
  channel: string;
  classification: "new" | "duplicate" | "collision";
  state: "staged" | "applied" | "rejected";
  assertsConsent: boolean;
  consentPurposes: string[];
  destination: MaskedDestination;
  // Present only for a reviewer who holds view over the target branch.
  displayName?: string;
  writtenAddress?: string;
  redacted?: boolean;
  // Whether this reviewer may claim the collision is the same person. False
  // when they hold no edit authority on the branch that person sits in.
  mayLink?: boolean;
};

export type ImportBatchView = {
  batchId: string;
  state: "staged" | "applied" | "rejected";
  branchPath?: string | null;
  sourceName?: string | null;
  rowCount: number;
  newCount: number;
  duplicateCount: number;
  collisionCount: number;
  redacted: boolean;
  rows: ImportRowView[];
};

export type ImportReviewProps = {
  batch: ImportBatchView | null;
  // Named on the button, because a bulk mistake is only recoverable if
  // somebody can be asked what they thought they were approving.
  actingPrincipalId: string;
  canApply: boolean;
  onApplyBatch: (batchId: string, reason: string) => void | Promise<void>;
  onDecideRow: (
    importRowId: string,
    decision: "link" | "reject",
    reason: string,
  ) => void | Promise<void>;
  busy?: boolean;
  emptyMessage?: string;
};

const CLASSIFICATION_LABELS: Record<string, string> = {
  new: "nueva",
  duplicate: "duplicada",
  collision: "colisión",
};

export default function ImportReview({
  batch,
  actingPrincipalId,
  canApply,
  onApplyBatch,
  onDecideRow,
  busy = false,
  emptyMessage = "No hay ninguna importación esperando revisión.",
}: ImportReviewProps) {
  const [reason, setReason] = useState("");
  if (batch === null) {
    return (
      <p role="status" className="text-[11px] text-[var(--ag-text-muted)]">
        {emptyMessage}
      </p>
    );
  }
  const staged = batch.state === "staged";
  const collisions = batch.rows.filter((row) => row.classification === "collision");
  const evidenced = batch.rows.filter((row) => row.assertsConsent).length;
  return (
    <section
      aria-label="Revisión de importación"
      className="box-border flex flex-col gap-[12px] rounded-[10px] border border-[var(--ag-card-border)] bg-[var(--ag-card)] p-[14px]"
    >
      <header className="flex flex-col gap-[2px]">
        <h2 className="text-[14px] font-semibold text-[var(--ag-text)]">
          {batch.sourceName ?? "Importación"}
        </h2>
        <p className="text-[10px] text-[var(--ag-text-muted)]">
          {batch.branchPath ?? "sin rama"} · {batch.rowCount} filas · estado {batch.state}
        </p>
      </header>

      <dl
        aria-label="Resumen de la importación"
        className="grid grid-cols-[auto_1fr] gap-x-[10px] gap-y-[2px] text-[10px] text-[var(--ag-text-secondary)]"
      >
        <dt className="text-[var(--ag-text-muted)]">Nuevas</dt>
        <dd data-testid="count-new">{batch.newCount}</dd>
        <dt className="text-[var(--ag-text-muted)]">Duplicadas</dt>
        <dd data-testid="count-duplicate">{batch.duplicateCount}</dd>
        <dt className="text-[var(--ag-text-muted)]">Colisiones</dt>
        <dd data-testid="count-collision">{batch.collisionCount}</dd>
      </dl>

      <p role="status" className="text-[10px] text-[var(--ag-orange)]">
        {evidenced === 0
          ? "Ninguna fila trae evidencia de consentimiento: todas las direcciones quedarán inutilizables."
          : `${evidenced} de ${batch.rowCount} filas traen evidencia; el resto quedará inutilizable.`}
      </p>
      {batch.collisionCount > 0 ? (
        <p role="status" className="text-[10px] text-[var(--ag-orange)]">
          Las colisiones no entran en la decisión por lote: se resuelven una a una.
        </p>
      ) : null}
      {batch.redacted ? (
        <p role="status" className="text-[10px] text-[var(--ag-text-muted)]">
          Estás viendo una importación redactada: sin nombres y con los destinos enmascarados.
        </p>
      ) : null}

      <ul className="flex flex-col gap-[6px]">
        {batch.rows.map((row) => (
          <li
            key={row.importRowId}
            aria-label={`Fila ${row.rowNumber}`}
            className="flex flex-col gap-[4px] rounded-[8px] border border-[var(--ag-divider)] p-[8px]"
          >
            <div className="flex flex-row items-baseline gap-[8px]">
              <span className="text-[11px] font-semibold text-[var(--ag-text)]">
                {row.displayName ?? "Identidad reservada"}
              </span>
              <span className="text-[10px] uppercase tracking-wide text-[var(--ag-text-muted)]">
                {CLASSIFICATION_LABELS[row.classification]} · {row.state}
              </span>
            </div>
            <span className="text-[10px] text-[var(--ag-text-secondary)]" data-testid="masked-destination">
              {row.destination.text}
            </span>
            <span className="text-[10px] text-[var(--ag-text-muted)]">
              {row.assertsConsent
                ? `Consentimiento con evidencia: ${row.consentPurposes.join(", ")}`
                : "Sin evidencia: quedará inutilizable"}
            </span>
            {row.classification === "collision" && row.state === "staged" ? (
              <div className="flex flex-row gap-[8px]">
                <button
                  type="button"
                  disabled={busy || row.mayLink === false}
                  onClick={() => void onDecideRow(row.importRowId, "link", reason.trim() || "misma persona")}
                  className="rounded-[8px] border border-[var(--ag-card-border)] px-[10px] py-[4px] text-[10px] text-[var(--ag-text-secondary)] hover:text-[var(--ag-text)] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Es la misma persona
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    void onDecideRow(row.importRowId, "reject", reason.trim() || "rechazada en revisión")
                  }
                  className="rounded-[8px] border border-[var(--ag-card-border)] px-[10px] py-[4px] text-[10px] text-[var(--ag-text-secondary)] hover:text-[var(--ag-text)] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Descartar la fila
                </button>
                {row.mayLink === false ? (
                  <span role="status" className="text-[10px] text-[var(--ag-orange)]">
                    No puedes vincularla: esa persona vive en una rama que no editas.
                  </span>
                ) : null}
              </div>
            ) : null}
          </li>
        ))}
      </ul>

      <label className="flex flex-col gap-[2px] text-[10px] text-[var(--ag-text-muted)]">
        Motivo
        <input
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          className="rounded border border-[var(--ag2-border)] bg-[var(--ag2-input)] px-[6px] py-[4px] text-[11px] text-[var(--ag-text)]"
        />
      </label>

      <button
        type="button"
        disabled={busy || !canApply || !staged}
        onClick={() => void onApplyBatch(batch.batchId, reason.trim() || "importación revisada")}
        className="w-fit rounded-[8px] bg-[#5D20DC] px-[12px] py-[6px] text-[11px] font-semibold text-white hover:bg-[#6d2ee8] disabled:cursor-not-allowed disabled:opacity-40"
      >
        {`Autorizar ${batch.newCount + batch.duplicateCount} filas como ${actingPrincipalId}`}
      </button>
      {canApply ? null : (
        <p role="status" className="text-[10px] text-[var(--ag-orange)]">
          No tienes autoridad de edición sobre esta rama, así que no puedes autorizar esta importación.
        </p>
      )}
      {collisions.length > 0 && staged ? (
        <p className="text-[10px] text-[var(--ag-text-muted)]">
          Quedarán {collisions.length} colisiones por decidir después de autorizar el lote.
        </p>
      ) : null}
    </section>
  );
}
