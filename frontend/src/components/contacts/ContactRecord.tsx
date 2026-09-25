"use client";

// One person, as a contact manager sees them (R10).
//
// This is the screen the plan left out. Everything Phase 2 built about a
// contact -- addresses, four independent axes, the evidence behind a grant,
// why they fell out of an audience -- had no surface at all, which meant a
// contact manager could neither validate a record nor explain one.
//
// Two rules the component's *shape* enforces, rather than its rendering:
//
// * **There is no prop that carries a destination the server withheld.** The
//   written form arrives as `writtenAddress`, and the server includes that key
//   only for a principal who holds view over the branch. A redacted record
//   simply has no such field, so no future edit can wire one field to another
//   and leak the digits.
// * **Usability, suppression, provider reachability and consent are rendered
//   as four separate readings.** Collapsing them into one badge is the exact
//   mistake U6 exists to prevent: a live grant and a bounce suppression are
//   both true at once, and an operator shown only the losing one has no way to
//   act.

import type { MaskedDestination } from "./ProposalQueue";

export type ConsentReading = {
  state: string;
  captureMethod?: string | null;
  capturedAt?: string | null;
  jurisdiction?: string | null;
  legalBasis?: string | null;
  disclosureHash?: string | null;
  expiresAt?: string | null;
  decidedByPrincipalId?: string | null;
};

export type ContactAddressView = {
  addressId: string;
  channel: string;
  isPrimary: boolean;
  label?: string | null;
  lastContactedAt?: string | null;
  destination: MaskedDestination;
  // Present only when the server decided this principal may read it.
  writtenAddress?: string;
  usability: string;
  suppression: string;
  providerReachability: string;
  consent: Record<string, ConsentReading>;
  // Purpose -> why an effect on this address would be refused right now.
  exclusions: Record<string, string>;
};

export type ContactRecordData = {
  contactId: string;
  recordVersion: string;
  branchPath?: string | null;
  status: string;
  source: string;
  displayName?: string;
  givenName?: string | null;
  familyName?: string | null;
  companyName?: string | null;
  jobTitle?: string | null;
  // True when the identity was withheld -- campaign-use without view.
  redacted?: boolean;
  addresses: ContactAddressView[];
  authorizedChannels: string[];
  mayEdit: boolean;
};

export type ContactRecordProps = {
  record: ContactRecordData | null;
  onEdit?: (contactId: string) => void;
  notFoundMessage?: string;
};

const AXIS_LABELS: Record<string, string> = {
  usability: "Uso del destino",
  suppression: "Supresión",
  providerReachability: "Alcance del operador",
};

export function isReachable(address: ContactAddressView, purpose: string) {
  return !(purpose in address.exclusions);
}

export default function ContactRecord({
  record,
  onEdit,
  notFoundMessage = "No hay ninguna ficha que puedas ver con este identificador.",
}: ContactRecordProps) {
  if (record === null) {
    // Absence, not refusal. The server answers the same way for a contact in
    // another account and for one this principal may not see, and so does
    // this screen -- a distinguishable message confirms the person exists.
    return (
      <p role="status" className="text-[11px] text-[var(--ag-text-muted)]">
        {notFoundMessage}
      </p>
    );
  }
  const redacted = Boolean(record.redacted);
  return (
    <article
      aria-label="Ficha de contacto"
      className="box-border flex flex-col gap-[12px] rounded-[10px] border border-[var(--ag-card-border)] bg-[var(--ag-card)] p-[14px]"
    >
      <header className="flex flex-row items-start justify-between gap-[10px]">
        <div className="flex flex-col gap-[2px]">
          <h2 className="text-[14px] font-semibold text-[var(--ag-text)]">
            {redacted ? "Identidad reservada" : record.displayName}
          </h2>
          <p className="text-[10px] text-[var(--ag-text-muted)]">
            {record.branchPath ?? "sin rama"} · {record.status} · origen {record.source}
          </p>
          {redacted ? (
            <p role="status" className="text-[10px] text-[var(--ag-orange)]">
              Tienes uso en campañas pero no lectura: puedes revisar destinos y exclusiones, no nombres.
            </p>
          ) : (
            <p className="text-[10px] text-[var(--ag-text-secondary)]">
              {[record.companyName, record.jobTitle].filter(Boolean).join(" · ") || "—"}
            </p>
          )}
        </div>
        <button
          type="button"
          disabled={!record.mayEdit}
          onClick={() => onEdit?.(record.contactId)}
          className="rounded-[8px] border border-[var(--ag-card-border)] px-[12px] py-[6px] text-[11px] text-[var(--ag-text-secondary)] hover:text-[var(--ag-text)] disabled:cursor-not-allowed disabled:opacity-40"
        >
          Editar ficha
        </button>
      </header>

      <p className="text-[10px] text-[var(--ag-text-muted)]">
        Canales autorizados ahora mismo:{" "}
        <span data-testid="authorized-channels">
          {record.authorizedChannels.length > 0 ? record.authorizedChannels.join(", ") : "ninguno"}
        </span>
      </p>

      <ul className="flex flex-col gap-[10px]">
        {record.addresses.map((address) => (
          <AddressCard key={address.addressId} address={address} />
        ))}
      </ul>
      {record.addresses.length === 0 ? (
        <p role="status" className="text-[11px] text-[var(--ag-text-muted)]">
          Esta persona no tiene ningún destino registrado.
        </p>
      ) : null}
    </article>
  );
}

