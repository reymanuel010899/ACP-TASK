"use client";

import { useCallback, useEffect, useState } from "react";
import { readStoredCsrfToken as csrfToken } from "@/lib/agentSession";

// ConnectSlackCard asks for a whole capability array at once and only reports
// which families are missing scopes. This control is the other half: it
// changes state. Each family is a separate request, because "disable direct
// messages" must not be able to take anything else down with it.

type Family = {
  family: string;
  enabled: boolean;
};

type Sender = {
  sender_id: string;
  enabled: boolean;
};

type EffectCounts = {
  dispatched?: number;
  prevented?: number;
  in_progress?: number;
  uncertain?: number;
  failed?: number;
};

type ControlPlane = {
  emergency_stop?: boolean;
  stop_reason?: string | null;
  families?: Family[];
  senders?: Sender[];
  effects?: EffectCounts | null;
};

// What each family lets Tessera do, in the user's words. The families
// themselves come from the server; only the phrasing lives here.
const FAMILY_LABELS: Record<string, string> = {
  slack_connection_status: "check the connection",
  slack_channel_discovery: "find channels",
  slack_conversation_reads: "read conversations",
  slack_private_reads: "read private channels",
  slack_user_discovery: "find people",
  slack_messaging: "post messages and replies",
  slack_direct_messages: "send direct messages",
  slack_reactions: "add and remove reactions",
  slack_pins: "pin and unpin messages",
  slack_bookmarks: "bookmark links",
  slack_search: "search messages",
  slack_channel_management: "manage channels",
};

function familyLabel(family: string) {
  return FAMILY_LABELS[family] ?? family.replace(/^slack_/, "").replace(/_/g, " ");
}

const COUNT_LABELS: [keyof EffectCounts, string][] = [
  ["dispatched", "Dispatched"],
  ["prevented", "Prevented"],
  ["in_progress", "In progress"],
  ["uncertain", "Uncertain"],
];

