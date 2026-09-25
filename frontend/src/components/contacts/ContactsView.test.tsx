// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import ContactsView from "./ContactsView";

afterEach(cleanup);

const CONTACTS = [{
  contactId: "contact:1",
  recordVersion: "version:1",
  displayName: "Rey Ferreras",
  companyName: "Tessera",
  jobTitle: "AI Engineer",
  status: "active",
  source: "manual",
}];

describe("ContactsView", () => {
  it("starts as a table and switches to the tree style", () => {
    render(<ContactsView contacts={CONTACTS} branchLabel="/general/clientes" />);

    expect(screen.getByRole("table")).toBeVisible();
    expect(screen.getByRole("button", { name: "Tabla" })).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(screen.getByRole("button", { name: "Árbol" }));

    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByRole("tree", { name: "Contactos de la rama" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Árbol" })).toHaveAttribute("aria-pressed", "true");
  });

  it("keeps the empty state when changing styles", () => {
    render(<ContactsView contacts={[]} branchLabel="/general" />);
    expect(screen.getByText("Esta rama todavía no contiene contactos.")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Árbol" }));
    expect(screen.getByText("Esta rama todavía no contiene contactos.")).toBeVisible();
  });
});
