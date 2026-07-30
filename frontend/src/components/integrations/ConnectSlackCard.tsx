"use client";

import { useCallback, useEffect, useState } from "react";
import { WEB_SESSION_CSRF_STORAGE_KEY } from "@/lib/agentSession";
import SlackBrandIcon from "./SlackBrandIcon";

type SlackConnection = {
  connection_id: string;
  team_id: string;
  team_name?: string;
  enterprise_id?: string | null;
  bot_user_id?: string | null;
  status: "connected" | "degraded" | "disconnect_pending" | "rotation_uncertain";
  enabled_capabilities: string[];
  owner?: boolean;
};

type SlackResponse = {
  connections?: SlackConnection[];
  authorization_url?: string;
  status?: string;
  connection_id?: string;
};

const CAPABILITIES = [
  "slack.channels.list",
  "slack.conversation.read",
  "slack.thread.read",
  "slack.users.list",
  "slack.message.permalink",
  "slack.private_channels.list",
  "slack.private_conversation.read",
  "slack.private_thread.read",
  "slack.message.send",
  "slack.thread.reply",
  "slack.direct_message.send",
  "slack.reaction.add",
  "slack.file.upload",
];

export default function ConnectSlackCard({
  redirect = (url: string) => window.location.assign(url),
}: {
  redirect?: (url: string) => void;
}) {
  const [connections, setConnections] = useState<SlackConnection[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("Loading Slack workspaces…");
  const [failed, setFailed] = useState(false);

  const loadStatus = useCallback(async () => {
    setLoading(true);
    setFailed(false);
    try {
      const response = await fetch("/api/integrations/slack", {
        credentials: "same-origin",
        cache: "no-store",
      });
      if (!response.ok) throw new Error("status unavailable");
      const data = (await response.json()) as SlackResponse;
      const next = data.connections ?? [];
      setConnections(next);
      setMessage(next.length ? `${next.length} Slack workspace${next.length === 1 ? "" : "s"} connected.` : "Slack is not connected.");
    } catch {
      setFailed(true);
      setMessage("We could not load your Slack connection status.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const callback = new URLSearchParams(window.location.search).get("slack");
    if (callback === "denied" || callback === "callback-failed") {
      queueMicrotask(() => {
        setFailed(callback === "callback-failed");
        setMessage(callback === "denied" ? "Slack access was denied. Nothing was connected." : "We could not finish connecting Slack.");
        setLoading(false);
      });
      return;
    }
    queueMicrotask(() => void loadStatus());
  }, [loadStatus]);

  function csrfToken() {
    try {
      return window.sessionStorage.getItem(WEB_SESSION_CSRF_STORAGE_KEY);
    } catch {
      return null;
    }
  }

  async function connect(target?: SlackConnection) {
    const csrf = csrfToken();
    if (!csrf) {
      setFailed(true);
      setMessage("Your secure session needs to be refreshed. Sign in again, then retry.");
      return;
    }
    setBusy(target?.connection_id ?? "new");
    try {
      const response = await fetch("/api/integrations/slack/connect", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
        body: JSON.stringify({
          capabilities: CAPABILITIES,
          return_to: "/integrations",
          target_connection_id: target?.connection_id,
          intended_team_id: target?.team_id,
        }),
      });
      const data = (await response.json()) as SlackResponse;
      if (!response.ok || !data.authorization_url) throw new Error("initiation failed");
      setMessage("Redirecting to Slack…");
      redirect(data.authorization_url);
    } catch {
      setFailed(true);
      setMessage("We could not start Slack consent. You can try again.");
      setBusy(null);
    }
  }

  async function disconnect(connection: SlackConnection) {
    const csrf = csrfToken();
    if (!csrf) return;
    setBusy(connection.connection_id);
    try {
      const response = await fetch(`/api/integrations/slack/${encodeURIComponent(connection.connection_id)}`, {
        method: "DELETE",
        credentials: "same-origin",
        headers: { "X-CSRF-Token": csrf },
      });
      const data = (await response.json()) as SlackResponse;
      if (response.status === 202 || data.status === "disconnect_pending") {
        setConnections((current) => current.map((item) => item.connection_id === connection.connection_id ? { ...item, status: "disconnect_pending" } : item));
        setMessage(`Disconnecting ${connection.team_name ?? connection.team_id}; Tessera has blocked new actions.`);
        return;
      }
      if (!response.ok || data.status !== "disconnected") throw new Error("disconnect failed");
      setConnections((current) => current.filter((item) => item.connection_id !== connection.connection_id));
      setMessage(`${connection.team_name ?? connection.team_id} was disconnected.`);
    } catch {
      setFailed(true);
      setMessage(`We could not confirm ${connection.team_name ?? connection.team_id}'s disconnect status.`);
    } finally {
      setBusy(null);
    }
  }

  return (
    <section aria-labelledby="slack-integration-title" data-layout="grid" className="box-border flex h-full w-full flex-col gap-[10px] rounded-[8px] border border-[var(--ag-card-border)] bg-[var(--ag-card)] p-[13px]">
      <div className="flex items-center gap-[10px]">
        <div aria-hidden="true" className="flex h-[34px] w-[34px] shrink-0 items-center justify-center rounded-[9px] border border-black/[0.06] bg-white shadow-[0_2px_8px_rgba(15,23,42,0.08)]">
          <SlackBrandIcon className="h-[20px] w-[20px]" />
        </div>
        <div className="min-w-0">
          <h2 id="slack-integration-title" className="text-[12px] font-semibold text-[var(--ag-text)]">Slack</h2>
          <p className="text-[9px] text-[var(--ag-text-secondary)]">Communication</p>
        </div>
      </div>

      <p className="text-[10px]/[15px] text-[var(--ag-text-secondary)]">Read selected conversations and collaborate through Tessera&apos;s secure broker.</p>

      <div className="space-y-[8px]">
        {connections.map((connection) => {
          const name = connection.team_name ?? connection.team_id;
          const missingUpload = !connection.enabled_capabilities.includes("slack.file.upload");
          const missingPrivateChannels = !connection.enabled_capabilities.includes("slack.private_channels.list")
            || !connection.enabled_capabilities.includes("slack.private_conversation.read")
            || !connection.enabled_capabilities.includes("slack.private_thread.read");
          const missingPeople = !connection.enabled_capabilities.includes("slack.users.list");
          const missingDirectMessages = !connection.enabled_capabilities.includes("slack.direct_message.send");
          return (
            <div key={connection.connection_id} role="group" aria-label={`${name} workspace`} className="rounded-[7px] border border-[var(--ag-card-border)] p-[8px]">
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-[10px] font-semibold text-[var(--ag-text)]">{name}</span>
                <span className={`rounded px-[6px] py-[2px] text-[8px] font-semibold ${connection.status === "connected" ? "bg-[#0B3B2B] text-[#22C55E]" : "bg-[#3B2A0B] text-[#FBBF24]"}`}>{connection.status === "connected" ? "Connected" : "Attention"}</span>
              </div>
              {missingUpload && <p className="mt-1 text-[9px] text-[#FBBF24]">File uploads need an additional scope</p>}
              {missingPrivateChannels && <p className="mt-1 text-[9px] text-[#FBBF24]">Private channels need additional scopes</p>}
              {missingPeople && <p className="mt-1 text-[9px] text-[#FBBF24]">Finding people needs the users:read scope</p>}
              {missingDirectMessages && <p className="mt-1 text-[9px] text-[#FBBF24]">Direct messages need the im:write scope</p>}
              {connection.owner !== false && (
                <div className="mt-2 flex flex-wrap gap-1">
                  <button type="button" disabled={busy !== null} onClick={() => void connect(connection)} className="rounded border border-[var(--ag-card-border)] px-2 py-1 text-[9px] text-[var(--ag-text)] disabled:opacity-50">Upgrade {name} permissions</button>
                  <button type="button" disabled={busy !== null} onClick={() => void disconnect(connection)} className="rounded border border-[#7F1D1D] px-2 py-1 text-[9px] text-[#FCA5A5] disabled:opacity-50">Disconnect {name}</button>
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div className="mt-auto flex gap-2">
        <button type="button" disabled={loading || busy !== null || failed} onClick={() => void connect()} className="rounded-[6px] bg-[var(--ag-purple)] px-[10px] py-[7px] text-[10px] font-semibold text-white disabled:opacity-50">{connections.length ? "Add workspace" : "Connect Slack"}</button>
        {failed && <button type="button" onClick={() => void loadStatus()} className="rounded-[6px] border border-[var(--ag-card-border)] px-[9px] py-[7px] text-[10px] text-[var(--ag-text)]">Retry status</button>}
      </div>

      <p role={failed ? "alert" : "status"} aria-live={failed ? "assertive" : "polite"} className="text-[9px]/[13px] text-[var(--ag-text-secondary)]">{message}</p>
    </section>
  );
}
