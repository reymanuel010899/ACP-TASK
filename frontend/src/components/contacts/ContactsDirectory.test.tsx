// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ContactsDirectory from "./ContactsDirectory";
import type { ContactBranch } from "./ContactsTree";

afterEach(cleanup);

const branches: ContactBranch[] = [{
  branchId: "general",
  name: "General",
  path: "General",
  kind: "organization",
  depth: 0,
  contactCount: 1,
  children: [{
    branchId: "clients",
    name: "Clientes",
    path: "General / Clientes",
    kind: "folder",
    depth: 1,
    contactCount: 0,
    children: [],
  }],
}];

describe("ContactsDirectory", () => {
  it("lists root folders and opens them from the table", () => {
    const navigate = vi.fn();
    render(<ContactsDirectory branches={branches} currentBranchId={null} contacts={[]} onNavigate={navigate} />);

    const row = screen.getByRole("row", { name: /General/ });
    expect(within(row).getByText("Carpeta")).toBeVisible();
    expect(within(row).getByText("Organización")).toBeVisible();
    fireEvent.click(within(row).getByRole("button", { name: "Abrir carpeta General" }));
    expect(navigate).toHaveBeenCalledWith("general");
  });

  it("mixes subfolders and contacts in one directory table", () => {
    render(<ContactsDirectory
      branches={branches}
      currentBranchId="general"
      contacts={[{ contactId: "contact:1", displayName: "Rey Ferreras", companyName: "Tessera", status: "active", source: "manual", recordVersion: "version:1" }]}
      onNavigate={vi.fn()}
    />);

    expect(screen.getByRole("row", { name: /Clientes/ })).toBeVisible();
    const contactRow = screen.getByRole("row", { name: /Rey Ferreras/ });
    expect(within(contactRow).getByText("Contacto")).toBeVisible();
    expect(within(contactRow).getByText("Tessera")).toBeVisible();
    expect(screen.getByRole("button", { name: "General" })).toBeVisible();
  });

  it("opens the selected contact in edit mode", () => {
    const onEditContact = vi.fn();
    const contact = { contactId: "contact:1", displayName: "Rey Ferreras", companyName: "Tessera", status: "active", source: "manual", recordVersion: "version:1", canEdit: true };
    render(<ContactsDirectory branches={branches} currentBranchId="general" contacts={[contact]} onNavigate={vi.fn()} onEditContact={onEditContact} />);

    fireEvent.click(screen.getByRole("button", { name: "Editar Rey Ferreras" }));

    expect(onEditContact).toHaveBeenCalledWith(contact);
  });
});
