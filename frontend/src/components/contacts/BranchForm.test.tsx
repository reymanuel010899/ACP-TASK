// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import BranchForm from "./BranchForm";

afterEach(cleanup);

describe("BranchForm", () => {
  it("creates the first branch as an organization", () => {
    const onCreate = vi.fn();
    render(<BranchForm hasBranches={false} onCreate={onCreate} />);

    fireEvent.change(screen.getByLabelText("Nombre de la organización"), { target: { value: "General" } });
    fireEvent.click(screen.getByRole("button", { name: "Crear rama inicial" }));

    expect(onCreate).toHaveBeenCalledWith({ name: "General", kind: "organization" });
  });

  it("requires a selected parent before creating a subbranch", () => {
    render(<BranchForm hasBranches parentBranchId={null} onCreate={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("Nombre de la subrama"), { target: { value: "Clientes" } });

    expect(screen.getByRole("button", { name: "Crear subrama" })).toBeDisabled();
  });
});