function AddressCard({ address }: { address: ContactAddressView }) {
  const axes: Array<[string, string]> = [
    ["usability", address.usability],
    ["suppression", address.suppression],
    ["providerReachability", address.providerReachability],
  ];
  const exclusions = Object.entries(address.exclusions);
  return (
    <li
      aria-label={`Destino ${address.channel}`}
      className="flex flex-col gap-[6px] rounded-[8px] border border-[var(--ag-divider)] p-[10px]"
    >
      <div className="flex flex-row items-baseline gap-[8px]">
        <span className="text-[11px] font-semibold text-[var(--ag-text)]" data-testid="masked-destination">
          {address.destination.text}
        </span>
        <span className="text-[10px] uppercase tracking-wide text-[var(--ag-text-muted)]">
          {address.channel}
          {address.isPrimary ? " · principal" : ""}
        </span>
      </div>
      {address.writtenAddress ? (
        <p className="text-[10px] text-[var(--ag-text-secondary)]">
          Tal como se escribió: <span data-testid="written-address">{address.writtenAddress}</span>
        </p>
      ) : null}
      <p className="font-mono text-[10px] text-[var(--ag-text-muted)]">{address.destination.fingerprint}</p>

      <dl className="grid grid-cols-[auto_1fr] gap-x-[10px] gap-y-[2px] text-[10px] text-[var(--ag-text-secondary)]">
        {axes.map(([axis, value]) => (
          <div key={axis} className="contents">
            <dt className="text-[var(--ag-text-muted)]">{AXIS_LABELS[axis]}</dt>
            <dd data-testid={`axis-${axis}`}>{value}</dd>
          </div>
        ))}
        <dt className="text-[var(--ag-text-muted)]">Último contacto</dt>
        <dd>{address.lastContactedAt ?? "nunca"}</dd>
      </dl>

      {address.usability !== "active" ? (
        <p role="status" className="text-[10px] text-[var(--ag-orange)]">
          Este destino no puede recibir ningún efecto hasta que una persona autorizada lo active.
        </p>
      ) : null}

      <ConsentTable consent={address.consent} />

      {exclusions.length > 0 ? (
        <div>
          <p className="text-[10px] text-[var(--ag-text-muted)]">Motivos de exclusión</p>
          <ul className="flex flex-col gap-[1px]">
            {exclusions.map(([purpose, reason]) => (
              <li key={purpose} className="text-[10px] text-[var(--ag-text-secondary)]">
                {purpose}: <span data-testid={`exclusion-${purpose}`}>{reason}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </li>
  );
}

function ConsentTable({ consent }: { consent: Record<string, ConsentReading> }) {
  const rows = Object.entries(consent);
  if (rows.length === 0) {
    return null;
  }
  return (
    <table className="w-full border-collapse text-left text-[10px] text-[var(--ag-text-secondary)]">
      <caption className="sr-only">Consentimiento por finalidad</caption>
      <thead>
        <tr className="text-[var(--ag-text-muted)]">
          <th scope="col">Finalidad</th>
          <th scope="col">Estado</th>
          <th scope="col">Captura</th>
          <th scope="col">Jurisdicción</th>
          <th scope="col">Base legal</th>
          <th scope="col">Prueba</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(([purpose, reading]) => (
          <tr key={purpose} data-testid={`consent-${purpose}`}>
            <th scope="row" className="font-normal">
              {purpose}
            </th>
            <td>{reading.state}</td>
            <td>{reading.captureMethod ?? "—"}</td>
            <td>{reading.jurisdiction ?? "—"}</td>
            <td>{reading.legalBasis ?? "—"}</td>
            {/* The verbatim disclosure is never sent to the browser: its hash
                is what proves the words shown have not changed since. */}
            <td className="font-mono">{reading.disclosureHash?.slice(0, 8) ?? "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
