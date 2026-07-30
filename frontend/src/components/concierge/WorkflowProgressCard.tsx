export type WorkflowProgressStep = { id: string; label: string; executionStatus: string; verificationStatus: string; output?: Record<string, unknown> };

const labels: Record<string, string> = { queued: "En espera", running: "Ejecutando", completed: "Completado", retry_wait: "Reintentará", execution_unknown: "Resultado por confirmar", paused_by_policy: "Pausado por seguridad", cancelled: "Cancelado" };
const verificationLabels: Record<string, string> = { pending: " · verificando", verified: " · verificado", inconclusive: " · sin confirmar", failed: " · no verificado" };

export default function WorkflowProgressCard({ outcome, steps }: { outcome: string; steps: WorkflowProgressStep[] }) {
  return <section aria-label="Workflow progress" className="rounded-xl border border-[var(--ag-card-border)] bg-[var(--ag-card)] p-4">
    <h3 className="text-sm font-semibold text-[var(--ag-text)]">{outcome}</h3>
    <ul className="mt-3 space-y-2">{steps.map(step => {
      const channels = publicChannelNames(step.output);
      return <li key={step.id} className="text-xs">
        <div className="flex items-start justify-between gap-3"><span className="text-[var(--ag-text)]">{step.label}</span><span className={step.executionStatus === "execution_unknown" || step.verificationStatus === "failed" || step.verificationStatus === "inconclusive" ? "text-amber-300" : "text-[var(--ag-text-secondary)]"}>{labels[step.executionStatus] ?? step.executionStatus}{step.executionStatus === "completed" ? verificationLabels[step.verificationStatus] ?? "" : ""}</span></div>
        {channels.length ? <ul className="mt-2 flex flex-wrap gap-2">{channels.map(channel => <li key={channel} className="rounded-md bg-[var(--ag-muted)] px-2 py-1 text-[var(--ag-text)]">#{channel}</li>)}</ul> : null}
      </li>;
    })}</ul>
  </section>;
}

function publicChannelNames(output?: Record<string, unknown>): string[] {
  if (!Array.isArray(output?.channels)) return [];
  return output.channels.flatMap(channel => {
    if (!channel || typeof channel !== "object") return [];
    const record = channel as Record<string, unknown>;
    return typeof record.name === "string" && record.is_private !== true ? [record.name] : [];
  });
}
