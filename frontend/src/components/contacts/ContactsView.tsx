"use client";

import { useState } from "react";
import ContactsTable, { type ContactTableItem } from "./ContactsTable";
import ContactsTreeView from "./ContactsTreeView";

type ViewMode = "table" | "tree";

export default function ContactsView({
  contacts,
  branchLabel,
  loading = false,
  error = "",
}: {
  contacts: ContactTableItem[];
  branchLabel: string;
  loading?: boolean;
  error?: string;
}) {
  const [mode, setMode] = useState<ViewMode>("table");
  return (
    <section aria-labelledby="contacts-view-title" className="overflow-hidden rounded-[10px] border border-[var(--ag-card-border)] bg-[var(--ag-card)]">
      <div className="flex flex-wrap items-center justify-between gap-[8px] border-b border-[var(--ag-divider)] px-[12px] py-[9px]">
        <div className="min-w-0">
          <h2 id="contacts-view-title" className="truncate text-[12px] font-semibold text-[var(--ag-text)]">{branchLabel}</h2>
          <p className="text-[10px] text-[var(--ag-text-muted)]">{contacts.length} items en esta rama</p>
        </div>
        <div role="group" aria-label="Estilo de visualización" className="flex rounded-[7px] border border-[var(--ag2-border)] bg-[var(--ag2-input)] p-[2px]">
          <ViewButton active={mode === "table"} onClick={() => setMode("table")}>Tabla</ViewButton>
          <ViewButton active={mode === "tree"} onClick={() => setMode("tree")}>Árbol</ViewButton>
        </div>
      </div>
      {error ? <p role="alert" className="p-[12px] text-[11px] text-[var(--ag-orange)]">{error}</p> : loading ? (
        <p role="status" className="p-[12px] text-[11px] text-[var(--ag-text-muted)]">Cargando contactos…</p>
      ) : mode === "table" ? (
        <ContactsTable contacts={contacts} showHeader={false} />
      ) : (
        <ContactsTreeView contacts={contacts} />
      )}
    </section>
  );
}

function ViewButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" aria-pressed={active} onClick={onClick} className={`rounded-[5px] px-[9px] py-[4px] text-[10px] font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--ag-purple)] ${active ? "bg-[#5D20DC] text-white" : "text-[var(--ag-text-muted)] hover:text-[var(--ag-text)]"}`}>
      {children}
    </button>
  );
}
