"use client";

// The contacts hierarchy, rendered from what the server chose to send.
//
// It shows structure and counts, never destinations. A branch a principal may
// not view is absent from the payload rather than greyed out here: a disabled
// row confirms the branch exists, which is most of what somebody probing the
// tree wants to learn. So this component has no notion of a hidden branch and
// cannot accidentally acquire one.

import { useState } from "react";

export type ContactBranch = {
  branchId: string;
  name: string;
  path: string;
  kind: string;
  depth: number;
  contactCount: number;
  children: ContactBranch[];
};

export type ContactsTreeProps = {
  branches: ContactBranch[];
  selectedBranchId?: string | null;
  // Selection carries the identifier, never the label (KTD21). A path is a
  // display string that two accounts can legitimately share.
  onSelectBranch?: (branchId: string) => void;
  emptyMessage?: string;
};

export default function ContactsTree({
  branches,
  selectedBranchId = null,
  onSelectBranch,
  emptyMessage = "No hay ramas visibles para ti.",
}: ContactsTreeProps) {
  if (branches.length === 0) {
    return (
      <p className="text-[11px] text-[var(--ag-text-muted)]" role="status">
        {emptyMessage}
      </p>
    );
  }
  return (
    <ul role="tree" aria-label="Estructura de contactos" className="flex flex-col gap-[2px]">
      {branches.map((branch) => (
        <BranchNode
          key={branch.branchId}
          branch={branch}
          selectedBranchId={selectedBranchId}
          onSelectBranch={onSelectBranch}
        />
      ))}
    </ul>
  );
}

function BranchNode({
  branch,
  selectedBranchId,
  onSelectBranch,
}: {
  branch: ContactBranch;
  selectedBranchId: string | null;
  onSelectBranch?: (branchId: string) => void;
}) {
  const [open, setOpen] = useState(branch.depth < 1);
  const hasChildren = branch.children.length > 0;
  const selected = branch.branchId === selectedBranchId;
  return (
    <li
      role="treeitem"
      aria-expanded={hasChildren ? open : undefined}
      aria-selected={selected}
      className="list-none"
    >
      <div className="flex items-center gap-[6px]" style={{ paddingLeft: `${branch.depth * 12}px` }}>
        {hasChildren ? (
          <button
            type="button"
            onClick={() => setOpen((value) => !value)}
            aria-label={open ? `Contraer ${branch.name}` : `Expandir ${branch.name}`}
            className="h-[16px] w-[16px] shrink-0 rounded text-[10px] leading-none text-[var(--ag-text-muted)] hover:text-[var(--ag-text)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--ag-purple)]"
          >
            {open ? "▾" : "▸"}
          </button>
        ) : (
          <span className="h-[16px] w-[16px] shrink-0" aria-hidden="true" />
        )}
        <button
          type="button"
          onClick={() => onSelectBranch?.(branch.branchId)}
          className={`flex min-w-0 flex-1 items-baseline gap-[8px] rounded px-[6px] py-[4px] text-left text-[11px] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--ag-purple)] ${selected ? "bg-[var(--ag-chip)] text-[var(--ag-text)]" : "text-[var(--ag-text-secondary)] hover:text-[var(--ag-text)]"}`}
        >
          <span className="min-w-0 truncate">{branch.name}</span>
          <span className="shrink-0 text-[10px] uppercase tracking-wide text-[var(--ag-text-muted)]">
            {branch.kind}
          </span>
          <span className="ml-auto shrink-0 text-[10px] text-[var(--ag-text-muted)]">
            {branch.contactCount}
          </span>
        </button>
      </div>
      {hasChildren && open ? (
        <ul role="group" className="flex flex-col gap-[2px]">
          {branch.children.map((child) => (
            <BranchNode
              key={child.branchId}
              branch={child}
              selectedBranchId={selectedBranchId}
              onSelectBranch={onSelectBranch}
            />
          ))}
        </ul>
      ) : null}
    </li>
  );
}
