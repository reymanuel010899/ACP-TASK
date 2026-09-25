"use client";

import { useEffect, useState } from "react";
import { readStoredCsrfToken } from "@/lib/agentSession";
import WorkflowProgressCard, { type WorkflowProgressStep } from "./WorkflowProgressCard";

export type WorkflowStepView = { id: string; label: string; provider: string; account: string; effect: "read" | "write"; disclosure?: string; effectFields?: Record<string, unknown> };
export type WorkflowPreview = { workflowId: string; revisionId: string; revision: number; outcome: string; steps: WorkflowStepView[]; blockers?: string[] };

// The concierge sends TWO different things under `workflow`: the reviewable
// plan above (`workflow["preview"]` in `web/concierge.py`), and a bare handle
// to an already-dispatched run — `{workflowId, revisionId}` only — emitted by
// `dynamic_workflow_service._start_slack_entity_resolution` and by
// `_conversation_response` while a conversation is still `retrieving`. A
// handle has no steps, revision, or outcome, so it is not renderable as a
// preview; callers must narrow with `isWorkflowPreview` before passing it in.
export type WorkflowHandle = { workflowId: string; revisionId?: string };

export function isWorkflowPreview(workflow: WorkflowPreview | WorkflowHandle): workflow is WorkflowPreview {
  return Array.isArray((workflow as WorkflowPreview).steps);
}
type RecoveryOptions = { cancelAllowed: boolean; retryableStepIds: string[]; unknownStepIds: string[] };
export type SlackDraft = { conversationId: string; draftHash: string; destination: string; text: string };

