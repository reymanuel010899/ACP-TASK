export type SlackCitation = {
  citation_id?: string;
  permalink: string;
  author_label?: string;
  occurred_at?: string;
  message_ts?: string;
};

export default function SlackEvidenceCard({
  answer,
  citations,
  period,
  partial = false,
}: {
  answer: string;
  citations: SlackCitation[];
  period?: { oldest?: string; latest?: string; label?: string };
  partial?: boolean;
}) {
  return (
    <section aria-label="Slack answer" className="min-w-0 text-[12px] text-[var(--ag-text)]">
      <p className="whitespace-pre-wrap leading-[1.6]">{answer}</p>
      {period ? (
        <p className="mt-2 text-[10px] text-[var(--ag-text-muted)]">
          Periodo revisado: {period.label ?? [period.oldest, period.latest].filter(Boolean).join(" – ")}
        </p>
      ) : null}
      {partial ? (
        <p role="status" className="mt-2 text-[10px] text-amber-300">
          Resultados parciales: Slack o el límite de seguridad acotó la revisión.
        </p>
      ) : null}
      {citations.length ? (
        <ul aria-label="Slack sources" className="mt-3 space-y-1.5">
          {citations.map((citation, index) => (
            <li key={citation.citation_id ?? `${citation.permalink}-${index}`}>
              <a
                href={citation.permalink}
                target="_blank"
                rel="noreferrer noopener"
                className="inline-flex max-w-full items-center gap-1 rounded-md text-[10px] font-medium text-[var(--ag-purple)] underline decoration-transparent underline-offset-2 transition-colors hover:decoration-current focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ag-purple)]"
                aria-label={`Abrir mensaje fuente de Slack${citation.author_label ? ` de ${citation.author_label}` : ""}`}
              >
                <span className="truncate">{citation.author_label ?? "Mensaje de Slack"}</span>
                <span className="shrink-0 text-[var(--ag-text-muted)]">{citation.occurred_at ?? citation.message_ts ?? `Fuente ${index + 1}`}</span>
              </a>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
