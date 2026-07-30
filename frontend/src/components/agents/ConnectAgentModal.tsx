"use client";

import { useEffect, useState } from "react";
import CapabilityPicker from "@/components/agents/CapabilityPicker";
import { useSession } from "@/lib/SessionProvider";

/**
 * Connect an existing (BYO) agent — the "someone else already built and hosts
 * it" path. The operator pastes the URL of their already-running agent (their
 * own domain/cloud); the runner fetches its published card server-side,
 * validates it, registers it into the registry so requesters discover it, and
 * then only health-checks it. Nothing is launched here.
 */

type Detected = {
  name: string;
  url: string;
  principal_id: string;
  capabilities: string[];
  version: string;
  /** verified = the agent publishes its own AgentTrust identity and can sign
   *  for it. basic = plain A2A agent; the marketplace assigns an identifier it
   *  cannot sign with, so reputation is platform-attested, not proven. */
  trust_tier: "verified" | "basic";
  /** proven = signed the challenge; unproven = claimed the identity but could
   *  not prove it; none = never claimed one. */
  proof: "proven" | "unproven" | "none";
};

const inputClass =
  "box-border w-full h-fit shrink-0 p-[10px_12px] bg-[var(--ag2-input)] [border:1px_solid_var(--ag2-border)] rounded-[7px] text-[12px]/[normal] text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] outline-none focus:[border-color:#5D20DC]";

export default function ConnectAgentModal({
  open,
  onClose,
  onConnected,
}: {
  open: boolean;
  onClose: () => void;
  onConnected?: () => void;
}) {
  if (!open) return null;
  return <ConnectWizard onClose={onClose} onConnected={onConnected} />;
}

