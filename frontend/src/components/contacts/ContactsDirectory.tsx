"use client";

import type { ContactTableItem } from "./ContactsTable";
import type { ContactBranch } from "./ContactsTree";

type ContactsDirectoryProps = {
  branches: ContactBranch[];
  currentBranchId: string | null;
  contacts: ContactTableItem[];
  loading?: boolean;
  contactsLoading?: boolean;
  error?: string;
  onNavigate: (branchId: string | null) => void;
  onEditContact?: (contact: ContactTableItem) => void;
};

export default function ContactsDirectory({
  branches,
  currentBranchId,
  contacts,
  loading = false,
  contactsLoading = false,
  error = "",
  onNavigate,
  onEditContact,
}: ContactsDirectoryProps) {
  const showEditActions = Boolean(onEditContact && contacts.some((contact) => contact.canEdit));
  const trail = currentBranchId ? findTrail(branches, currentBranchId) : [];
  const currentBranch = trail.at(-1) ?? null;
  const folders = currentBranch ? currentBranch.children : branches;
  const totalItems = folders.length + (currentBranch ? contacts.length : 0);

  return (
    <section aria-label="Directorio de contactos" className="min-h-[560px] overflow-hidden rounded-[12px] border border-[var(--ag-card-border)] bg-[var(--ag-card)] shadow-[0_18px_50px_rgba(0,0,0,0.16)]">
      <div className="flex min-h-[48px] items-center justify-between gap-[16px] border-b border-[var(--ag-divider)] px-[16px]">
        <nav aria-label="Ruta de carpetas" className="flex min-w-0 items-center gap-[6px] text-[12px]">
          <button type="button" onClick={() => onNavigate(null)} className="shrink-0 font-semibold text-[var(--ag-text)] hover:text-[#9d79f6] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#7c3aed]">
            Contactos
          </button>
          {trail.map((branch) => (
            <span key={branch.branchId} className="flex min-w-0 items-center gap-[6px]">
              <span aria-hidden="true" className="text-[var(--ag-text-muted)]">/</span>
              <button type="button" onClick={() => onNavigate(branch.branchId)} className="truncate text-[var(--ag-text-secondary)] hover:text-[var(--ag-text)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#7c3aed]">
                {branch.name}
              </button>
            </span>
          ))}
        </nav>
        <span className="shrink-0 text-[10px] text-[var(--ag-text-muted)]">{totalItems} {totalItems === 1 ? "item" : "items"}</span>
      </div>

      {error ? <p role="alert" className="border-b border-[var(--ag-divider)] px-[16px] py-[10px] text-[11px] text-[var(--ag-orange)]">{error}</p> : null}

      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] border-collapse text-left text-[12px]">
          <thead className="bg-[var(--ag2-input)] text-[10px] uppercase tracking-[0.06em] text-[var(--ag-text-muted)]">
            <tr>
              <th className="w-[42%] px-[16px] py-[10px] font-medium">Nombre</th>
              <th className="w-[14%] px-[12px] py-[10px] font-medium">Tipo</th>
              <th className="w-[24%] px-[12px] py-[10px] font-medium">Detalles</th>
              <th className="w-[10%] px-[12px] py-[10px] font-medium">Items</th>
              <th className="w-[10%] px-[12px] py-[10px] font-medium">Estado</th>
              {showEditActions ? <th className="px-[12px] py-[10px] text-right font-medium">Acciones</th> : null}
            </tr>
          </thead>
          <tbody>
            {currentBranch ? (
              <tr className="border-t border-[var(--ag-divider)] text-[var(--ag-text-secondary)] hover:bg-white/[0.025]">
                <td colSpan={showEditActions ? 6 : 5} className="px-[16px] py-[9px]">
                  <button type="button" onClick={() => onNavigate(trail.at(-2)?.branchId ?? null)} className="flex items-center gap-[9px] text-[11px] hover:text-[var(--ag-text)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#7c3aed]">
                    <span aria-hidden="true" className="text-[16px]">↰</span>
                    Volver a la carpeta anterior
                  </button>
                </td>
              </tr>
            ) : null}

            {folders.map((folder) => (
              <tr key={folder.branchId} className="group border-t border-[var(--ag-divider)] text-[var(--ag-text-secondary)] hover:bg-[#7c3aed]/[0.07]">
                <td className="px-[16px] py-[12px]">
                  <button type="button" onClick={() => onNavigate(folder.branchId)} aria-label={`Abrir carpeta ${folder.name}`} className="flex max-w-full items-center gap-[10px] font-semibold text-[var(--ag-text)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#7c3aed]">
                    <FolderIcon />
                    <span className="truncate group-hover:text-[#a98aef]">{folder.name}</span>
                  </button>
                </td>
                <td className="px-[12px] py-[12px]">Carpeta</td>
                <td className="px-[12px] py-[12px] text-[var(--ag-text-muted)]">{folder.kind === "organization" ? "Organización" : "Subcarpeta"}</td>
                <td className="px-[12px] py-[12px] tabular-nums">{folder.contactCount}</td>
                <td className="px-[12px] py-[12px]"><StatusBadge label="Activa" /></td>
                {showEditActions ? <td aria-hidden="true" /> : null}
              </tr>
            ))}

            {currentBranch ? contacts.map((contact) => (
              <tr key={contact.contactId} className="border-t border-[var(--ag-divider)] text-[var(--ag-text-secondary)] hover:bg-white/[0.025]">
                <td className="px-[16px] py-[12px]">
                  <div className="flex min-w-0 items-center gap-[10px] font-medium text-[var(--ag-text)]">
                    <ContactIcon />
                    <span className="truncate">{contact.displayName}</span>
                  </div>
                </td>
                <td className="px-[12px] py-[12px]">Contacto</td>
                <td className="px-[12px] py-[12px]">
                  <span className="block truncate text-[var(--ag-text-secondary)]">{contact.companyName || "Sin empresa"}</span>
                  {contact.jobTitle ? <span className="block truncate text-[10px] text-[var(--ag-text-muted)]">{contact.jobTitle}</span> : null}
                </td>
                <td className="px-[12px] py-[12px] text-[var(--ag-text-muted)]">—</td>
                <td className="px-[12px] py-[12px]"><StatusBadge label={contact.status} /></td>
                {showEditActions ? (
                  <td className="px-[12px] py-[12px] text-right">
                    {contact.canEdit ? <button
                      type="button"
                      onClick={() => onEditContact?.(contact)}
                      aria-label={`Editar ${contact.displayName}`}
                      className="rounded-[7px] border border-[#7c3aed]/30 bg-[#7c3aed]/10 px-[8px] py-[4px] text-[10px] font-semibold text-[#bba6ed] hover:bg-[#7c3aed]/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#7c3aed]"
                    >
                      Editar
                    </button> : null}
                  </td>
                ) : null}
              </tr>
            )) : null}
          </tbody>
        </table>
      </div>

      {loading || contactsLoading ? (
        <p role="status" className="border-t border-[var(--ag-divider)] px-[16px] py-[28px] text-center text-[11px] text-[var(--ag-text-muted)]">Cargando directorio…</p>
      ) : totalItems === 0 ? (
        <div className="border-t border-[var(--ag-divider)] px-[16px] py-[72px] text-center">
          <div aria-hidden="true" className="mx-auto mb-[10px] flex size-[42px] items-center justify-center rounded-[10px] bg-[#7c3aed]/10 text-[#a98aef]"><FolderIcon /></div>
          <p className="text-[12px] font-semibold text-[var(--ag-text)]">Esta carpeta está vacía</p>
          <p className="mt-[4px] text-[11px] text-[var(--ag-text-muted)]">Crea una subcarpeta o agrega contactos para empezar.</p>
        </div>
      ) : null}
    </section>
  );
}

