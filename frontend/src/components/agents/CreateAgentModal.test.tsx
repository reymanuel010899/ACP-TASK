// @vitest-environment jsdom
//
// Create Agent modal (plan 2026-07-23-002, U5): defines a SPEC — no client-side
// keypair. Basics (name/version/template/pricing) → Capabilities → Review →
// posts to /api/agents → Success.
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import CreateAgentModal from "./CreateAgentModal";

// The modal reads the signed-in user (ownership); tests run outside the real
// SessionProvider, so serve a stable principal here.
vi.mock("@/lib/SessionProvider", () => ({
  useSession: () => ({ session: { principalId: "user-test-principal" }, isHydrated: true }),
}));

function fillName(name = "DevOps Agent") {
  fireEvent.change(screen.getByPlaceholderText("DevOps Agent"), { target: { value: name } });
}

function toCapabilities() {
  fillName();
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
}

function selectCapability(label = "Terraform Engineer") {
  fireEvent.click(screen.getByRole("checkbox", { name: label }));
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: "agt_1" }) }));
});

describe("CreateAgentModal (spec-based)", () => {
  it("renders nothing when closed", () => {
    const { container } = render(<CreateAgentModal open={false} onClose={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders Basics first with the stepper active and NO keypair", () => {
    render(<CreateAgentModal open onClose={vi.fn()} />);
    expect(screen.getByRole("heading", { name: "Basics" })).toBeInTheDocument();
    // no principal_id / keypair UI in the spec-based flow
    expect(screen.queryByText(/principal_id/i)).not.toBeInTheDocument();
    expect(document.querySelector('[aria-current="step"]')).toHaveTextContent("Basics");
  });

  it("blocks advancing with an empty name / bad version / bad pricing", () => {
    render(<CreateAgentModal open onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText("Name is required.")).toBeInTheDocument();
    fillName();
    fireEvent.change(screen.getByDisplayValue("0.1.0"), { target: { value: "abc" } });
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText(/Version must be semver/)).toBeInTheDocument();
  });

  it("flags min price above list price", () => {
    render(<CreateAgentModal open onClose={vi.fn()} />);
    fillName();
    // defaults: list = 6, min = 3. Raise min above list.
    fireEvent.change(screen.getByDisplayValue("3"), { target: { value: "9" } }); // min = 9 > list 6
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText(/Min price must not exceed/)).toBeInTheDocument();
  });

  it("advances to Capabilities and Back preserves the name", () => {
    render(<CreateAgentModal open onClose={vi.fn()} />);
    fillName("My Agent");
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByRole("heading", { name: "Capabilities" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(screen.getByDisplayValue("My Agent")).toBeInTheDocument();
  });

  it("Capabilities blocks until one is selected", () => {
    render(<CreateAgentModal open onClose={vi.fn()} />);
    toCapabilities();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText(/Select at least one capability/)).toBeInTheDocument();
    selectCapability();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByRole("heading", { name: "Review" })).toBeInTheDocument();
  });

  it("Create posts the spec to /api/agents and reaches Success + onCreated", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: "agt_1" }) });
    vi.stubGlobal("fetch", fetchMock);
    const onCreated = vi.fn();
    render(<CreateAgentModal open onClose={vi.fn()} onCreated={onCreated} />);
    toCapabilities();
    selectCapability();
    fireEvent.click(screen.getByRole("button", { name: "Next" })); // -> Review
    fireEvent.click(screen.getByRole("button", { name: "Create Agent" }));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Agent created" })).toBeInTheDocument());
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/agents");
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body.template).toBe("terraform-provider");
    expect(body.capabilities).toContain("terraform.generate");
    expect(body.name).toBe("DevOps Agent");
    expect(onCreated).toHaveBeenCalled();
  });

  it("shows an error and stays on Review when create fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 422, json: async () => ({ error: "unknown template" }) }));
    render(<CreateAgentModal open onClose={vi.fn()} />);
    toCapabilities();
    selectCapability();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    fireEvent.click(screen.getByRole("button", { name: "Create Agent" }));
    await waitFor(() => expect(screen.getByText(/unknown template/)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Create Agent" })).toBeInTheDocument();
  });

  it("Cancel and Escape close", () => {
    const onClose = vi.fn();
    render(<CreateAgentModal open onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});
