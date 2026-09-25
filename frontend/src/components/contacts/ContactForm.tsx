"use client";

// Adding and correcting one person by hand (R12).
//
// The manual arm of "may be added manually or imported", and deliberately the
// same shape as the import review beside it: a destination entered here lands
// unusable, and becomes usable only when somebody records the evidence U6
// requires. The form says so out loud rather than letting a person discover it
// when their first message is refused.
//
// `missingEvidenceFields` is imported from the proposal queue rather than
// rewritten. There is one definition of "this consent record is defensible" in
// the browser, and it is the one that already mirrors
// `libs/contacts_consent.py`; a second copy would drift on the first change to
// either.

import { useState } from "react";

import { missingEvidenceFields, type ConsentEvidenceDraft } from "./ProposalQueue";

export type ContactBranchOption = { branchId: string; path: string };

export type ContactFormValues = {
  displayName: string;
  givenName: string;
  familyName: string;
  companyName: string;
  jobTitle: string;
};

export type ContactFormSubmission = {
  branchId: string;
  values: ContactFormValues;
  contactId?: string;
  recordVersion?: string;
  channel?: string;
  address?: string;
  consent?: { purposes: string[]; evidence: ConsentEvidenceDraft };
};

export type ContactFormProps = {
  branches: ContactBranchOption[];
  // Present for an edit; absent for a create. An edit carries the version the
  // record was read at, so a change made behind this form is refused rather
  // than silently overwritten.
  initial?: (ContactFormValues & { contactId: string; branchId: string; recordVersion: string }) | null;
  onSubmit: (submission: ContactFormSubmission) => void | Promise<void>;
  busy?: boolean;
};

const CAPTURE_METHODS = [
  "web_form",
  "embedded_form",
  "import_form",
  "verbal_recorded",
  "inbound_keyword",
  "contract",
];

const PURPOSES = ["marketing", "utility", "authentication", "transactional", "service"];

const CHANNELS = ["sms", "whatsapp", "voice", "email"];

function emptyValues(): ContactFormValues {
  return { displayName: "", givenName: "", familyName: "", companyName: "", jobTitle: "" };
}

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