export default function CapabilityFamilyControls() {
  const [state, setState] = useState<ControlPlane | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [message, setMessage] = useState("Loading your capability controls…");

  const load = useCallback(async () => {
    setLoading(true);
    setFailed(false);
    try {
      const response = await fetch("/api/integrations/control-plane", {
        credentials: "same-origin",
        cache: "no-store",
      });
      if (!response.ok) throw new Error("control plane unavailable");
      const data = (await response.json()) as ControlPlane;
      setState(data);
      setMessage(
        data.emergency_stop
          ? "Everything is stopped for this account. Nothing new will be sent."
          : "Each capability can be turned on or off on its own.",
      );
    } catch {
      setFailed(true);
      setState(null);
      // Fail closed in what we say, too: an unreadable control plane is not a
      // permissive one, and the page must not imply that anything is running.
      setMessage("We could not read your capability controls, so we cannot say what is on.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    queueMicrotask(() => void load());
  }, [load]);

  async function decide(body: Record<string, unknown>, key: string, note: string) {
    const csrf = csrfToken();
    if (!csrf) {
      setFailed(true);
      setMessage("Your secure session needs to be refreshed. Sign in again, then retry.");
      return;
    }
    setBusy(key);
    try {
      const response = await fetch("/api/integrations/control-plane", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
        body: JSON.stringify(body),
      });
      if (!response.ok) throw new Error("change rejected");
      // The response is the whole state after the change, so what is shown is
      // what the server will actually enforce, not what we hoped it would.
      setState((await response.json()) as ControlPlane);
      setFailed(false);
      setMessage(note);
    } catch {
      setFailed(true);
      setMessage("We could not change that. Nothing was switched.");
      await load();
    } finally {
      setBusy(null);
    }
  }

  const stopped = state?.emergency_stop === true;
  const families = state?.families ?? [];
  const senders = state?.senders ?? [];
  const effects = state?.effects ?? null;

  return (
    <section
      aria-labelledby="capability-family-controls-title"
      className="box-border flex h-full w-full flex-col gap-[10px] rounded-[8px] border border-[var(--ag-card-border)] bg-[var(--ag-card)] p-[13px]"
    >
      <div className="min-w-0">
        <h2 id="capability-family-controls-title" className="text-[12px] font-semibold text-[var(--ag-text)]">
          Capability controls
        </h2>
        <p className="text-[9px] text-[var(--ag-text-secondary)]">
          Applies to this account only, and takes effect immediately.
        </p>
      </div>

      <div role="group" aria-label="Emergency stop" className="rounded-[7px] border border-[#7F1D1D] p-[8px]">
        <p className="text-[10px] text-[var(--ag-text)]">
          {stopped
            ? "This account is stopped. Nothing new is sent, and messages already in flight still finish reporting back."
            : "Stop everything for this account, including incoming requests."}
        </p>
        {stopped && state?.stop_reason && (
          <p className="mt-1 text-[9px] text-[var(--ag-text-secondary)]">Reason: {state.stop_reason}</p>
        )}
        <button
          type="button"
          disabled={loading || busy !== null || failed}
          onClick={() =>
            void decide(
              { action: "emergency_stop", enabled: !stopped },
              "emergency_stop",
              stopped
                ? "This account is running again. Work that was held is being released."
                : "This account is stopped. Nothing new will be sent.",
            )
          }
          className="mt-2 rounded border border-[#7F1D1D] px-2 py-1 text-[9px] text-[#FCA5A5] disabled:opacity-50"
        >
          {stopped ? "Resume this account" : "Stop everything"}
        </button>
        {effects && (
          <dl className="mt-2 grid grid-cols-2 gap-1" aria-label="Effect counts">
            {COUNT_LABELS.map(([key, label]) => (
              <div key={key} className="flex items-center justify-between gap-2">
                <dt className="text-[9px] text-[var(--ag-text-secondary)]">{label}</dt>
                <dd className="text-[9px] font-semibold text-[var(--ag-text)]">{effects[key] ?? 0}</dd>
              </div>
            ))}
          </dl>
        )}
      </div>

      <ul className="space-y-[6px]">
        {families.map((family) => (
          <li key={family.family} className="flex items-center justify-between gap-2">
            <span className="truncate text-[10px] text-[var(--ag-text)]">
              {familyLabel(family.family)}
              <span className="ml-1 text-[9px] text-[var(--ag-text-secondary)]">
                {family.enabled ? "on" : "off"}
              </span>
            </span>
            <button
              type="button"
              disabled={busy !== null || failed}
              aria-pressed={family.enabled}
              onClick={() =>
                void decide(
                  { action: "family", family: family.family, enabled: !family.enabled },
                  family.family,
                  family.enabled
                    ? `Tessera will no longer ${familyLabel(family.family)}.`
                    : `Tessera can now ${familyLabel(family.family)}.`,
                )
              }
              className="shrink-0 rounded border border-[var(--ag-card-border)] px-2 py-1 text-[9px] text-[var(--ag-text)] disabled:opacity-50"
            >
              {family.enabled ? `Turn off ${familyLabel(family.family)}` : `Turn on ${familyLabel(family.family)}`}
            </button>
          </li>
        ))}
      </ul>

      {senders.length > 0 && (
        <ul aria-label="Senders" className="space-y-[6px]">
          {senders.map((sender) => (
            <li key={sender.sender_id} className="flex items-center justify-between gap-2">
              <span className="truncate text-[10px] text-[var(--ag-text)]">{sender.sender_id}</span>
              <button
                type="button"
                disabled={busy !== null || failed}
                aria-pressed={sender.enabled}
                onClick={() =>
                  void decide(
                    { action: "sender", sender_id: sender.sender_id, enabled: !sender.enabled },
                    sender.sender_id,
                    sender.enabled
                      ? `${sender.sender_id} will no longer send.`
                      : `${sender.sender_id} can send again.`,
                  )
                }
                className="shrink-0 rounded border border-[var(--ag-card-border)] px-2 py-1 text-[9px] text-[var(--ag-text)] disabled:opacity-50"
              >
                {sender.enabled ? `Disable ${sender.sender_id}` : `Enable ${sender.sender_id}`}
              </button>
            </li>
          ))}
        </ul>
      )}

      <p
        role={failed ? "alert" : "status"}
        aria-live={failed ? "assertive" : "polite"}
        className="mt-auto text-[9px]/[13px] text-[var(--ag-text-secondary)]"
      >
        {message}
      </p>
    </section>
  );
}
