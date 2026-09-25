// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ImportReview, { type ImportBatchView, type ImportRowView } from "./ImportReview";

const DIGITS = "600111222";

function row(overrides: Partial<ImportRowView> = {}): ImportRowView {
  return {
    importRowId: "importrow:01JBQ9YHY3W4M9K1Q7S2X8T5ZR",
    rowNumber: 1,
    channel: "sms",
    classification: "new",
    state: "staged",
    assertsConsent: false,
    consentPurposes: [],
    destination: {
      channel: "sms",
      text: "+34 ••• ••• 1222 · a1b2c3d4 · /acme/sales · never contacted",
      countryCode: "34",
      digitCount: 11,
      visibleTail: "1222",
      fingerprint: "a1b2c3d4",
      branchPath: "/acme/sales",
      lastContactedAt: null,
    },
    displayName: "Ana Pérez",
    ...overrides,
  };
}

function batch(overrides: Partial<ImportBatchView> = {}): ImportBatchView {
  return {
    batchId: "import:01JBQ9YHY3W4M9K1Q7S2X8T5ZQ",
    state: "staged",
    branchPath: "/acme/sales",
    sourceName: "feria-2026.csv",
    rowCount: 1,
    newCount: 1,
    duplicateCount: 0,
    collisionCount: 0,
    redacted: false,
    rows: [row()],
    ...overrides,
  };
}

