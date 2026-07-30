"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { CAPABILITIES } from "@/data/capabilities";
import CapabilityPicker from "@/components/agents/CapabilityPicker";
import { useSession } from "@/lib/SessionProvider";

/**
 * Create/Add Agent — modal wizard (plan 2026-07-23-002, U5). Creation defines a
 * SPEC (name, template, capabilities, pricing) — it no longer generates or
 * discards a client-side keypair. Identity is assigned at Deploy time by the
 * runner (which owns the keys-dir). Steps: Basics → Skills → Review → Success
 * ("created, stopped — Start it to go live"). Posts to `POST /api/agents`.
 */

type StepKey = "basics" | "skills" | "review" | "success";

const STEPS: { key: StepKey; label: string }[] = [
  { key: "basics", label: "Basics" },
  { key: "skills", label: "Capabilities" },
  { key: "review", label: "Review" },
];

// Mirrors runner/templates.py — the runnable behaviors the runner can launch.
const TEMPLATES = [
  { key: "terraform-provider", label: "Terraform Provider", capability: "terraform.generate" },
];

type Draft = {
  name: string;
  description: string;
  version: string;
  template: string;
  listPrice: string;
  minPrice: string;
  capabilities: string[]; // capability ids
};

const VERSION_RE = /^\d+\.\d+\.\d+$/;

function basicsErrors(d: Draft): { name?: string; version?: string; price?: string } {
  const e: { name?: string; version?: string; price?: string } = {};
  if (!d.name.trim()) e.name = "Name is required.";
  if (!VERSION_RE.test(d.version.trim())) e.version = "Version must be semver like 0.1.0.";
  const lp = d.listPrice === "" ? null : Number(d.listPrice);
  const mp = d.minPrice === "" ? null : Number(d.minPrice);
  if (lp !== null && (Number.isNaN(lp) || lp < 0)) e.price = "Prices must be non-negative numbers.";
  else if (mp !== null && (Number.isNaN(mp) || mp < 0)) e.price = "Prices must be non-negative numbers.";
  else if (lp !== null && mp !== null && mp > lp) e.price = "Min price must not exceed list price.";
  return e;
}

function isStepValid(step: StepKey, d: Draft): boolean {
  if (step === "basics") return Object.keys(basicsErrors(d)).length === 0;
  if (step === "skills") return d.capabilities.length > 0;
  return true;
}

const inputClass =
  "box-border w-full h-fit shrink-0 p-[9px_11px] bg-[var(--ag2-input)] [border:1px_solid_var(--ag2-border)] rounded-[7px] text-[12px]/[normal] text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] outline-none focus:[border-color:#5D20DC]";

function Label({ children }: { children: ReactNode }) {
  return (
    <div className="text-[11px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]">
      {children}
    </div>
  );
}

function FieldError({ msg }: { msg?: string }) {
  if (!msg) return null;
  return (
    <div className="text-[10px]/[normal] box-border text-[#F87171] font-[Inter,system-ui,sans-serif] font-normal text-left">
      {msg}
    </div>
  );
}

function ReviewRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="box-border w-full h-fit flex flex-col gap-[3px] justify-start items-start">
      <Label>{label}</Label>
      <div className="text-[12px]/[normal] box-border w-full text-[var(--ag2-strong)] font-[Inter,system-ui,sans-serif] font-medium text-left break-all">
        {value || "—"}
      </div>
    </div>
  );
}

export default function CreateAgentModal({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated?: () => void;
}) {
  if (!open) return null;
  return <CreateAgentWizard onClose={onClose} onCreated={onCreated} />;
}

