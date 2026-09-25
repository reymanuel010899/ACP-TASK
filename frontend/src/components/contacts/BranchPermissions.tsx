"use client";

// Who may do what on one branch, and what this administrator may hand out.
//
// R11's four dimensions are independently grantable, which is only meaningful
// if the editor keeps them independent -- so there is no "role" control here,
// and no dimension implies another. Viewing, editing, administering and using
// contacts in campaigns each get their own row and their own decision.
//
// The rule this component exists to make unavoidable: **you cannot grant an
// authority you do not hold here.** The server sends `grantable`, the set of
// dimensions the acting principal effectively holds on this branch, and the
// grant control for anything outside it is disabled with the reason said out
// loud. Handing out view over a branch whose names you cannot read is
// privilege creation, not delegation.
//
// Restricting is not gated the same way, and that asymmetry is deliberate: a
// restrictive move closes a subtree and needs less authority than the
// permissive one that opened it (KTD13).

export type PermissionDecisionView = {
  dimension: string;
  effect: "grant" | "restrict";
  principalId: string;
  decidedByPrincipalId?: string | null;
  reason?: string | null;
};

export type BranchPermissionsProps = {
  branchPath: string;
  // The principal whose authority is being edited.
  subjectPrincipalId: string;
  // What the subject effectively holds here, inheritance already resolved.
  subjectEffective: Record<string, boolean>;
  // Decisions written *at* this branch, as opposed to inherited from above.
  decisions: PermissionDecisionView[];
  // What the acting principal may delegate here. Computed on the server.
  grantable: string[];
  onDecide: (dimension: string, effect: "grant" | "restrict") => void | Promise<void>;
  onRevoke: (dimension: string) => void | Promise<void>;
  busy?: boolean;
};

export const DIMENSIONS = ["view", "edit", "administer", "campaign_use"] as const;

const DIMENSION_LABELS: Record<string, string> = {
  view: "Ver",
  edit: "Editar",
  administer: "Administrar",
  campaign_use: "Usar en campañas",
};

export function explicitEffect(
  decisions: PermissionDecisionView[],
  principalId: string,
  dimension: string,
) {
  const found = decisions.find(
    (decision) => decision.principalId === principalId && decision.dimension === dimension,
  );
  return found ? found.effect : null;
}

export default function BranchPermissions({
  branchPath,
  subjectPrincipalId,
  subjectEffective,
  decisions,
  grantable,
  onDecide,
  onRevoke,
  busy = false,
}: BranchPermissionsProps) {
  return (
    <section
      aria-label="Permisos de la rama"
      className="box-border flex flex-col gap-[10px] rounded-[10px] border border-[var(--ag-card-border)] bg-[var(--ag-card)] p-[14px]"
    >
      <header className="flex flex-col gap-[2px]">
        <h2 className="text-[14px] font-semibold text-[var(--ag-text)]">{branchPath}</h2>
        <p className="text-[10px] text-[var(--ag-text-muted)]">
          Autoridad de {subjectPrincipalId}. Cada dimensión se concede por separado y baja a las ramas hijas.
        </p>
      </header>

      <ul className="flex flex-col gap-[8px]">
        {DIMENSIONS.map((dimension) => {
          const explicit = explicitEffect(decisions, subjectPrincipalId, dimension);
          const held = Boolean(subjectEffective[dimension]);
          const mayGrant = grantable.includes(dimension);
          return (
            <li
              key={dimension}
              aria-label={DIMENSION_LABELS[dimension]}
              className="flex flex-col gap-[4px] rounded-[8px] border border-[var(--ag-divider)] p-[8px]"
            >
              <div className="flex flex-row items-baseline gap-[8px]">
                <span className="text-[11px] font-semibold text-[var(--ag-text)]">
                  {DIMENSION_LABELS[dimension]}
                </span>
                <span className="text-[10px] text-[var(--ag-text-secondary)]" data-testid={`state-${dimension}`}>
                  {held ? "concedida" : "denegada"}
                  {explicit === null ? " · heredada" : ` · decidida aquí (${explicit})`}
                </span>
              </div>
              <div className="flex flex-row flex-wrap items-center gap-[8px]">
                <button
                  type="button"
                  disabled={busy || !mayGrant}
                  onClick={() => void onDecide(dimension, "grant")}
                  className="rounded-[8px] border border-[var(--ag-card-border)] px-[10px] py-[4px] text-[10px] text-[var(--ag-text-secondary)] hover:text-[var(--ag-text)] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {`Conceder ${DIMENSION_LABELS[dimension]}`}
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void onDecide(dimension, "restrict")}
                  className="rounded-[8px] border border-[var(--ag-card-border)] px-[10px] py-[4px] text-[10px] text-[var(--ag-text-secondary)] hover:text-[var(--ag-text)] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {`Restringir ${DIMENSION_LABELS[dimension]}`}
                </button>
                <button
                  type="button"
                  disabled={busy || explicit === null}
                  onClick={() => void onRevoke(dimension)}
                  className="rounded-[8px] border border-[var(--ag-card-border)] px-[10px] py-[4px] text-[10px] text-[var(--ag-text-secondary)] hover:text-[var(--ag-text)] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {`Volver a heredar ${DIMENSION_LABELS[dimension]}`}
                </button>
                {mayGrant ? null : (
                  <span role="status" className="text-[10px] text-[var(--ag-orange)]">
                    No puedes conceder una autoridad que tú no tienes en esta rama.
                  </span>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
