"use client";

import type { ContactTableItem } from "./ContactsTable";

export default function ContactsTreeView({ contacts }: { contacts: ContactTableItem[] }) {
  if (contacts.length === 0) {
    return <p role="status" className="p-[12px] text-[11px] text-[var(--ag-text-muted)]">Esta rama todavía no contiene contactos.</p>;
  }
  return (
    <ul role="tree" aria-label="Contactos de la rama" className="flex flex-col py-[5px]">
      {contacts.map((contact, index) => (
        <li key={contact.contactId} role="treeitem" className="group relative flex min-h-[44px] items-center gap-[10px] px-[14px] py-[7px] hover:bg-[var(--ag2-input)]">
          <span className="relative flex h-[26px] w-[26px] shrink-0 items-center justify-center rounded-full bg-[var(--ag-chip)] text-[10px] font-semibold text-[var(--ag-text)]">
            {initials(contact.displayName)}
            {index < contacts.length - 1 ? <span aria-hidden="true" className="absolute left-1/2 top-[26px] h-[18px] w-px bg-[var(--ag-divider)]" /> : null}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-[11px] font-medium text-[var(--ag-text)]">{contact.displayName}</span>
            <span className="block truncate text-[10px] text-[var(--ag-text-muted)]">
              {[contact.companyName, contact.jobTitle].filter(Boolean).join(" · ") || "Sin empresa ni puesto"}
            </span>
          </span>
          <span className="rounded-full bg-[var(--ag-chip)] px-[7px] py-[3px] text-[9px] text-[var(--ag-text-secondary)]">{contact.status}</span>
        </li>
      ))}
    </ul>
  );
}

function initials(name: string) {
  return name.trim().split(/\s+/).slice(0, 2).map((part) => part[0]?.toUpperCase()).join("") || "?";
}
