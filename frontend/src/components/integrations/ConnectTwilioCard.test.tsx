// @vitest-environment jsdom

import { render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, expect, test, vi } from "vitest";
import ConnectTwilioCard from "./ConnectTwilioCard";

afterEach(() => vi.restoreAllMocks());

test("shows the verified subaccount without exposing a token", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
    status: "connected",
    connections: [{ provider_account_id: "AC11111111111111111111111111111111", enabled_capabilities: ["twilio.sms.send"] }],
  }), { status: 200 })));
  render(<ConnectTwilioCard />);
  await waitFor(() => expect(screen.getByText("Connected")).toBeInTheDocument());
  expect(screen.getByText("AC11111111111111111111111111111111")).toBeInTheDocument();
  expect(screen.queryByLabelText("Auth token")).not.toBeInTheDocument();
});

test("disconnected form keeps the token in a password input", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: "disconnected", connections: [] }), { status: 200 })));
  render(<ConnectTwilioCard />);
  const token = await screen.findByLabelText("Auth token");
  expect(token).toHaveAttribute("type", "password");
  expect(token).toHaveAttribute("autocomplete", "off");
});
