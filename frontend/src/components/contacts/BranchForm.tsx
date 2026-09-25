"use client";

import { useState } from "react";

export type BranchFormProps = {
  parentBranchId?: string | null;
  hasBranches: boolean;
  busy?: boolean;
  onCreate: (input: { name: string; kind: "organization" | "folder"; parentBranchId?: string }) => void | Promise<void>;
};

export default function BranchForm({ parentBranchId, hasBranches, busy = false, onCreate }: BranchFormProps) {
  const [name, setName] = useState("");
  const nested = hasBranches;

  async function submit() {
    const trimmed = name.trim();
    if (!trimmed) return;
    await onCreate({
      name: trimmed,
      kind: nested ? "folder" : "organization",
      ...(nested && parentBranchId ? { parentBranchId } : {}),
    });
    setName("");
  }

  return (
    <form
      aria-label="Nueva rama"
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
      className="mt-[10px] flex flex-col gap-[6px] rounded-[8px] border border-[var(--ag-card-border)] bg-[var(--ag-card)] p-[10px]"
    >
      <label className="flex flex-col gap-[2px] text-[10px] text-[var(--ag-text-muted)]">
        {nested ? "Nombre de la subrama" : "Nombre de la organización"}
        <input
          value={name}
          maxLength={120}
          onChange={(event) => setName(event.target.value)}
          className="rounded border border-[var(--ag2-border)] bg-[var(--ag2-input)] px-[6px] py-[4px] text-[11px] text-[var(--ag-text)]"
        />
      </label>
      {nested && !parentBranchId ? (
        <p className="text-[10px] text-[var(--ag-orange)]">Selecciona primero la rama que será su carpeta superior.</p>
      ) : null}
      <button
        type="submit"
        disabled={busy || !name.trim() || (nested && !parentBranchId)}
        className="w-fit rounded-[8px] bg-[#5D20DC] px-[10px] py-[5px] text-[10px] font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40"
      >
        {busy ? "Creando…" : nested ? "Crear subrama" : "Crear rama inicial"}
      </button>
    </form>
  );
}