describe("ImportReview", () => {
  afterEach(cleanup);

  it("says there is nothing to review rather than rendering an empty frame", () => {
    render(
      <ImportReview
        batch={null}
        actingPrincipalId="principal:manager"
        canApply
        onApplyBatch={vi.fn()}
        onDecideRow={vi.fn()}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent(
      "No hay ninguna importación esperando revisión.",
    );
  });

  it("shows what the scan concluded before anybody authorizes anything", () => {
    render(
      <ImportReview
        batch={batch({ rowCount: 12, newCount: 8, duplicateCount: 3, collisionCount: 1 })}
        actingPrincipalId="principal:manager"
        canApply
        onApplyBatch={vi.fn()}
        onDecideRow={vi.fn()}
      />,
    );

    expect(screen.getByTestId("count-new")).toHaveTextContent("8");
    expect(screen.getByTestId("count-duplicate")).toHaveTextContent("3");
    expect(screen.getByTestId("count-collision")).toHaveTextContent("1");
  });

  it("warns that rows without evidence will land unusable", () => {
    render(
      <ImportReview
        batch={batch()}
        actingPrincipalId="principal:manager"
        canApply
        onApplyBatch={vi.fn()}
        onDecideRow={vi.fn()}
      />,
    );

    expect(
      screen.getByText(
        "Ninguna fila trae evidencia de consentimiento: todas las direcciones quedarán inutilizables.",
      ),
    ).toBeVisible();
  });

  it("takes one decision for the whole batch and names who is taking it", () => {
    const onApplyBatch = vi.fn();
    render(
      <ImportReview
        batch={batch({ rowCount: 900, newCount: 880, duplicateCount: 20 })}
        actingPrincipalId="principal:manager"
        canApply
        onApplyBatch={onApplyBatch}
        onDecideRow={vi.fn()}
      />,
    );

    // A thousand rows cannot ask for a thousand clicks -- but the one click
    // has to be attributable, or a bulk mistake has no owner.
    const button = screen.getByRole("button", { name: /Autorizar 900 filas como principal:manager/ });
    fireEvent.change(screen.getByLabelText("Motivo"), { target: { value: "alta de feria" } });
    fireEvent.click(button);

    expect(onApplyBatch).toHaveBeenCalledWith(batch().batchId, "alta de feria");
  });

  it("closes the batch decision to a reviewer without edit authority", () => {
    const onApplyBatch = vi.fn();
    render(
      <ImportReview
        batch={batch()}
        actingPrincipalId="principal:operator"
        canApply={false}
        onApplyBatch={onApplyBatch}
        onDecideRow={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: /Autorizar/ })).toBeDisabled();
    expect(
      screen.getByText(
        "No tienes autoridad de edición sobre esta rama, así que no puedes autorizar esta importación.",
      ),
    ).toBeVisible();
    expect(onApplyBatch).not.toHaveBeenCalled();
  });

  it("will not let an applied batch be authorized a second time", () => {
    render(
      <ImportReview
        batch={batch({ state: "applied" })}
        actingPrincipalId="principal:manager"
        canApply
        onApplyBatch={vi.fn()}
        onDecideRow={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: /Autorizar/ })).toBeDisabled();
  });

  it("masks every destination and never renders the digits", () => {
    render(
      <ImportReview
        batch={batch({
          redacted: true,
          rows: [row({ displayName: undefined, redacted: true })],
        })}
        actingPrincipalId="principal:operator"
        canApply={false}
        onApplyBatch={vi.fn()}
        onDecideRow={vi.fn()}
      />,
    );

    expect(document.body.textContent).not.toContain(DIGITS);
    expect(document.body.textContent).not.toContain("Ana Pérez");
    expect(screen.getByTestId("masked-destination")).toHaveTextContent("a1b2c3d4");
    expect(screen.getByText("Identidad reservada")).toBeVisible();
  });

  it("keeps collisions out of the batch and answers them one at a time", () => {
    const onDecideRow = vi.fn();
    render(
      <ImportReview
        batch={batch({
          rowCount: 2,
          newCount: 1,
          collisionCount: 1,
          rows: [row(), row({ importRowId: "importrow:2", rowNumber: 2, classification: "collision" })],
        })}
        actingPrincipalId="principal:manager"
        canApply
        onApplyBatch={vi.fn()}
        onDecideRow={onDecideRow}
      />,
    );

    // The batch button covers the new and duplicate rows only.
    expect(screen.getByRole("button", { name: /Autorizar 1 filas/ })).toBeEnabled();
    expect(
      screen.getByText("Las colisiones no entran en la decisión por lote: se resuelven una a una."),
    ).toBeVisible();

    const collision = screen.getByLabelText("Fila 2");
    fireEvent.click(within(collision).getByRole("button", { name: "Es la misma persona" }));

    expect(onDecideRow).toHaveBeenCalledWith("importrow:2", "link", "misma persona");
  });

  it("will not let a reviewer link a collision in a branch they cannot edit", () => {
    const onDecideRow = vi.fn();
    render(
      <ImportReview
        batch={batch({
          collisionCount: 1,
          rows: [row({ classification: "collision", mayLink: false })],
        })}
        actingPrincipalId="principal:manager"
        canApply
        onApplyBatch={vi.fn()}
        onDecideRow={onDecideRow}
      />,
    );

    // "That is the same person" is an assertion about a record living
    // somewhere this reviewer has no authority. Rejecting it still is theirs.
    expect(screen.getByRole("button", { name: "Es la misma persona" })).toBeDisabled();
    expect(
      screen.getByText("No puedes vincularla: esa persona vive en una rama que no editas."),
    ).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Descartar la fila" }));

    expect(onDecideRow).toHaveBeenCalledWith(
      "importrow:01JBQ9YHY3W4M9K1Q7S2X8T5ZR",
      "reject",
      "rechazada en revisión",
    );
  });

  it("names the purposes a row claims so a reviewer knows what is being granted", () => {
    render(
      <ImportReview
        batch={batch({ rows: [row({ assertsConsent: true, consentPurposes: ["marketing"] })] })}
        actingPrincipalId="principal:manager"
        canApply
        onApplyBatch={vi.fn()}
        onDecideRow={vi.fn()}
      />,
    );

    expect(screen.getByText("Consentimiento con evidencia: marketing")).toBeVisible();
    expect(screen.getByText("1 de 1 filas traen evidencia; el resto quedará inutilizable.")).toBeVisible();
  });
});
