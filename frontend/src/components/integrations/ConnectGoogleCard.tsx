"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { readStoredCsrfToken as csrfToken } from "@/lib/agentSession";
import GoogleBrandIcon from "./GoogleBrandIcon";

type GoogleState =
  | "disconnected"
  | "initiating"
  | "redirected"
  | "denied"
  | "callback-failed"
  | "status-load-failed"
  | "connected"
  | "reconnecting"
  | "disconnecting"
  | "disconnect-failed"
  | "pending_revocation";

type StatusResponse = {
  status?: "disconnected" | "connected" | "pending_revocation";
  enabled_capabilities?: string[];
  authorization_url?: string;
  error?: string;
};

const CAPABILITIES = ["calendar.create", "gmail.send", "drive.upload"];
const LABELS: Record<string, string> = {
  "calendar.create": "Calendar events",
  "calendar.read": "Calendar availability",
  "gmail.send": "Gmail sending",
  "gmail.read": "Gmail reading",
  "drive.upload": "Drive uploads",
  "drive.read": "Drive files",
};

export default function ConnectGoogleCard({
  redirect = (url: string) => window.location.assign(url),
  layout = "banner",
}: {
  redirect?: (url: string) => void;
  layout?: "banner" | "grid";
}) {
  const [state, setState] = useState<GoogleState>("disconnected");
  const [capabilities, setCapabilities] = useState<string[]>([]);
  const [message, setMessage] = useState("Loading Google connection status…");
  const [loading, setLoading] = useState(true);
  const retryRef = useRef<HTMLButtonElement>(null);

  const loadStatus = useCallback(async () => {
    setLoading(true);
    setMessage("Loading Google connection status…");
    try {
      const response = await fetch("/api/integrations/google", {
        credentials: "same-origin",
        cache: "no-store",
      });
      if (!response.ok) throw new Error("status unavailable");
      const data = (await response.json()) as StatusResponse;
      const next = data.status ?? "disconnected";
      setState(next);
      setCapabilities(data.enabled_capabilities ?? []);
      setMessage(
        next === "connected"
          ? "Google Workspace is connected"
          : next === "pending_revocation"
            ? "Revocation is pending. Google access is blocked in Tessera."
            : "Google Workspace is not connected",
      );
    } catch {
      setState("status-load-failed");
      setMessage("We could not load your Google connection status.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const callback = new URLSearchParams(window.location.search).get("google");
    if (callback === "denied") {
      queueMicrotask(() => {
        setState("denied");
        setMessage("Google access was denied. Nothing was connected.");
        setLoading(false);
      });
      return;
    }
    if (callback === "callback-failed") {
      queueMicrotask(() => {
        setState("callback-failed");
        setMessage("We could not finish connecting Google.");
        setLoading(false);
      });
      return;
    }
    queueMicrotask(() => void loadStatus());
  }, [loadStatus]);

  useEffect(() => {
    if (state === "pending_revocation") retryRef.current?.focus();
  }, [state]);


  async function connect(reconnect = false) {
    const csrf = csrfToken();
    if (!csrf) {
      setState("callback-failed");
      setMessage("Your secure session needs to be refreshed. Sign in again, then retry.");
      return;
    }
    setState(reconnect ? "reconnecting" : "initiating");
    setMessage(
      reconnect
        ? "Starting a fresh Google consent flow…"
        : "Preparing Google consent…",
    );
    try {
      const response = await fetch("/api/integrations/google/connect", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrf,
        },
        body: JSON.stringify({
          capabilities: CAPABILITIES,
          return_to: "/integrations",
        }),
      });
      const data = (await response.json()) as StatusResponse;
      if (!response.ok || !data.authorization_url) throw new Error("initiation failed");
      setState("redirected");
      setMessage("Redirecting to Google…");
      redirect(data.authorization_url);
    } catch {
      setState("callback-failed");
      setMessage("We could not start Google consent. You can try again.");
    }
  }

  async function disconnect() {
    const csrf = csrfToken();
    if (!csrf) {
      setState("callback-failed");
      setMessage("Your secure session needs to be refreshed. Sign in again, then retry.");
      return;
    }
    setState("disconnecting");
    setMessage("Blocking Tessera access and revoking Google authorization…");
    try {
      const response = await fetch("/api/integrations/google", {
        method: "DELETE",
        credentials: "same-origin",
        headers: { "X-CSRF-Token": csrf },
      });
      const data = (await response.json()) as StatusResponse;
      if (response.status === 202 || data.status === "pending_revocation") {
        setState("pending_revocation");
        setMessage("Revocation is pending. Tessera access is already blocked; retry to finish at Google.");
        return;
      }
      if (!response.ok || data.status !== "disconnected") throw new Error("disconnect failed");
      setState("disconnected");
      setCapabilities([]);
      setMessage("Google Workspace was disconnected.");
    } catch {
      setState("disconnect-failed");
      setMessage(
        "I could not confirm whether Google access was blocked. Check the connection status before retrying.",
      );
    }
  }

  const busy = loading || ["initiating", "redirected", "reconnecting", "disconnecting"].includes(state);
  const isGrid = layout === "grid";
  const statusLabel =
    state === "connected"
      ? "Connected"
      : state === "pending_revocation"
        ? "Revoking"
        : state === "status-load-failed"
          ? "Unavailable"
          : "Not connected";
  const statusClasses =
    state === "connected"
      ? "bg-[#0B3B2B] text-[#22C55E]"
      : state === "pending_revocation"
        ? "bg-[#3B2A0B] text-[#FBBF24]"
        : state === "status-load-failed"
          ? "bg-[#3F1D24] text-[#FCA5A5]"
          : "bg-[var(--ag-input-bg)] text-[var(--ag-text-secondary)]";

  return (
    <section
      aria-labelledby="google-integration-title"
      data-layout={layout}
      className={
        isGrid
          ? "box-border w-full h-full flex flex-col gap-[10px] p-[13px] bg-[var(--ag-card)] border border-[var(--ag-card-border)] rounded-[8px]"
          : "box-border w-full rounded-[12px] border border-[var(--ag-card-border)] bg-[var(--ag-card)] p-[16px] sm:p-[20px]"
      }
    >
      <div className={isGrid ? "flex h-full flex-col gap-[10px]" : "flex flex-col gap-[16px] sm:flex-row sm:items-start sm:justify-between"}>
        <div className="min-w-0">
          <div className="flex items-center gap-[10px]">
            <div
              aria-hidden="true"
              className={`flex shrink-0 items-center justify-center border border-black/[0.06] bg-white shadow-[0_2px_8px_rgba(15,23,42,0.08)] ${isGrid ? "h-[34px] w-[34px] rounded-[9px]" : "h-[40px] w-[40px] rounded-[11px]"}`}
            >
              <GoogleBrandIcon
                className={isGrid ? "h-[19px] w-[19px]" : "h-[23px] w-[23px]"}
              />
            </div>
            <div>
              <h2 id="google-integration-title" className={`${isGrid ? "text-[12px]" : "text-[15px]"} font-semibold text-[var(--ag-text)]`}>
                Google Workspace
              </h2>
              <p className={`${isGrid ? "text-[9px]" : "text-[12px]"} text-[var(--ag-text-secondary)]`}>
                {isGrid ? "Productivity" : "Calendar, Gmail, and Drive through Tessera\u0027s secure broker."}
              </p>
            </div>
          </div>

          {isGrid && (
            <div className={`mt-[10px] w-fit rounded-[4px] px-[8px] py-[3px] text-[9px] font-semibold ${statusClasses}`}>
              {statusLabel}
            </div>
          )}

          {state === "connected" && capabilities.length > 0 && (
            <ul aria-label="Enabled Google capabilities" className={`${isGrid ? "mt-[9px] gap-[4px]" : "mt-[14px] gap-[6px]"} flex flex-wrap`}>
              {capabilities.map((capability) => (
                <li key={capability} className={`rounded-full bg-[#0B3B2B] text-[#4ADE80] ${isGrid ? "px-[6px] py-[3px] text-[9px]" : "px-[9px] py-[4px] text-[11px]"}`}>
                  {LABELS[capability] ?? capability}
                </li>
              ))}
            </ul>
          )}
        </div>

        {isGrid && (
          <p className="text-[10px]/[15px] text-[var(--ag-text-secondary)]">
            Sync Calendar, Gmail, and Drive through Tessera&apos;s secure broker.
          </p>
        )}

        <div className={`${isGrid ? "mt-auto" : ""} flex shrink-0 flex-wrap gap-[8px]`}>
          {state === "connected" && (
            <>
              <button type="button" disabled={busy} onClick={() => void connect(true)} className={`${isGrid ? "px-[9px] py-[7px] text-[10px]" : "px-[12px] py-[8px] text-[12px]"} rounded-[7px] border border-[var(--ag-card-border)] text-[var(--ag-text)] disabled:opacity-60`}>
                {isGrid ? "Reconnect" : "Reconnect Google"}
              </button>
              <button type="button" disabled={busy} onClick={() => void disconnect()} className={`${isGrid ? "px-[9px] py-[7px] text-[10px]" : "px-[12px] py-[8px] text-[12px]"} rounded-[7px] border border-[#7F1D1D] text-[#FCA5A5] disabled:opacity-60`}>
                {isGrid ? "Disconnect" : "Disconnect Google"}
              </button>
            </>
          )}
          {state === "pending_revocation" && (
            <button ref={retryRef} type="button" onClick={() => void disconnect()} className="rounded-[7px] bg-[var(--ag-purple)] px-[13px] py-[8px] text-[12px] font-semibold text-white">
              Retry revocation
            </button>
          )}
          {state === "status-load-failed" && (
            <>
              <button
                type="button"
                disabled
                className="rounded-[7px] bg-[var(--ag-purple)] px-[13px] py-[8px] text-[12px] font-semibold text-white opacity-50"
              >
                Connect Google
              </button>
              <button
                type="button"
                onClick={() => void loadStatus()}
                className="rounded-[7px] border border-[var(--ag-card-border)] px-[12px] py-[8px] text-[12px] text-[var(--ag-text)]"
              >
                Retry status
              </button>
            </>
          )}
          {(["disconnected", "denied", "callback-failed", "disconnect-failed"] as GoogleState[]).includes(state) && (
            <button
              type="button"
              disabled={busy}
              onClick={() => state === "disconnect-failed" ? void loadStatus() : void connect(false)}
              className="rounded-[7px] bg-[var(--ag-purple)] px-[13px] py-[8px] text-[12px] font-semibold text-white disabled:opacity-60"
            >
              {state === "denied"
                ? "Try again"
                : state === "disconnect-failed"
                    ? "Check status"
                    : "Connect Google"}
            </button>
          )}
        </div>
      </div>

      <p
        role={["callback-failed", "status-load-failed", "disconnect-failed"].includes(state) ? "alert" : "status"}
        aria-live={["callback-failed", "status-load-failed", "disconnect-failed"].includes(state) ? "assertive" : "polite"}
        className={`${isGrid ? "text-[9px]/[13px]" : "mt-[14px] text-[12px]"} text-[var(--ag-text-secondary)]`}
      >
        {message}
      </p>
    </section>
  );
}
