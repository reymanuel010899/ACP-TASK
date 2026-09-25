"use client";

export type ContactTableItem = {
  contactId: string;
  displayName: string;
  givenName?: string | null;
  familyName?: string | null;
  companyName?: string | null;
  jobTitle?: string | null;
  status: string;
  source: string;
  recordVersion: string;
  canEdit?: boolean;
};

export type ContactsTableProps = {
  contacts: ContactTableItem[];
  loading?: boolean;
  error?: string;
  showHeader?: boolean;
  onEdit?: (contact: ContactTableItem) => void;
};

export default function ContactsTable({ contacts, loading = false, error = "", showHeader = true, onEdit }: ContactsTableProps) {
  const showEditActions = Boolean(onEdit && contacts.some((contact) => contact.canEdit));
  return (
    <section aria-labelledby={showHeader ? "branch-contacts-title" : undefined} className={showHeader ? "overflow-hidden rounded-[10px] border border-[var(--ag-card-border)] bg-[var(--ag-card)]" : "overflow-hidden"}>
      {showHeader ? <div className="flex items-center justify-between border-b border-[var(--ag-divider)] px-[12px] py-[9px]">
        <h2 id="branch-contacts-title" className="text-[12px] font-semibold text-[var(--ag-text)]">Contactos de la rama</h2>
        <span className="text-[10px] text-[var(--ag-text-muted)]">{contacts.length} items</span>
      </div> : null}
      {error ? <p role="alert" className="p-[12px] text-[11px] text-[var(--ag-orange)]">{error}</p> : loading ? (
        <p role="status" className="p-[12px] text-[11px] text-[var(--ag-text-muted)]">Cargando contactos…</p>
      ) : contacts.length === 0 ? (
        <p role="status" className="p-[12px] text-[11px] text-[var(--ag-text-muted)]">Esta rama todavía no contiene contactos.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left text-[11px]">
            <thead className="bg-[var(--ag2-input)] text-[10px] uppercase tracking-wide text-[var(--ag-text-muted)]">
              <tr>
                <th className="px-[12px] py-[8px] font-medium">Nombre</th>
                <th className="px-[12px] py-[8px] font-medium">Empresa</th>
                <th className="px-[12px] py-[8px] font-medium">Puesto</th>
                <th className="px-[12px] py-[8px] font-medium">Origen</th>
                <th className="px-[12px] py-[8px] font-medium">Estado</th>
                {showEditActions ? <th className="px-[12px] py-[8px] text-right font-medium">Acciones</th> : null}
              </tr>
            </thead>
            <tbody>
              {contacts.map((contact) => (
                <tr key={contact.contactId} className="border-t border-[var(--ag-divider)] text-[var(--ag-text-secondary)]">
                  <td className="px-[12px] py-[9px] font-medium text-[var(--ag-text)]">{contact.displayName}</td>
                  <td className="px-[12px] py-[9px]">{contact.companyName || "—"}</td>
                  <td className="px-[12px] py-[9px]">{contact.jobTitle || "—"}</td>
                  <td className="px-[12px] py-[9px]">{contact.source}</td>
                  <td className="px-[12px] py-[9px]"><span className="rounded-full bg-[var(--ag-chip)] px-[7px] py-[3px] text-[10px]">{contact.status}</span></td>
                  {showEditActions ? <td className="px-[12px] py-[9px] text-right">{contact.canEdit ? <EditButton contact={contact} onEdit={onEdit!} /> : null}</td> : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function EditButton({ contact, onEdit }: { contact: ContactTableItem; onEdit: (contact: ContactTableItem) => void }) {
  return <button type="button" onClick={() => onEdit(contact)} aria-label={`Editar ${contact.displayName}`} className="rounded-[7px] border border-[#7c3aed]/30 bg-[#7c3aed]/10 px-[8px] py-[4px] text-[10px] font-semibold text-[#bba6ed] hover:bg-[#7c3aed]/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#7c3aed]">Editar</button>;
}