export default function WorkflowPreviewCard({ workflow, onDecision, slackDraft, superseded = false, onEdit }: { workflow: WorkflowPreview; onDecision?: (approved: boolean) => void; slackDraft?: SlackDraft; superseded?: boolean; onEdit?: (text: string) => void }) {
  const [state, setState] = useState<"idle" | "saving" | "approved" | "rejected" | "cancelled" | "failed">("idle");
  const [progress, setProgress] = useState<WorkflowProgressStep[]>([]);
  const [recovery, setRecovery] = useState<RecoveryOptions>({ cancelAllowed: false, retryableStepIds: [], unknownStepIds: [] });
  useEffect(() => {
    if (state !== "approved") return;
    let active = true;
    async function refresh() {
      try {
        const response = await fetch(`/api/workflows/${encodeURIComponent(workflow.workflowId)}`, { credentials: "same-origin", cache: "no-store" });
        if (!response.ok) return;
        const body = await response.json() as { revision?: { steps?: Array<Record<string, unknown>> }; recovery?: RecoveryOptions };
        const steps = body.revision?.steps;
        if (!active || !Array.isArray(steps)) return;
        setProgress(steps.map(step => ({
          id: String(step.step_id),
          label: String(step.capability_id),
          executionStatus: String(step.execution_status),
          verificationStatus: String(step.verification_status),
          output: step.output && typeof step.output === "object" ? step.output as Record<string, unknown> : undefined,
        })));
        if (body.recovery) setRecovery(body.recovery);
      } catch { /* Keep the last durable state visible; the next poll retries. */ }
    }
    void refresh();
    const timer = window.setInterval(() => void refresh(), 2000);
    return () => { active = false; window.clearInterval(timer); };
  }, [state, workflow.workflowId]);
  async function recover(operation: "cancel" | "retry", stepId?: string) {
    const csrf = readStoredCsrfToken();
    if (!csrf) return setState("failed");
    try {
      const response = await fetch(`/api/workflows/${encodeURIComponent(workflow.workflowId)}/${operation}`, {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
        body: JSON.stringify({ revisionId: workflow.revisionId, revision: workflow.revision, stepId }),
      });
      if (!response.ok) throw new Error("recovery failed");
      if (operation === "cancel") setState("cancelled");
      else setRecovery(current => ({ ...current, retryableStepIds: current.retryableStepIds.filter(id => id !== stepId) }));
    } catch { setState("failed"); }
  }
  async function decide(approved: boolean) {
    const csrf = readStoredCsrfToken();
    if (!csrf) return setState("failed");
    setState("saving");
    try {
      const response = await fetch(`/api/workflows/${encodeURIComponent(workflow.workflowId)}/approve`, {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
        body: JSON.stringify({ approved, revisionId: workflow.revisionId, revision: workflow.revision,
          conversationId: slackDraft?.conversationId, draftHash: slackDraft?.draftHash }),
      });
      if (!response.ok) throw new Error("decision failed");
      setState(approved ? "approved" : "rejected"); onDecision?.(approved);
    } catch { setState("failed"); }
  }
  return <section aria-label="Workflow preview" className="rounded-xl border border-violet-500/30 bg-[var(--ag-card)] p-4">
    <p className="text-xs font-semibold uppercase tracking-wide text-violet-400">{slackDraft ? "Mensaje listo para confirmar" : "Plan listo para revisar"} · revisión {workflow.revision}</p>
    <h3 className="mt-1 text-sm font-semibold text-[var(--ag-text)]">{workflow.outcome}</h3>
    {slackDraft ? <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 rounded-lg border border-[var(--ag-card-border)] p-3 text-xs">
      <dt className="text-[var(--ag-text-secondary)]">Destino</dt><dd className="font-semibold text-[var(--ag-text)]">{slackDraft.destination}</dd>
      <dt className="text-[var(--ag-text-secondary)]">Mensaje exacto</dt><dd className="whitespace-pre-wrap break-words text-[var(--ag-text)]">{slackDraft.text}</dd>
    </dl> : null}
    <ol className="mt-3 space-y-2">{workflow.steps.map((step, index) => <li key={step.id} className="rounded-lg border border-[var(--ag-card-border)] p-3 text-xs text-[var(--ag-text)]">
      <span className="font-semibold">{index + 1}. {step.label}</span><span className="ml-2 text-[var(--ag-text-secondary)]">{step.provider} · {step.account}</span>
      {step.effect === "write" && step.effectFields && Object.keys(step.effectFields).length ? <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-2 gap-y-1 text-[11px]">
        {Object.entries(step.effectFields).map(([field, value]) => <div className="contents" key={field}><dt className="font-medium text-[var(--ag-text-secondary)]">{effectFieldLabel(field)}</dt><dd className="break-words">{formatEffectValue(value)}</dd></div>)}
      </dl> : null}
      {step.disclosure ? <p className="mt-1 text-amber-300">Comparte: {step.disclosure}</p> : null}
    </li>)}</ol>
    {workflow.blockers?.length ? <p className="mt-3 text-xs text-amber-300">Antes de continuar: {workflow.blockers.join(" · ")}</p> : null}
    {state === "approved" && progress.length ? <div className="mt-4"><WorkflowProgressCard outcome="Ejecución del plan" steps={progress} /></div> : null}
    {state === "approved" && recovery.retryableStepIds.length ? <div className="mt-3 flex flex-wrap gap-2">{recovery.retryableStepIds.map(stepId => <button key={stepId} type="button" onClick={() => void recover("retry", stepId)} className="rounded-lg border border-[var(--ag-card-border)] px-3 py-2 text-xs text-[var(--ag-text)]">Reintentar lectura {stepId}</button>)}</div> : null}
    {state === "approved" && recovery.unknownStepIds.length ? <p className="mt-3 text-xs text-amber-300">Resultado por confirmar en: {recovery.unknownStepIds.join(", ")}. Tessera no repetirá esas acciones hasta conciliarlas.</p> : null}
    {state === "approved" && recovery.cancelAllowed ? <button type="button" onClick={() => void recover("cancel")} className="mt-3 rounded-lg border border-red-500/40 px-3 py-2 text-xs text-red-300">Cancelar trabajo pendiente</button> : null}
    {state !== "approved" && state !== "rejected" ? <div className="mt-4 flex flex-wrap gap-2"><button disabled={superseded || state === "saving" || Boolean(workflow.blockers?.length)} onClick={() => void decide(true)} className="rounded-lg bg-[var(--ag-purple)] px-3 py-2 text-xs font-semibold text-white disabled:opacity-40">{slackDraft ? "Confirmar y enviar" : "Aprobar este plan"}</button>{slackDraft && onEdit ? <button disabled={state === "saving"} onClick={() => onEdit(slackDraft.text)} className="rounded-lg border border-[var(--ag-card-border)] px-3 py-2 text-xs text-[var(--ag-text)]">Cambiar mensaje</button> : null}<button disabled={state === "saving"} onClick={() => void decide(false)} className="rounded-lg border border-[var(--ag-card-border)] px-3 py-2 text-xs text-[var(--ag-text)]">Rechazar</button></div> : null}
    {/* Only while the draft is still answerable. Once approved the approval
        already landed, and saying it "is no longer valid" both contradicts the
        confirmation below it and invites someone to re-send a message that
        was already sent. */}
    {superseded && state !== "approved" && state !== "rejected" ? <p role="status" className="mt-2 text-xs text-amber-300">El mensaje cambió. Esta aprobación ya no es válida; envía el nuevo texto para generar otra revisión.</p> : null}
    {state !== "idle" && state !== "saving" ? <p role={state === "failed" ? "alert" : "status"} className="mt-2 text-xs text-[var(--ag-text-secondary)]">{state === "approved" ? "Plan aprobado para esta revisión." : state === "rejected" ? "Plan rechazado. No se ejecutó nada." : state === "cancelled" ? "Trabajo pendiente cancelado. Los efectos ya completados se conservan." : "No pude guardar la decisión en tu sesión segura."}</p> : null}
  </section>;
}

function formatEffectValue(value: unknown) {
  if (value && typeof value === "object" && "$ref" in value) return `Se completará con ${String((value as { $ref: unknown }).$ref)}`;
  const rendered = typeof value === "string" ? value : JSON.stringify(value);
  return rendered.length > 240 ? `${rendered.slice(0, 237)}...` : rendered;
}

function effectFieldLabel(field: string) {
  return ({
    persona_id: "Persona", persona_version: "Versión de persona", model: "Modelo fijado",
    opening_script: "Guion inicial exacto", topic_policy_id: "Política de temas",
    topic_policy_version: "Versión de política", maximum_duration_seconds: "Duración máxima (segundos)",
    transfer_policy_id: "Política de transferencia", transfer_policy_version: "Versión de transferencia",
    recording: "Grabación", definition_hash: "Huella de aprobación",
  } as Record<string, string>)[field] ?? field;
}