export default function ContactForm({ branches, initial = null, onSubmit, busy = false }: ContactFormProps) {
  const editing = initial !== null;
  const [values, setValues] = useState<ContactFormValues>(
    initial ? { ...emptyValues(), ...stripIdentity(initial) } : emptyValues(),
  );
  const [branchId, setBranchId] = useState(initial?.branchId ?? branches[0]?.branchId ?? "");
  const [channel, setChannel] = useState("sms");
  const [address, setAddress] = useState("");
  const [claimsConsent, setClaimsConsent] = useState(false);
  const [purposes, setPurposes] = useState<string[]>([]);
  const [evidence, setEvidence] = useState<ConsentEvidenceDraft>(emptyEvidence);

  const set = <K extends keyof ContactFormValues>(key: K, value: ContactFormValues[K]) =>
    setValues((current) => ({ ...current, [key]: value }));
  const setEvidenceField = <K extends keyof ConsentEvidenceDraft>(key: K, value: ConsentEvidenceDraft[K]) =>
    setEvidence((current) => ({ ...current, [key]: value }));

  const missing = claimsConsent ? missingEvidenceFields(evidence) : [];
  const needsPurpose = claimsConsent && purposes.length === 0;
  const blocked =
    busy ||
    !values.displayName.trim() ||
    !branchId ||
    (claimsConsent && (missing.length > 0 || needsPurpose)) ||
    (claimsConsent && !address.trim());

  function submit() {
    void onSubmit({
      branchId,
      values,
      contactId: initial?.contactId,
      recordVersion: initial?.recordVersion,
      channel: editing || !address.trim() ? undefined : channel,
      address: editing ? undefined : address.trim() || undefined,
      consent: !editing && claimsConsent ? { purposes, evidence } : undefined,
    });
  }

  return (
    <form
      aria-label={editing ? "Corregir contacto" : "Nuevo contacto"}
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
      className="box-border flex flex-col gap-[10px] rounded-[10px] border border-[var(--ag-card-border)] bg-[var(--ag-card)] p-[14px]"
    >
      <Field label="Nombre visible" value={values.displayName} onChange={(value) => set("displayName", value)} />
      <Field label="Nombre" value={values.givenName} onChange={(value) => set("givenName", value)} />
      <Field label="Apellidos" value={values.familyName} onChange={(value) => set("familyName", value)} />
      <Field label="Empresa" value={values.companyName} onChange={(value) => set("companyName", value)} />
      <Field label="Puesto" value={values.jobTitle} onChange={(value) => set("jobTitle", value)} />

      <label className="flex flex-col gap-[2px] text-[10px] text-[var(--ag-text-muted)]">
        Rama
        <select
          value={branchId}
          disabled={editing}
          onChange={(event) => setBranchId(event.target.value)}
          className="rounded border border-[var(--ag2-border)] bg-[var(--ag2-input)] px-[6px] py-[4px] text-[11px] text-[var(--ag-text)] disabled:opacity-40"
        >
          {branches.map((branch) => (
            <option key={branch.branchId} value={branch.branchId}>
              {branch.path}
            </option>
          ))}
        </select>
      </label>
      {editing ? (
        <p className="text-[10px] text-[var(--ag-text-muted)]">
          Mover a otra rama y cambiar destinos o consentimiento no se hacen desde aquí: cada uno tiene su propia
          decisión registrada.
        </p>
      ) : null}

      {editing ? null : (
        <fieldset className="flex flex-col gap-[6px] rounded-[8px] border border-[var(--ag-divider)] p-[8px]">
          <legend className="px-[4px] text-[10px] text-[var(--ag-text-muted)]">Destino</legend>
          <label className="flex flex-col gap-[2px] text-[10px] text-[var(--ag-text-muted)]">
            Canal
            <select
              value={channel}
              onChange={(event) => setChannel(event.target.value)}
              className="rounded border border-[var(--ag2-border)] bg-[var(--ag2-input)] px-[6px] py-[4px] text-[11px] text-[var(--ag-text)]"
            >
              {CHANNELS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>
          <Field
            label={channel === "email" ? "Correo electrónico" : "Número en formato internacional"}
            value={address}
            type={channel === "email" ? "email" : "tel"}
            placeholder={channel === "email" ? "persona@ejemplo.com" : "+15165550100"}
            onChange={setAddress}
          />
          <p role="status" className="text-[10px] text-[var(--ag-orange)]">
            Un destino nuevo queda inutilizable hasta que alguien autorizado lo active.
          </p>
        </fieldset>
      )}

      {editing ? null : (
        <label className="flex items-center gap-[6px] text-[10px] text-[var(--ag-text-muted)]">
          <input
            type="checkbox"
            checked={claimsConsent}
            onChange={(event) => {
              const checked = event.target.checked;
              setClaimsConsent(checked);
              if (checked && !evidence.legalBasis) {
                setEvidenceField("legalBasis", "consent");
              }
            }}
          />
          Tengo evidencia de consentimiento para esta persona
        </label>
      )}

      {claimsConsent ? (
        <fieldset className="flex flex-col gap-[6px] rounded-[8px] border border-[var(--ag-divider)] p-[8px]">
          <legend className="px-[4px] text-[10px] text-[var(--ag-orange)]">Evidencia de consentimiento</legend>
          <fieldset className="flex flex-row flex-wrap gap-[8px]">
            <legend className="text-[10px] text-[var(--ag-text-muted)]">Finalidades</legend>
            {PURPOSES.map((purpose) => (
              <label key={purpose} className="flex items-center gap-[4px] text-[10px] text-[var(--ag-text-muted)]">
                <input
                  type="checkbox"
                  checked={purposes.includes(purpose)}
                  onChange={(event) =>
                    setPurposes((current) =>
                      event.target.checked
                        ? [...current, purpose]
                        : current.filter((value) => value !== purpose),
                    )
                  }
                />
                {purpose}
              </label>
            ))}
          </fieldset>
          <label className="flex flex-col gap-[2px] text-[10px] text-[var(--ag-text-muted)]">
            Método de captura
            <select
              value={evidence.captureMethod}
              onChange={(event) => setEvidenceField("captureMethod", event.target.value)}
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
          <Field
            label="Fecha y hora locales"
            value={evidence.capturedAtLocal}
            type="datetime-local"
            onChange={(value) => setEvidenceField("capturedAtLocal", value)}
          />
          <Field
            label="Zona horaria"
            value={evidence.captureTimezone}
            onChange={(value) => setEvidenceField("captureTimezone", value)}
          />
          <Field
            label="Jurisdicción"
            value={evidence.jurisdiction}
            onChange={(value) => setEvidenceField("jurisdiction", value)}
          />
          <Field
            label="Texto mostrado"
            value={evidence.disclosureText}
            onChange={(value) => setEvidenceField("disclosureText", value)}
          />
          <Field
            label="Base legal"
            value={evidence.legalBasis}
            onChange={(value) => setEvidenceField("legalBasis", value)}
          />
          <label className="flex items-center gap-[6px] text-[10px] text-[var(--ag-text-muted)]">
            <input
              type="checkbox"
              checked={evidence.defaultUnchecked}
              onChange={(event) => setEvidenceField("defaultUnchecked", event.target.checked)}
            />
            La casilla empezó vacía
          </label>
          {missing.length > 0 ? (
            <p role="status" className="text-[10px] text-[var(--ag-orange)]">
              Falta evidencia: {missing.join(", ")}
            </p>
          ) : null}
          {needsPurpose ? (
            <p role="status" className="text-[10px] text-[var(--ag-orange)]">
              Un consentimiento vale para las finalidades que nombra: elige al menos una.
            </p>
          ) : null}
        </fieldset>
      ) : null}

      <button
        type="submit"
        disabled={blocked}
        className="w-fit rounded-[8px] bg-[#5D20DC] px-[12px] py-[6px] text-[11px] font-semibold text-white hover:bg-[#6d2ee8] disabled:cursor-not-allowed disabled:opacity-40"
      >
        {editing ? "Guardar corrección" : "Crear contacto"}
      </button>
    </form>
  );
}

function stripIdentity(initial: ContactFormValues & { contactId: string }): ContactFormValues {
  return {
    displayName: initial.displayName,
    givenName: initial.givenName,
    familyName: initial.familyName,
    companyName: initial.companyName,
    jobTitle: initial.jobTitle,
  };
}

function Field({
  label,
  value,
  onChange,
  type = "text",
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  placeholder?: string;
}) {
  return (
    <label className="flex flex-col gap-[2px] text-[10px] text-[var(--ag-text-muted)]">
      {label}
      <input
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className="rounded border border-[var(--ag2-border)] bg-[var(--ag2-input)] px-[6px] py-[4px] text-[11px] text-[var(--ag-text)]"
      />
    </label>
  );
}
