// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import ContactsTable from "./ContactsTable";

afterEach(cleanup);

describe("ContactsTable", () => {
  it("shows an explicit empty state", () => {
    render(<ContactsTable contacts={[]} />);
    expect(screen.getByText("Esta rama todavía no contiene contactos.")).toBeVisible();
    expect(screen.getByText("0 items")).toBeVisible();
  });

  it("renders the contacts in columns", () => {
    render(<ContactsTable contacts={[{
      contactId: "contact:1", displayName: "Rey Ferreras",
      recordVersion: "version:1",
      companyName: "Tessera", jobTitle: "AI Engineer",
      source: "manual", status: "active",
    }]} />);
    const row = screen.getByRole("row", { name: /Rey Ferreras/ });
    expect(within(row).getByText("Tessera")).toBeVisible();
    expect(within(row).getByText("AI Engineer")).toBeVisible();
    expect(within(row).getByText("active")).toBeVisible();
  });
});
