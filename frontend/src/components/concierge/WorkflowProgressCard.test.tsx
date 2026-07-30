// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import WorkflowProgressCard from "./WorkflowProgressCard";
it("separates provider completion from verification", () => { render(<WorkflowProgressCard outcome="Entrevista" steps={[{ id: "1", label: "Crear evento", executionStatus: "completed", verificationStatus: "pending" }, { id: "2", label: "Responder", executionStatus: "execution_unknown", verificationStatus: "pending" }]} />); expect(screen.getByText(/Completado · verificando/)).toBeVisible(); expect(screen.getByText("Resultado por confirmar")).toBeVisible(); });
it("does not present failed verification as success", () => { render(<WorkflowProgressCard outcome="Entrevista" steps={[{ id: "1", label: "Correo", executionStatus: "completed", verificationStatus: "failed" }, { id: "2", label: "Evento", executionStatus: "completed", verificationStatus: "inconclusive" }]} />); expect(screen.getByText(/Completado · no verificado/)).toBeVisible(); expect(screen.getByText(/Completado · sin confirmar/)).toBeVisible(); });
it("shows filtered Slack channel output for completed public reads", () => {
  render(<WorkflowProgressCard outcome="Canales públicos" steps={[{
    id: "1", label: "slack.channels.list", executionStatus: "completed",
    verificationStatus: "not_required", output: { channels: [
      { id: "C1", name: "tessera-test", is_private: false },
      { id: "C2", name: "general", is_private: false },
    ] },
  }]} />);

  expect(screen.getByText("#tessera-test")).toBeVisible();
  expect(screen.getByText("#general")).toBeVisible();
});
