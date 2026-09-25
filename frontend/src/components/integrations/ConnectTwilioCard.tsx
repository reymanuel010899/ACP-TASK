"use client";

import { FormEvent, useEffect, useState } from "react";
import { readStoredCsrfToken } from "@/lib/agentSession";

type State = { status?: string; connections?: { provider_account_id?: string; enabled_capabilities?: string[] }[]; error?: string };

export default function ConnectTwilioCard() {
  const [state, setState] = useState<State>({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("Loading Twilio connection status…");

  async function load() {
    setLoading(true);
    try {
      const response = await fetch("/api/integrations/twilio", { credentials: "same-origin", cache: "no-store" });
      const data = (await response.json()) as State;
      if (!response.ok) throw new Error();
      setState(data);
      setMessage(data.status === "connected" ? "Twilio is connected." : "Connect an existing Twilio subaccount.");
    } catch {
      setMessage("We could not load Twilio connection status.");
    } finally { setLoading(false); }
  }

  useEffect(() => { queueMicrotask(() => void load()); }, []);

  async function connect(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const csrf = readStoredCsrfToken();
    if (!csrf) { setMessage("Refresh your secure session, then retry."); return; }
    const form = new FormData(event.currentTarget);
    setBusy(true);
    try {
      const response = await fetch("/api/integrations/twilio", {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
        body: JSON.stringify({ account_id: form.get("account_id"), auth_token: form.get("auth_token") }),
      });
      const data = (await response.json()) as State;
      if (!response.ok) {
        setMessage(data.error || "Twilio could not be verified. Nothing was connected.");
        return;
      }
      event.currentTarget.reset();
      await load();
    } catch {
      setMessage("Twilio could not be verified. Nothing was connected.");
    } finally { setBusy(false); }
  }

  const connected = state.status === "connected";
  const connection = state.connections?.[0];
  return (
    <section aria-labelledby="twilio-integration-title" className="box-border flex h-full w-full flex-col gap-[10px] rounded-[8px] border border-[var(--ag-card-border)] bg-[var(--ag-card)] p-[13px]">
      <div className="flex items-center gap-[9px]">
        <div aria-hidden="true" className="flex h-[34px] w-[34px] items-center justify-center rounded-[8px] border border-[var(--ag-card-border)] text-[15px] font-bold text-[#F22F46]">◉</div>
        <div><h2 id="twilio-integration-title" className="text-[12px] font-semibold text-[var(--ag-text)]">Twilio</h2><p className="text-[9px] text-[var(--ag-text-secondary)]">Communication</p></div>
      </div>
      <div className={`w-fit rounded-[4px] px-[8px] py-[3px] text-[9px] font-semibold ${connected ? "bg-[#0B3B2B] text-[#22C55E]" : "bg-[var(--ag-input-bg)] text-[var(--ag-text-secondary)]"}`}>{connected ? "Connected" : "Not connected"}</div>
      {connected ? (
        <div className="text-[10px]/[15px] text-[var(--ag-text-secondary)]">
          <p>{connection?.provider_account_id}</p>
          <p>{connection?.enabled_capabilities?.join(", ") || "No family enabled yet"}</p>
        </div>
      ) : (
        <form onSubmit={connect} className="space-y-2">
          <label className="block text-[9px] text-[var(--ag-text-secondary)]">Subaccount SID<input required name="account_id" pattern="AC[0-9a-fA-F]{32}" className="mt-1 w-full rounded border border-[var(--ag-card-border)] bg-[var(--ag-input-bg)] p-2 text-[10px] text-[var(--ag-text)]" /></label>
          <label className="block text-[9px] text-[var(--ag-text-secondary)]">Auth token<input required type="password" autoComplete="off" name="auth_token" className="mt-1 w-full rounded border border-[var(--ag-card-border)] bg-[var(--ag-input-bg)] p-2 text-[10px] text-[var(--ag-text)]" /></label>
          <button disabled={busy || loading} className="rounded-[6px] bg-[var(--ag-purple)] px-4 py-2 text-[10px] font-semibold text-white disabled:opacity-50">Verify and connect</button>
        </form>
      )}
      <p role="status" className="mt-auto text-[9px]/[13px] text-[var(--ag-text-secondary)]">{message}</p>
    </section>
  );
}
