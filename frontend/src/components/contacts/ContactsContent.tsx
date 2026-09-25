"use client";

import { useCallback, useEffect, useState } from "react";
import { readStoredCsrfToken } from "@/lib/agentSession";

import BranchForm from "./BranchForm";
import ContactForm, { type ContactFormSubmission } from "./ContactForm";
import ContactsDirectory from "./ContactsDirectory";
import type { ContactTableItem } from "./ContactsTable";
import type { ContactBranch } from "./ContactsTree";

export type ContactsContentProps = {
  branches?: ContactBranch[];
};

export default function ContactsContent({ branches }: ContactsContentProps) {
  const remote = branches === undefined;
  const [loadedBranches, setLoadedBranches] = useState<ContactBranch[]>(branches ?? []);
  const [selectedBranchId, setSelectedBranchId] = useState<string | null>(null);
  const [loading, setLoading] = useState(remote);
  const [busy, setBusy] = useState(false);
  const [showBranchForm, setShowBranchForm] = useState(false);
  const [showContactForm, setShowContactForm] = useState(false);
  const [editingContact, setEditingContact] = useState<ContactTableItem | null>(null);
  const [directoryMessage, setDirectoryMessage] = useState("");
  const [directoryAccessDenied, setDirectoryAccessDenied] = useState(false);
  const [contacts, setContacts] = useState<ContactTableItem[]>([]);
  const [contactsLoading, setContactsLoading] = useState(false);
  const [contactsError, setContactsError] = useState("");
  const [contactFormError, setContactFormError] = useState("");

  const loadBranches = useCallback(async () => {
    if (!remote) return;
    setLoading(true);
    try {
      const response = await fetch("/api/contacts/branches", { credentials: "same-origin", cache: "no-store" });
      const payload = (await response.json()) as { branches?: ContactBranch[]; error?: string };
      if (!response.ok) {
        setDirectoryAccessDenied(response.status === 403);
        throw new Error(payload.error ?? "directory unavailable");
      }
      setLoadedBranches(payload.branches ?? []);
      setDirectoryAccessDenied(false);
      setDirectoryMessage("");
    } catch (error) {
      setDirectoryMessage(
        error instanceof Error && error.message === "directory access is required"
          ? "Tu usuario todavía no tiene acceso al directorio de esta organización."
          : "No pudimos cargar el directorio de esta cuenta.",
      );
    } finally {
      setLoading(false);
    }
  }, [remote]);

  useEffect(() => {
    queueMicrotask(() => void loadBranches());
  }, [loadBranches]);

  useEffect(() => {
    if (!showContactForm) return;
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape" && !busy) {
        setShowContactForm(false);
        setEditingContact(null);
      }
    }
    document.addEventListener("keydown", closeOnEscape);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", closeOnEscape);
      document.body.style.overflow = previousOverflow;
    };
  }, [showContactForm, busy]);

  useEffect(() => {
    if (!remote || !selectedBranchId) return;
    let cancelled = false;
    queueMicrotask(() => {
      if (cancelled) return;
      setContactsLoading(true);
      setContactsError("");
      void fetch(`/api/contacts?branchId=${encodeURIComponent(selectedBranchId)}`, { credentials: "same-origin", cache: "no-store" })
        .then(async (response) => {
          const payload = (await response.json()) as { contacts?: ContactTableItem[]; error?: string };
          if (!response.ok) throw new Error(payload.error ?? "No pudimos cargar los contactos.");
          if (!cancelled) setContacts(payload.contacts ?? []);
        })
        .catch((error: unknown) => {
          if (!cancelled) {
            setContacts([]);
            setContactsError(error instanceof Error ? error.message : "No pudimos cargar los contactos.");
          }
        })
        .finally(() => {
          if (!cancelled) setContactsLoading(false);
        });
    });
    return () => { cancelled = true; };
  }, [remote, selectedBranchId]);

  const visibleBranches = remote ? loadedBranches : (branches ?? []);
  const canCreate = !directoryAccessDenied && (visibleBranches.length === 0 || selectedBranchId !== null);

  function navigate(branchId: string | null) {
    setSelectedBranchId(branchId);
    setContacts([]);
    setContactsError("");
    setShowBranchForm(false);
    setShowContactForm(false);
    setEditingContact(null);
  }

  async function saveContact(submission: ContactFormSubmission) {
    setContactFormError("");
    const csrf = readStoredCsrfToken();
    if (!csrf) {
      setDirectoryMessage("Tu sesión segura debe renovarse. Inicia sesión de nuevo.");
      return;
    }
    setBusy(true);
    try {
      const editing = Boolean(submission.contactId && submission.recordVersion);
      const response = await fetch(
        editing ? `/api/contacts/${encodeURIComponent(submission.contactId!)}` : "/api/contacts",
        {
        method: editing ? "PATCH" : "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
        body: JSON.stringify(submission),
      });
      const payload = (await response.json()) as { error?: string };
      if (!response.ok) {
        if (response.status === 409) {
          await refreshContacts(submission.branchId);
          setShowContactForm(false);
          setEditingContact(null);
          setDirectoryMessage(payload.error ?? "El contacto cambió. Ábrelo de nuevo para editar la versión actual.");
          return;
        }
        throw new Error(payload.error ?? (editing ? "No pudimos guardar el contacto." : "No pudimos crear el contacto."));
      }
      await refreshContacts(submission.branchId);
      setDirectoryMessage(editing ? "Contacto actualizado correctamente." : "Contacto creado correctamente.");
      setShowContactForm(false);
      setEditingContact(null);
    } catch (error) {
      setContactFormError(error instanceof Error ? error.message : "No pudimos guardar el contacto.");
    } finally {
      setBusy(false);
    }
  }

  async function refreshContacts(branchId: string) {
      const refreshed = await fetch(
        `/api/contacts?branchId=${encodeURIComponent(branchId)}`,
        { credentials: "same-origin", cache: "no-store" },
      );
      const refreshedPayload = (await refreshed.json()) as { contacts?: ContactTableItem[]; error?: string };
      if (!refreshed.ok) throw new Error(refreshedPayload.error ?? "El contacto se guardó, pero no pudimos actualizar la lista.");
      setContacts(refreshedPayload.contacts ?? []);
  }

  async function createBranch(input: { name: string; kind: "organization" | "folder"; parentBranchId?: string }) {
    const csrf = readStoredCsrfToken();
    if (!csrf) {
      setDirectoryMessage("Tu sesión segura debe renovarse. Inicia sesión de nuevo.");
      return;
    }
    setBusy(true);
    try {
      const response = await fetch("/api/contacts/branches", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
        body: JSON.stringify(input),
      });
      const payload = (await response.json()) as { branch?: { branchId: string }; error?: string };
      if (!response.ok) throw new Error(payload.error ?? "No pudimos crear la carpeta.");
      setDirectoryMessage("Carpeta creada correctamente.");
      setSelectedBranchId(payload.branch?.branchId ?? selectedBranchId);
      setShowBranchForm(false);
      await loadBranches();
    } catch (error) {
      setDirectoryMessage(error instanceof Error ? error.message : "No pudimos crear la carpeta.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="box-border flex w-full flex-col gap-[14px] p-[18px_20px_24px]">
      <header className="flex flex-wrap items-end justify-between gap-[12px]">
        <div>
          <h1 className="text-[24px] font-bold tracking-[-0.02em] text-[var(--ag-text)]">Contactos</h1>
          <p className="mt-[3px] text-[11px] text-[var(--ag-text-secondary)]">Organiza carpetas y contactos desde un solo directorio.</p>
        </div>
        {remote ? (
          <div className="flex flex-wrap gap-[8px]">
            <button
              type="button"
              disabled={!selectedBranchId}
              title={!selectedBranchId ? "Abre una carpeta para agregar un contacto" : undefined}
              onClick={() => { setEditingContact(null); setContactFormError(""); setShowContactForm(true); setShowBranchForm(false); }}
              className="rounded-[8px] border border-[var(--ag-card-border)] bg-[var(--ag-card)] px-[12px] py-[7px] text-[11px] font-semibold text-[var(--ag-text)] disabled:cursor-not-allowed disabled:opacity-40"
            >
              + Nuevo contacto
            </button>
            <button
            type="button"
            disabled={!canCreate}
            title={!canCreate ? "Abre una carpeta para crear una subcarpeta" : undefined}
            onClick={() => { setShowBranchForm((visible) => !visible); setShowContactForm(false); }}
            className="rounded-[8px] bg-[#5D20DC] px-[12px] py-[7px] text-[11px] font-semibold text-white shadow-[0_6px_18px_rgba(93,32,220,0.22)] hover:bg-[#6b2ce6] disabled:cursor-not-allowed disabled:opacity-40"
          >
            + Nueva carpeta
            </button>
          </div>
        ) : null}
      </header>

      {showBranchForm ? (
        <div className="max-w-[520px]">
          <BranchForm parentBranchId={selectedBranchId} hasBranches={visibleBranches.length > 0} busy={busy} onCreate={createBranch} />
        </div>
      ) : null}

      {showContactForm && selectedBranchId ? (
        <div
          className="fixed inset-0 z-[80] flex items-center justify-center bg-[rgba(4,3,12,0.72)] p-[18px] backdrop-blur-[2px]"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && !busy) {
              setShowContactForm(false);
              setEditingContact(null);
            }
          }}
        >
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="contact-form-title"
            className="flex max-h-[calc(100vh-36px)] w-full max-w-[680px] flex-col overflow-hidden rounded-[14px] border border-[var(--ag-card-border)] bg-[var(--ag-bg)] shadow-[0_28px_90px_rgba(0,0,0,0.55)]"
          >
            <header className="flex shrink-0 items-center justify-between border-b border-[var(--ag-divider)] px-[16px] py-[13px]">
              <div>
                <h2 id="contact-form-title" className="text-[14px] font-semibold text-[var(--ag-text)]">{editingContact ? "Editar contacto" : "Nuevo contacto"}</h2>
                <p className="mt-[2px] text-[10px] text-[var(--ag-text-muted)]">
                  {findBranchPath(visibleBranches, selectedBranchId) ?? "Carpeta seleccionada"}
                </p>
              </div>
              <button
                type="button"
                autoFocus
                disabled={busy}
                onClick={() => { setShowContactForm(false); setEditingContact(null); }}
                aria-label="Cerrar formulario de contacto"
                className="flex size-[30px] items-center justify-center rounded-[7px] text-[18px] text-[var(--ag-text-muted)] hover:bg-white/[0.06] hover:text-[var(--ag-text)] disabled:opacity-40"
              >
                ×
              </button>
            </header>
            <div className="min-h-0 overflow-y-auto p-[14px]">
              {contactFormError ? (
                <p role="alert" className="mb-[10px] rounded-[8px] border border-red-500/30 bg-red-500/10 px-[10px] py-[8px] text-[11px] text-red-300">
                  {contactFormError}
                </p>
              ) : null}
              <ContactForm
                key={editingContact?.contactId ?? "new-contact"}
                branches={[{
                  branchId: selectedBranchId,
                  path: findBranchPath(visibleBranches, selectedBranchId) ?? "Carpeta seleccionada",
                }]}
                initial={editingContact ? {
                  contactId: editingContact.contactId,
                  branchId: selectedBranchId,
                  recordVersion: editingContact.recordVersion,
                  displayName: editingContact.displayName,
                  givenName: editingContact.givenName ?? "",
                  familyName: editingContact.familyName ?? "",
                  companyName: editingContact.companyName ?? "",
                  jobTitle: editingContact.jobTitle ?? "",
                } : null}
                busy={busy}
                onSubmit={saveContact}
              />
            </div>
          </section>
        </div>
      ) : null}

      {directoryMessage ? <p role="status" className="text-[10px] text-[var(--ag-orange)]">{directoryMessage}</p> : null}

      <ContactsDirectory
        branches={visibleBranches}
        currentBranchId={selectedBranchId}
        contacts={contacts}
        loading={loading}
        contactsLoading={contactsLoading}
        error={contactsError}
        onNavigate={navigate}
        onEditContact={(contact) => {
          setContactFormError("");
          setEditingContact(contact);
          setShowContactForm(true);
          setShowBranchForm(false);
        }}
      />
    </main>
  );
}

function findBranchPath(branches: ContactBranch[], branchId: string): string | null {
  for (const branch of branches) {
    if (branch.branchId === branchId) return branch.path;
    const nested = findBranchPath(branch.children, branchId);
    if (nested) return nested;
  }
  return null;
}