function ConnectWizard({ onClose, onConnected }: { onClose: () => void; onConnected?: () => void }) {
  const { session } = useSession();
  const [url, setUrl] = useState("");
  const [detected, setDetected] = useState<Detected | null>(null);
  // What the operator declares this agent offers. Prefilled from the card when
  // it publishes skills; editable because most external agents don't.
  const [caps, setCaps] = useState<string[]>([]);
  const [verifying, setVerifying] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function verify() {
    setVerifying(true);
    setError(null);
    setDetected(null);
    try {
      const res = await fetch("/api/agents/verify-connect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ endpoint_url: url.trim() }),
      });
      const data = (await res.json().catch(() => null)) as (Detected & { error?: string }) | null;
      if (!res.ok) {
        setError(data?.error ?? `Could not verify the agent (HTTP ${res.status}).`);
        return;
      }
      setDetected(data as Detected);
      setCaps((data as Detected).capabilities ?? []);
    } catch {
      setError("Could not reach the server.");
    } finally {
      setVerifying(false);
    }
  }

  async function connect() {
    setConnecting(true);
    setError(null);
    try {
      const res = await fetch("/api/agents/connect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          endpoint_url: url.trim(),
          capabilities: caps,
          // The signed-in user OWNS the agent they connect: only they may
          // disconnect it later.
          owner_principal_id: session?.principalId ?? null,
        }),
      });
      const data = (await res.json().catch(() => null)) as { error?: string } | null;
      if (!res.ok) {
        setError(data?.error ?? `Could not connect the agent (HTTP ${res.status}).`);
        return;
      }
      onConnected?.();
      setDone(true);
    } catch {
      setError("Could not reach the server.");
    } finally {
      setConnecting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-[20px] bg-[rgba(4,3,12,0.62)]"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Connect existing agent"
        className="box-border w-[640px] max-w-[94vw] max-h-[88vh] flex flex-col bg-[var(--ag2-panel)] [border:1px_solid_var(--ag2-border)] rounded-[12px] overflow-hidden shadow-2xl"
      >
        <div className="box-border w-full shrink-0 flex flex-row gap-0 p-[16px_20px] justify-between items-center [border-width:0px_0px_1px_0px] [border-style:solid] [border-color:var(--ag2-border)]">
          <div className="box-border flex flex-col gap-[2px]">
            <div className="text-[16px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
              Connect existing agent
            </div>
            <div className="text-[11px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left">
              Already running somewhere? Paste its URL to publish it to the marketplace.
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="box-border w-[30px] h-[30px] flex items-center justify-center rounded-[7px] bg-[var(--ag2-surface)] [border:1px_solid_var(--ag2-border)] text-[var(--ag2-dim)] text-[14px] cursor-pointer"
          >
            ✕
          </button>
        </div>

        {/* flex basis:auto (not 0) so the body sizes to its content — with
            basis:0 + overflow-auto inside a max-height (content-sized) card the
            browser resolves this box to 0px and the fields vanish. */}
        <div className="box-border w-full [flex:0_1_auto] min-h-0 overflow-y-auto flex flex-col gap-[14px] p-[20px]">
          {done ? (
            <div className="box-border w-full flex flex-col gap-[12px] p-[10px] justify-start items-center">
              <div className="box-border w-[52px] h-[52px] flex items-center justify-center rounded-full bg-[#073C31] text-[24px] text-[#35D78B]">✓</div>
              <div className="text-[16px] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-center">Agent connected</div>
              <div className="text-[12px] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] text-center max-w-[420px]">
                It&apos;s published to the registry and discoverable. Requesters will call it{" "}
                <b>directly at its own URL</b> — we only track its health.
              </div>
            </div>
          ) : (
            <>
              <div className="box-border w-full flex flex-col gap-[6px]">
                <div className="text-[11px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-medium">
                  Agent URL
                </div>
                <input
                  className={inputClass}
                  value={url}
                  placeholder="https://agents.my-company.com/devops-bot"
                  aria-label="Agent URL"
                  onChange={(e) => {
                    setUrl(e.target.value);
                    setDetected(null);
                  }}
                />
                <div className="text-[10px]/[normal] box-border text-[var(--ag2-muted)] font-[Inter,system-ui,sans-serif]">
                  Paste the agent&apos;s base URL <b>or</b> its full{" "}
                  <span className="font-mono">/.well-known/agent-card.json</span> URL — either works. To join the
                  marketplace the card must declare the AgentTrust trust extension.
                </div>
              </div>

              <button
                type="button"
                onClick={verify}
                disabled={!url.trim() || verifying}
                className="box-border w-fit h-fit flex flex-row p-[9px_14px] justify-center items-center bg-[var(--ag2-surface)] [border:1px_solid_var(--ag2-border)] rounded-[7px] cursor-pointer text-[11px] text-[var(--ag2-text)] font-semibold font-[Inter,system-ui,sans-serif] disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {verifying ? "Verifying…" : "Verify agent"}
              </button>

              {error && (
                <div className="box-border w-full flex flex-row gap-[8px] p-[10px_12px] bg-[#2A1518] [border:1px_solid_#5a2330] rounded-[8px]">
                  <div className="text-[12px] text-[#F87171]">⚠</div>
                  <div className="text-[11px]/[normal] box-border text-[#FCA5A5] font-[Inter,system-ui,sans-serif]">{error}</div>
                </div>
              )}

              {detected && (
                <div className="box-border w-full flex flex-col gap-[10px] p-[14px] bg-[var(--ag2-surface)] [border:1px_solid_#2f7d5b] rounded-[9px]">
                  <div className="box-border w-full flex flex-row gap-[8px] items-center [flex-wrap:wrap]">
                    <div className="text-[11px] box-border text-[#35D78B] font-[Inter,system-ui,sans-serif] font-semibold">
                      ✓ Reachable — this is what will be published
                    </div>
                    <div
                      className={`box-border w-fit flex flex-row p-[3px_8px] rounded-[4px] text-[9px] font-semibold font-[Inter,system-ui,sans-serif] [white-space:nowrap] ${
                        detected.trust_tier === "verified"
                          ? "bg-[#073C31] text-[#38D996]"
                          : "bg-[#1E3A5F] text-[#7DD3FC]"
                      }`}
                    >
                      {detected.trust_tier === "verified" ? "VERIFIED · TRANSACTABLE" : "BASIC · DISCOVERY ONLY"}
                    </div>
                  </div>
                  <div className="text-[10px]/[1.5] box-border text-[var(--ag2-muted)] font-[Inter,system-ui,sans-serif]">
                    {detected.trust_tier === "verified"
                      ? "Transactable — it signed our challenge, proving it holds the private key for its identity. It speaks the negotiation vocabulary, so you can agree a price, get evidence for the work, and it accrues provable reputation."
                      : detected.proof === "unproven"
                        ? "Declared an AgentTrust identity but could not prove it — it failed to sign our challenge, so it can't hold the reputation of a principal it can't sign for. It joins as Basic (discovery only)."
                        : "Discovery only — plain A2A agent, listed and reachable but it does not speak the negotiation vocabulary. No price negotiation, no verifiable result. It becomes transactable by adopting the AgentTrust extension and signing the identity challenge."}
                  </div>
                  <Row label="Name" value={detected.name} />
                  <Row label="Version" value={detected.version} />
                  <Row label="Endpoint" value={detected.url} mono />
                  <Row label="Principal ID" value={detected.principal_id} mono />
                  <div className="text-[10px]/[normal] box-border text-[var(--ag2-muted)] font-[Inter,system-ui,sans-serif]">
                    {detected.capabilities.length > 0
                      ? `Its card publishes ${detected.capabilities.length} capability(-ies) — prefilled below. Adjust if needed.`
                      : "Its card publishes no capabilities in this marketplace's vocabulary — declare them below."}
                  </div>
                </div>
              )}

              {/* Always visible — the operator declares what this agent offers
                  whether or not its card publishes skills. Prefilled on a
                  successful Verify. */}
              <CapabilityPicker
                selected={caps}
                onToggle={(cap) =>
                  setCaps((cur) =>
                    cur.includes(cap.id) ? cur.filter((x) => x !== cap.id) : [...cur, cap.id],
                  )
                }
                showError={!!detected && caps.length === 0}
                errorMsg="Declare at least one capability so requesters can discover this agent."
                heading="Capabilities this agent offers"
                maxHeightClass="max-h-[240px]"
              />
            </>
          )}
        </div>

        <div className="box-border w-full shrink-0 flex flex-row gap-0 p-[14px_20px] justify-between items-center [border-width:1px_0px_0px_0px] [border-style:solid] [border-color:var(--ag2-border)]">
          {done ? (
            <>
              <div />
              <button type="button" onClick={onClose} className="box-border w-fit flex flex-row p-[10px_18px] justify-center items-center rounded-[7px] text-[12px] font-semibold font-[Inter,system-ui,sans-serif] bg-[#5D20DC] text-[#F4F2FF] cursor-pointer">
                Done
              </button>
            </>
          ) : (
            <>
              <button type="button" onClick={onClose} className="text-[12px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-medium cursor-pointer">
                Cancel
              </button>
              <button
                type="button"
                onClick={connect}
                disabled={!detected || caps.length === 0 || connecting}
                className="box-border w-fit flex flex-row p-[10px_18px] justify-center items-center bg-[#5D20DC] rounded-[7px] cursor-pointer text-[12px] text-[#F4F2FF] font-semibold font-[Inter,system-ui,sans-serif] disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {connecting ? "Connecting…" : "Connect agent"}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="box-border w-full flex flex-col gap-[2px]">
      <div className="text-[10px]/[normal] box-border text-[var(--ag2-muted)] font-[Inter,system-ui,sans-serif]">{label}</div>
      <div className={`text-[12px]/[normal] box-border w-full text-[var(--ag2-strong)] text-left break-all ${mono ? "font-mono" : "font-[Inter,system-ui,sans-serif] font-medium"}`}>
        {value}
      </div>
    </div>
  );
}