function findTrail(branches: ContactBranch[], branchId: string): ContactBranch[] {
  for (const branch of branches) {
    if (branch.branchId === branchId) return [branch];
    const nested = findTrail(branch.children, branchId);
    if (nested.length) return [branch, ...nested];
  }
  return [];
}

function FolderIcon() {
  return <svg aria-hidden="true" viewBox="0 0 24 24" className="size-[18px] shrink-0 fill-none stroke-[#a98aef]" strokeWidth="1.7"><path d="M3.5 6.75h6l1.7 2h9.3v8.5a2 2 0 0 1-2 2h-15v-12.5Z"/><path d="M3.5 8.75v-2a2 2 0 0 1 2-2h3.2l1.8 2h8a2 2 0 0 1 2 2"/></svg>;
}

function ContactIcon() {
  return <span aria-hidden="true" className="flex size-[22px] shrink-0 items-center justify-center rounded-full bg-[#7c3aed]/15 text-[10px] font-bold text-[#b69bf3]">●</span>;
}

function StatusBadge({ label }: { label: string }) {
  return <span className="inline-flex rounded-full border border-[#7c3aed]/20 bg-[#7c3aed]/10 px-[7px] py-[3px] text-[9px] font-medium capitalize text-[#bba6ed]">{label}</span>;
}
