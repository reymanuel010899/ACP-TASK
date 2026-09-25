// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import BranchPermissions, { explicitEffect } from "./BranchPermissions";

function props(overrides: Partial<Parameters<typeof BranchPermissions>[0]> = {}) {
  return {
    branchPath: "/acme/sales",
    subjectPrincipalId: "principal:operator",
    subjectEffective: { view: true, edit: false, administer: false, campaign_use: false },
    decisions: [],
    grantable: ["view", "edit", "administer", "campaign_use"],
    onDecide: vi.fn(),
    onRevoke: vi.fn(),
    ...overrides,
  };
}

describe("BranchPermissions", () => {
  afterEach(cleanup);

  it("renders the four dimensions separately and never as a role", () => {
    render(<BranchPermissions {...props()} />);

    for (const label of ["Ver", "Editar", "Administrar", "Usar en campañas"]) {
      expect(screen.getByLabelText(label)).toBeVisible();
    }
    expect(screen.queryByLabelText("Rol")).toBeNull();
  });

  it("distinguishes an inherited answer from one decided at this branch", () => {
    render(
      <BranchPermissions
        {...props({
          subjectEffective: { view: true, edit: true, administer: false, campaign_use: false },
          decisions: [
            { dimension: "edit", effect: "grant", principalId: "principal:operator" },
          ],
        })}
      />,
    );

    expect(screen.getByTestId("state-view")).toHaveTextContent("concedida · heredada");
    expect(screen.getByTestId("state-edit")).toHaveTextContent("concedida · decidida aquí (grant)");
  });

  it("cannot grant an authority the acting principal does not itself hold", () => {
    const onDecide = vi.fn();
    render(
      <BranchPermissions {...props({ grantable: ["view", "administer"], onDecide })} />,
    );

    // Handing out campaign-use you do not hold is privilege creation, not
    // delegation -- so the control is shut and the reason is said out loud.
    const campaign = screen.getByLabelText("Usar en campañas");
    const grant = within(campaign).getByRole("button", { name: "Conceder Usar en campañas" });
    expect(grant).toBeDisabled();
    expect(
      within(campaign).getByText("No puedes conceder una autoridad que tú no tienes en esta rama."),
    ).toBeVisible();

    fireEvent.click(grant);
    expect(onDecide).not.toHaveBeenCalled();

    // And the one it does hold is delegable, so this is a real gate rather
    // than a component that disables everything.
    fireEvent.click(within(screen.getByLabelText("Ver")).getByRole("button", { name: "Conceder Ver" }));
    expect(onDecide).toHaveBeenCalledWith("view", "grant");
  });

  it("lets a restriction through that the matching grant would be refused", () => {
    const onDecide = vi.fn();
    render(<BranchPermissions {...props({ grantable: ["administer"], onDecide })} />);

    // KTD13's asymmetry: closing a subtree needs less authority than the
    // permissive move that opened it.
    const campaign = screen.getByLabelText("Usar en campañas");
    expect(within(campaign).getByRole("button", { name: "Conceder Usar en campañas" })).toBeDisabled();

    fireEvent.click(within(campaign).getByRole("button", { name: "Restringir Usar en campañas" }));

    expect(onDecide).toHaveBeenCalledWith("campaign_use", "restrict");
  });

  it("offers to fall back to inheritance only where a decision was written here", () => {
    const onRevoke = vi.fn();
    render(
      <BranchPermissions
        {...props({
          decisions: [{ dimension: "edit", effect: "restrict", principalId: "principal:operator" }],
          onRevoke,
        })}
      />,
    );

    expect(
      within(screen.getByLabelText("Ver")).getByRole("button", { name: "Volver a heredar Ver" }),
    ).toBeDisabled();

    fireEvent.click(
      within(screen.getByLabelText("Editar")).getByRole("button", { name: "Volver a heredar Editar" }),
    );

    expect(onRevoke).toHaveBeenCalledWith("edit");
  });

  it("reads an explicit decision by principal and dimension, never by dimension alone", () => {
    const decisions = [
      { dimension: "view", effect: "grant" as const, principalId: "principal:other" },
      { dimension: "view", effect: "restrict" as const, principalId: "principal:operator" },
    ];

    // Two principals hold decisions on the same dimension at the same branch.
    // Matching on the dimension alone would show one of them the other's.
    expect(explicitEffect(decisions, "principal:operator", "view")).toBe("restrict");
    expect(explicitEffect(decisions, "principal:other", "view")).toBe("grant");
    expect(explicitEffect(decisions, "principal:nobody", "view")).toBeNull();
  });

  it("holds every control shut while a decision is in flight", () => {
    render(<BranchPermissions {...props({ busy: true })} />);

    for (const button of screen.getAllByRole("button")) {
      expect(button).toBeDisabled();
    }
  });
});
