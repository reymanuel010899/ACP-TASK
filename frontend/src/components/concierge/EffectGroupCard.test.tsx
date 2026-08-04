// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import EffectGroupCard, { type EffectGroup } from "./EffectGroupCard";

function group(overrides: Partial<EffectGroup> = {}): EffectGroup {
  return {
    groupId: "group:1",
    summary: "0 of 2 completed",
    effects: [
      {
        effectId: "effect:1", capabilityId: "slack.reaction.add",
        summary: "add reaction #general", status: "awaiting_approval",
        reinforced: false, allowedActions: ["approve", "reject"],
        detailsExpanded: false,
      },
      {
        effectId: "effect:2", capabilityId: "slack.channel.archive",
        summary: "archive #ideas", status: "awaiting_approval",
        reinforced: true, allowedActions: ["approve", "reject"],
        detailsExpanded: true,
      },
    ],
    ...overrides,
  };
}

describe("EffectGroupCard", () => {
  afterEach(cleanup);

  it("answers one effect at a time", () => {
    const onDecide = vi.fn();
    render(<EffectGroupCard group={group()} onDecide={onDecide} />);

    const rows = screen.getAllByRole("listitem");
    fireEvent.click(within(rows[0]).getByRole("button", { name: "Approve" }));

    // Approving one must never carry the other.
    expect(onDecide).toHaveBeenCalledTimes(1);
    expect(onDecide).toHaveBeenCalledWith("effect:1", "approve");
  });

  it("opens details by default only where approval is reinforced", () => {
    render(<EffectGroupCard group={group()} onDecide={vi.fn()} />);

    const [ordinary, reinforced] = screen.getAllByRole("button", { name: /details/ });
    expect(ordinary).toHaveAttribute("aria-expanded", "false");
    expect(reinforced).toHaveAttribute("aria-expanded", "true");
    // The reinforced row says why it is different, in words.
    expect(screen.getByText(/needs you present/)).toBeInTheDocument();
  });

  it("lets a person open details on an ordinary effect", () => {
    render(<EffectGroupCard group={group()} onDecide={vi.fn()} />);

    const [ordinary] = screen.getAllByRole("button", { name: "Show details" });
    fireEvent.click(ordinary);

    expect(screen.getByText("slack.reaction.add")).toBeInTheDocument();
  });

  it("reports a mixed outcome without a verdict", () => {
    render(
      <EffectGroupCard
        group={group({
          summary: "1 of 2 completed",
          effects: [
            { effectId: "effect:1", capabilityId: "slack.message.send", summary: "send #general", status: "succeeded", reinforced: false, allowedActions: [], detailsExpanded: false },
            { effectId: "effect:2", capabilityId: "slack.reaction.add", summary: "add reaction", status: "failed", reinforced: false, allowedActions: [], detailsExpanded: false, recovery: "retry_safe" },
          ],
        })}
        onDecide={vi.fn()}
      />,
    );

    expect(screen.getByText("1 of 2 completed")).toBeInTheDocument();
    expect(screen.getByText("Done")).toBeInTheDocument();
    expect(screen.getByText("Failed")).toBeInTheDocument();
    // A finished effect offers no action, so nobody can approve what already ran.
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });

  it("offers no action on an effect still waiting on an earlier one", () => {
    render(
      <EffectGroupCard
        group={group({
          effects: [
            { effectId: "effect:1", capabilityId: "slack.conversation.read", summary: "read #general", status: "awaiting_approval", reinforced: false, allowedActions: ["approve", "reject"], detailsExpanded: false },
            { effectId: "effect:2", capabilityId: "slack.message.send", summary: "send #general", status: "blocked", reinforced: false, allowedActions: [], detailsExpanded: false },
          ],
        })}
        onDecide={vi.fn()}
      />,
    );

    // Approving a derived write before its read has run would approve content
    // nobody has seen.
    expect(screen.getAllByRole("button", { name: "Approve" })).toHaveLength(1);
    expect(screen.getByText("Waiting on an earlier step")).toBeInTheDocument();
  });

  it("announces the summary only when it actually changes", () => {
    const { rerender } = render(<EffectGroupCard group={group()} onDecide={vi.fn()} />);
    const live = screen.getByText("0 of 2 completed");
    expect(live).toHaveAttribute("aria-live", "polite");

    rerender(<EffectGroupCard group={group()} onDecide={vi.fn()} />);
    expect(screen.getByText("0 of 2 completed")).toBeInTheDocument();

    rerender(<EffectGroupCard group={group({ summary: "1 of 2 completed" })} onDecide={vi.fn()} />);
    expect(screen.getByText("1 of 2 completed")).toBeInTheDocument();
  });
});
