"use client";

import { useState } from "react";

type AudienceRow = {
  contactId: string;
  channel: string;
  maskedDestination: string;
  branchId: string;
};

export type CampaignPreview = {
  campaignId: string;
  eligibleCount: number;
  estimatedSpendMicros: number;
  audience: AudienceRow[];
  exclusionReasons: Record<string, number>;
  envelopeHash: string;
};

export default function CampaignAuthorization({
  preview,
  onAuthorize,
  busy = false,
}: {
  preview: CampaignPreview;
  onAuthorize: (campaignId: string, envelopeHash: string) => void | Promise<void>;
  busy?: boolean;
}) {
  const [acknowledged, setAcknowledged] = useState(false);
  const money = (preview.estimatedSpendMicros / 1_000_000).toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
  });

  return (
    <section aria-labelledby="campaign-authorization-title" className="space-y-4 rounded-lg border border-[var(--ag-card-border)] bg-[var(--ag-card)] p-4">
      <div>
        <h2 id="campaign-authorization-title" className="text-sm font-semibold text-[var(--ag-text)]">Revisar y autorizar</h2>
        <p className="text-xs text-[var(--ag-text-secondary)]">{preview.eligibleCount} contactos elegibles</p>
        <p className="text-xs text-[var(--ag-text-secondary)]">Gasto máximo estimado: {money}</p>
      </div>

      <div aria-label="Redacted campaign audience" className="space-y-2">
        {preview.audience.map((row) => (
          <div key={`${row.contactId}:${row.channel}`} className="rounded border border-[var(--ag-card-border)] p-2 text-xs text-[var(--ag-text-secondary)]">
            <span className="font-medium text-[var(--ag-text)]">{row.maskedDestination}</span>
            <span> · {row.channel} · {row.branchId}</span>
          </div>
        ))}
      </div>

      <div>
        <h3 className="text-xs font-semibold text-[var(--ag-text)]">Excluidos</h3>
        <ul className="text-xs text-[var(--ag-text-secondary)]">
          {Object.entries(preview.exclusionReasons).map(([reason, count]) => (
            <li key={reason}>{reason.replaceAll("_", " ")}: {count}</li>
          ))}
        </ul>
      </div>

      <label className="flex gap-2 text-xs text-[var(--ag-text-secondary)]">
        <input type="checkbox" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} />
        Autorizo esta audiencia, contenido, horario, límites y presupuesto exactos.
      </label>
      <button
        type="button"
        disabled={!acknowledged || busy}
        onClick={() => void onAuthorize(preview.campaignId, preview.envelopeHash)}
        className="rounded-md bg-[var(--ag-purple)] px-4 py-2 text-xs font-semibold text-white disabled:opacity-50"
      >
        {busy ? "Lanzando…" : "Autorizar y lanzar"}
      </button>
    </section>
  );
}