function CreateAgentWizard({ onClose, onCreated }: { onClose: () => void; onCreated?: () => void }) {
  const { session } = useSession();
  const [step, setStep] = useState<StepKey>("basics");
  const [showErrors, setShowErrors] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft>({
    name: "",
    description: "",
    version: "0.1.0",
    template: TEMPLATES[0].key,
    listPrice: "6",
    minPrice: "3",
    capabilities: [],
  });

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const headingRef = useRef<HTMLHeadingElement | null>(null);
  useEffect(() => {
    headingRef.current?.focus();
  }, [step]);

  const stepIndex = STEPS.findIndex((s) => s.key === step);
  const errs = basicsErrors(draft);
  const template = TEMPLATES.find((t) => t.key === draft.template) ?? TEMPLATES[0];

  function goNext() {
    if (!isStepValid(step, draft)) {
      setShowErrors(true);
      return;
    }
    setShowErrors(false);
    const next = STEPS[stepIndex + 1];
    if (next) setStep(next.key);
  }
  function goBack() {
    setShowErrors(false);
    const prev = STEPS[stepIndex - 1];
    if (prev) setStep(prev.key);
  }

  async function createAgent() {
    setSubmitting(true);
    setSubmitError(null);
    const body = {
      name: draft.name.trim(),
      description: draft.description,
      version: draft.version.trim(),
      template: draft.template,
      capabilities: draft.capabilities,
      list_price: draft.listPrice === "" ? null : Number(draft.listPrice),
      min_price: draft.minPrice === "" ? null : Number(draft.minPrice),
      // The signed-in user OWNS the agent they add: only they may mutate it.
      owner_principal_id: session?.principalId ?? null,
    };
    try {
      const res = await fetch("/api/agents", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const data = (await res.json().catch(() => null)) as { error?: string } | null;
        setSubmitError(data?.error ?? `Create failed (HTTP ${res.status}).`);
        setSubmitting(false);
        return;
      }
      setSubmitting(false);
      onCreated?.();
      setStep("success");
    } catch {
      setSubmitError("Could not reach the server. Please try again.");
      setSubmitting(false);
    }
  }

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
        aria-label="Create Agent"
        className="box-border w-[720px] max-w-[94vw] h-[640px] max-h-[90vh] flex flex-col bg-[var(--ag2-panel)] [border:1px_solid_var(--ag2-border)] rounded-[12px] overflow-hidden shadow-2xl"
      >
        {/* Header */}
        <div className="box-border w-full shrink-0 flex flex-row gap-0 p-[16px_20px] justify-between items-center [border-width:0px_0px_1px_0px] [border-style:solid] [border-color:var(--ag2-border)]">
          <div className="box-border flex flex-col gap-[2px]">
            <div className="text-[16px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
              Create Agent
            </div>
            <div className="text-[11px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
              Define the agent; deploy it to go live in the protocol.
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="box-border w-[30px] h-[30px] flex items-center justify-center rounded-[7px] bg-[var(--ag2-surface)] [border:1px_solid_var(--ag2-border)] text-[var(--ag2-dim)] text-[14px] cursor-pointer"
          >
            ✕
          </button>
        </div>

        {/* Stepper */}
        {step !== "success" && (
          <div className="box-border w-full shrink-0 flex flex-row gap-[8px] p-[14px_20px] justify-start items-center [border-width:0px_0px_1px_0px] [border-style:solid] [border-color:var(--ag2-border)]">
            {STEPS.map((s, i) => {
              const state = i < stepIndex ? "done" : i === stepIndex ? "active" : "upcoming";
              return (
                <div key={s.key} className="box-border w-fit h-fit shrink-0 flex flex-row gap-[8px] justify-start items-center">
                  <div
                    aria-current={state === "active" ? "step" : undefined}
                    className={`box-border w-fit h-fit shrink-0 flex flex-row gap-[7px] p-[6px_11px] justify-start items-center rounded-[7px] ${
                      state === "active" ? "bg-[#5D20DC]" : "bg-[var(--ag2-surface)] [border:1px_solid_var(--ag2-border)]"
                    }`}
                  >
                    <div
                      className={`box-border w-[18px] h-[18px] shrink-0 flex items-center justify-center rounded-full text-[10px] font-bold ${
                        state === "done"
                          ? "bg-[#35D78B] text-[#0b0a1a]"
                          : state === "active"
                            ? "bg-[#F4F2FF] text-[#5D20DC]"
                            : "bg-[var(--ag2-input-deep)] text-[var(--ag2-muted)]"
                      }`}
                    >
                      {state === "done" ? "✓" : i + 1}
                    </div>
                    <div
                      className={`text-[11px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap] ${
                        state === "active" ? "text-[#F4F2FF]" : "text-[var(--ag2-dim)]"
                      }`}
                    >
                      {s.label}
                    </div>
                  </div>
                  {i < STEPS.length - 1 && <div className="box-border w-[16px] h-[1px] bg-[var(--ag2-border)]"></div>}
                </div>
              );
            })}
          </div>
        )}

        {/* Body */}
        <div className="box-border w-full [flex:1_1_0] min-h-0 overflow-y-auto flex flex-col gap-[14px] p-[20px]">
          {step === "basics" && (
            <>
              <h2 ref={headingRef} tabIndex={-1} className="text-[14px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-left outline-none">
                Basics
              </h2>
              <div className="box-border w-full flex flex-col gap-[5px]">
                <Label>Name</Label>
                <input
                  className={inputClass}
                  value={draft.name}
                  placeholder="DevOps Agent"
                  onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
                  onBlur={() => setShowErrors(true)}
                />
                {showErrors && <FieldError msg={errs.name} />}
              </div>
              <div className="box-border w-full flex flex-col gap-[5px]">
                <Label>Description</Label>
                <textarea
                  className={`${inputClass} min-h-[54px] resize-y`}
                  value={draft.description}
                  placeholder="Infrastructure & deployment specialist…"
                  onChange={(e) => setDraft((d) => ({ ...d, description: e.target.value }))}
                />
              </div>
              <div className="box-border w-full flex flex-row gap-[12px]">
                <div className="box-border [flex:1_1_0] flex flex-col gap-[5px]">
                  <Label>Version</Label>
                  <input
                    className={inputClass}
                    value={draft.version}
                    onChange={(e) => setDraft((d) => ({ ...d, version: e.target.value }))}
                    onBlur={() => setShowErrors(true)}
                  />
                  {showErrors && <FieldError msg={errs.version} />}
                </div>
                <div className="box-border [flex:1_1_0] flex flex-col gap-[5px]">
                  <Label>Template (what it runs)</Label>
                  <select
                    className={inputClass}
                    value={draft.template}
                    onChange={(e) => setDraft((d) => ({ ...d, template: e.target.value }))}
                  >
                    {TEMPLATES.map((t) => (
                      <option key={t.key} value={t.key}>
                        {t.label}
                      </option>
                    ))}
                  </select>
                  <div className="text-[9px]/[normal] box-border text-[var(--ag2-muted)] font-[Inter,system-ui,sans-serif]">
                    Executes <span className="font-mono">{template.capability}</span>
                  </div>
                </div>
              </div>
              <div className="box-border w-full flex flex-row gap-[12px]">
                <div className="box-border [flex:1_1_0] flex flex-col gap-[5px]">
                  <Label>List price (public offer)</Label>
                  <input
                    className={inputClass}
                    type="number"
                    min="0"
                    value={draft.listPrice}
                    onChange={(e) => setDraft((d) => ({ ...d, listPrice: e.target.value }))}
                    onBlur={() => setShowErrors(true)}
                  />
                </div>
                <div className="box-border [flex:1_1_0] flex flex-col gap-[5px]">
                  <Label>Min price (private reserve)</Label>
                  <input
                    className={inputClass}
                    type="number"
                    min="0"
                    value={draft.minPrice}
                    onChange={(e) => setDraft((d) => ({ ...d, minPrice: e.target.value }))}
                    onBlur={() => setShowErrors(true)}
                  />
                </div>
              </div>
              {showErrors && <FieldError msg={errs.price} />}
            </>
          )}

          {step === "skills" && (
            <CapabilityPicker
              selected={draft.capabilities}
              showError={showErrors && draft.capabilities.length === 0}
              onToggle={(cap) =>
                setDraft((d) => ({
                  ...d,
                  capabilities: d.capabilities.includes(cap.id)
                    ? d.capabilities.filter((x) => x !== cap.id)
                    : [...d.capabilities, cap.id],
                }))
              }
              headingRef={headingRef}
            />
          )}

          {step === "review" && (
            <>
              <h2 ref={headingRef} tabIndex={-1} className="text-[14px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-left outline-none">
                Review
              </h2>
              <div className="box-border w-full flex flex-col gap-[10px] p-[16px] bg-[var(--ag2-surface)] [border:1px_solid_var(--ag2-border)] rounded-[9px]">
                <ReviewRow label="Name" value={draft.name} />
                <ReviewRow label="Version · Template" value={`${draft.version} · ${template.label}`} />
                <ReviewRow label="Pricing" value={`list ${draft.listPrice || "—"} · min ${draft.minPrice || "—"}`} />
                <div className="box-border w-full flex flex-col gap-[6px] p-[10px_0px_0px_0px] [border-width:1px_0px_0px_0px] [border-style:solid] [border-color:var(--ag2-border)]">
                  <Label>Capabilities ({draft.capabilities.length})</Label>
                  <div className="box-border w-full flex flex-row gap-[6px] [flex-wrap:wrap]">
                    {draft.capabilities.map((id) => {
                      const cap = CAPABILITIES.find((c) => c.id === id);
                      return (
                        <div key={id} className="box-border w-fit flex flex-row p-[4px_8px] bg-[var(--ag2-chip)] rounded-[4px]">
                          <div className="text-[10px]/[normal] box-border text-[#A78BFA] font-[Inter,system-ui,sans-serif] font-medium [white-space:nowrap]">
                            {cap?.label ?? id}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
              <div className="text-[10px]/[normal] box-border text-[var(--ag2-muted)] font-[Inter,system-ui,sans-serif]">
                The agent is created <b>stopped</b>. Deploy it (Start) to mint its identity and go live in the protocol.
              </div>
              {submitError && (
                <div className="box-border w-full flex flex-row gap-[8px] p-[10px_12px] bg-[#2A1518] [border:1px_solid_#5a2330] rounded-[8px]">
                  <div className="text-[12px] text-[#F87171]">⚠</div>
                  <div className="text-[11px]/[normal] box-border text-[#FCA5A5] font-[Inter,system-ui,sans-serif]">{submitError}</div>
                </div>
              )}
            </>
          )}

          {step === "success" && (
            <div className="box-border w-full flex flex-col gap-[14px] p-[8px] justify-start items-center">
              <div className="box-border w-[52px] h-[52px] flex items-center justify-center rounded-full bg-[#073C31] text-[24px] text-[#35D78B]">
                ✓
              </div>
              <h2 ref={headingRef} tabIndex={-1} className="text-[18px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-center outline-none">
                Agent created
              </h2>
              <div className="text-[12px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-center max-w-[420px]">
                Your agent is registered and <b>stopped</b>. Click <b>Start</b> on it in the list to deploy — the runner mints its identity, launches the process, and it goes Online in the protocol.
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="box-border w-full shrink-0 flex flex-row gap-0 p-[14px_20px] justify-between items-center [border-width:1px_0px_0px_0px] [border-style:solid] [border-color:var(--ag2-border)]">
          {step === "success" ? (
            <>
              <div />
              <button
                type="button"
                onClick={onClose}
                className="box-border w-fit flex flex-row p-[10px_18px] justify-center items-center rounded-[7px] text-[12px] font-semibold font-[Inter,system-ui,sans-serif] bg-[#5D20DC] text-[#F4F2FF] cursor-pointer"
              >
                Done
              </button>
            </>
          ) : (
            <>
              <button type="button" onClick={onClose} className="text-[12px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-medium cursor-pointer">
                Cancel
              </button>
              <div className="box-border w-fit flex flex-row gap-[10px] justify-end items-center">
                {stepIndex > 0 && (
                  <button
                    type="button"
                    onClick={goBack}
                    className="box-border w-fit flex flex-row p-[10px_16px] justify-center items-center bg-[var(--ag2-surface)] [border:1px_solid_var(--ag2-border)] rounded-[7px] cursor-pointer text-[12px] text-[var(--ag2-text)] font-semibold font-[Inter,system-ui,sans-serif]"
                  >
                    Back
                  </button>
                )}
                {step === "review" ? (
                  <button
                    type="button"
                    disabled={submitting}
                    onClick={createAgent}
                    className="box-border w-fit flex flex-row p-[10px_18px] justify-center items-center bg-[#5D20DC] rounded-[7px] cursor-pointer text-[12px] text-[#F4F2FF] font-semibold font-[Inter,system-ui,sans-serif] disabled:opacity-60"
                  >
                    {submitting ? "Creating…" : "Create Agent"}
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={goNext}
                    className="box-border w-fit flex flex-row p-[10px_18px] justify-center items-center bg-[#5D20DC] rounded-[7px] cursor-pointer text-[12px] text-[#F4F2FF] font-semibold font-[Inter,system-ui,sans-serif]"
                  >
                    Next
                  </button>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
