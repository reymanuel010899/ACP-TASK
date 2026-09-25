// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";
import * as matchers from "vitest-axe/matchers";


import EffectGroupCard, { type EffectGroup } from "./EffectGroupCard";

expect.extend(matchers);

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

describe("EffectGroupCard accessibility", () => {
  afterEach(cleanup);

  it("has no axe violations while effects await a decision", async () => {
    const { container } = render(<EffectGroupCard group={group()} onDecide={vi.fn()} />);

    expect(await axe(container)).toHaveNoViolations();
  });

  it("has no axe violations once outcomes are mixed", async () => {
    const { container } = render(
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

    expect(await axe(container)).toHaveNoViolations();
  });

  it("can be driven to a decision with the keyboard alone", async () => {
    const user = userEvent.setup();
    const onDecide = vi.fn();
    render(<EffectGroupCard group={group()} onDecide={onDecide} />);

    await user.tab();
    // Tab order follows the visual order, so the first effect answers first.
    expect(screen.getAllByRole("button", { name: "Approve" })[0]).toHaveFocus();
    await user.keyboard("{Enter}");

    expect(onDecide).toHaveBeenCalledWith("effect:1", "approve");
  });

  it("lets a keyboard user open and close details deterministically", async () => {
    const user = userEvent.setup();
    render(<EffectGroupCard group={group()} onDecide={vi.fn()} />);

    const toggle = screen.getAllByRole("button", { name: "Show details" })[0];
    toggle.focus();
    await user.keyboard("{Enter}");

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    // Focus stays on the control that was used, not on the revealed content.
    expect(toggle).toHaveFocus();
  });

  it("restores focus to the last control after a server re-render", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<EffectGroupCard group={group()} onDecide={vi.fn()} />);

    const approve = screen.getAllByRole("button", { name: "Approve" })[1];
    await user.click(approve);

    // The server answers with new state; focus must not jump to the top of a
    // card that re-rendered underneath the person.
    rerender(<EffectGroupCard group={group({ summary: "1 of 2 completed" })} onDecide={vi.fn()} />);

    expect(document.getElementById("effect:2-approve")).toHaveFocus();
  });

  it("introduces no motion that a reduced-motion preference must undo", () => {
    const { container } = render(<EffectGroupCard group={group()} onDecide={vi.fn()} />);

    // The card animates nothing. Asserting it keeps a later unconditional
    // transition or animation from shipping without a motion-reduce variant.
    const animated = container.querySelectorAll(
      "[class*='animate-'], [class*='transition-'], [class*='duration-']",
    );
    for (const element of animated) {
      expect(element.className).toMatch(/motion-reduce:/);
    }
  });

  it("associates every effect with its own details region", () => {
    render(<EffectGroupCard group={group()} onDecide={vi.fn()} />);

    for (const toggle of screen.getAllByRole("button", { name: /details/ })) {
      const controlled = toggle.getAttribute("aria-controls");
      expect(controlled).toBeTruthy();
      if (toggle.getAttribute("aria-expanded") === "true") {
        expect(document.getElementById(controlled!)).toBeInTheDocument();
      }
    }
  });
});
