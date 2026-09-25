// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import SlackEvidenceCard from "./SlackEvidenceCard";

it("renders reviewed period, author/date, partial notice and safe source links", () => {
  render(<SlackEvidenceCard
    answer="María confirmó el lanzamiento."
    period={{ label: "24–30 julio" }}
    partial
    citations={[{
      citation_id: "one", permalink: "https://acme.slack.com/archives/C1/p1",
      author_label: "María", occurred_at: "30/07/2026 09:00",
    }]}
  />);
  expect(screen.getByText("Periodo revisado: 24–30 julio")).toBeVisible();
  expect(screen.getByText(/Resultados parciales/)).toBeVisible();
  const link = screen.getByRole("link", { name: /Abrir mensaje fuente de Slack de María/ });
  expect(link).toHaveAttribute("target", "_blank");
  expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
  expect(screen.getByText("30/07/2026 09:00")).toBeVisible();
});
