"use client";

import { useState } from "react";

/**
 * Settings tab. Edits the agent registration surface — the Principal identity
 * (display_name, public_key, key_algorithm) and the agent card (version,
 * capabilities.streaming / pushNotifications, trust extension, securitySchemes).
 * public_key is shown read-only and is the PUBLIC key only — private material
 * never leaves the vault. Danger zone covers grant revocation and deregistration.
 */

function Toggle({ on, onClick }: { on: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={on}
      className={`box-border w-[38px] h-[22px] shrink-0 flex flex-row items-center rounded-full cursor-pointer transition-colors p-[2px] ${
        on ? "bg-[#5D20DC] justify-end" : "bg-[var(--ag2-input-deep)] justify-start [border:1px_solid_var(--ag2-border)]"
      }`}
    >
      <div className="box-border w-[16px] h-[16px] bg-white rounded-full"></div>
    </button>
  );
}

function Field({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="box-border w-full h-fit shrink-0 flex flex-col gap-[4px] justify-start items-start">
      <div className="text-[10px]/[normal] box-border text-[var(--ag2-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
        {label}
      </div>
      <div
        className={`box-border w-full h-fit shrink-0 flex flex-row gap-0 p-[9px_11px] justify-start items-center bg-[var(--ag2-input)] [border:1px_solid_var(--ag2-border)] rounded-[7px] text-[12px]/[normal] text-[var(--ag2-strong)] text-left overflow-hidden text-ellipsis [white-space:nowrap] ${
          mono ? "font-mono" : "font-[Inter,system-ui,sans-serif] font-medium"
        }`}
      >
        {value}
      </div>
    </div>
  );
}

function ToggleRow({
  title,
  desc,
  on,
  onToggle,
}: {
  title: string;
  desc: string;
  on: boolean;
  onToggle: () => void;
}) {
  return (
    <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[12px] justify-between items-center p-[10px_0px] [border-width:1px_0px_0px_0px] [border-style:solid] [border-color:var(--ag2-border)]">
      <div className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[2px] justify-start items-start">
        <div className="text-[12px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]">
          {title}
        </div>
        <div className="text-[10px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left">
          {desc}
        </div>
      </div>
      <Toggle on={on} onClick={onToggle} />
    </div>
  );
}

export default function AgentSettingsTab() {
  const [streaming, setStreaming] = useState(true);
  const [pushNotifications, setPushNotifications] = useState(false);
  const [trustRequired, setTrustRequired] = useState(true);
  const [bearerAuth, setBearerAuth] = useState(true);

  return (
    <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[12px] justify-start items-start">
      {/* Left column */}
      <div className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[12px] justify-start items-start">
        {/* Identity */}
        <div className="box-border w-full h-fit shrink-0 flex flex-col gap-[12px] p-[16px] justify-start items-start bg-[var(--ag2-panel)] [border:1px_solid_var(--ag2-border)] rounded-[9px]">
          <div className="text-[15px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
            Identity
          </div>
          <Field label="Display name" value="DevOps Agent" />
          <Field label="Agent ID (principal_id)" value="agt_devops_001" mono />
          <Field label="Public key (ed25519)" value="z6MkpTHR8VNsBxYAAWHut2Geadd9jSwuBV8xRoAnZWjFHJ8n" mono />
          <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[12px] justify-start items-start">
            <div className="box-border [flex:1_1_0]">
              <Field label="Key algorithm" value="ed25519" mono />
            </div>
            <div className="box-border [flex:1_1_0]">
              <Field label="Card version" value="2.1.4" mono />
            </div>
          </div>
        </div>

        {/* Card capabilities */}
        <div className="box-border w-full h-fit shrink-0 flex flex-col gap-[4px] p-[16px] justify-start items-start bg-[var(--ag2-panel)] [border:1px_solid_var(--ag2-border)] rounded-[9px]">
          <div className="text-[15px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap] pb-[4px]">
            Agent Card
          </div>
          <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[12px] justify-between items-center p-[10px_0px_4px_0px]">
            <div className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[2px] justify-start items-start">
              <div className="text-[12px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]">
                Streaming
              </div>
              <div className="text-[10px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left">
                capabilities.streaming — stream partial results over the wire
              </div>
            </div>
            <Toggle on={streaming} onClick={() => setStreaming((v) => !v)} />
          </div>
          <ToggleRow
            title="Push notifications"
            desc="capabilities.pushNotifications — notify on long-running task updates"
            on={pushNotifications}
            onToggle={() => setPushNotifications((v) => !v)}
          />
          <ToggleRow
            title="Trust extension required"
            desc="extensions[trust/v1].required — enforce verified reputation on hire"
            on={trustRequired}
            onToggle={() => setTrustRequired((v) => !v)}
          />
          <ToggleRow
            title="Bearer authentication"
            desc="securitySchemes — require a bearer token to invoke this agent"
            on={bearerAuth}
            onToggle={() => setBearerAuth((v) => !v)}
          />
        </div>

        {/* Danger zone */}
        <div className="box-border w-full h-fit shrink-0 flex flex-col gap-[10px] p-[16px] justify-start items-start bg-[var(--ag2-panel)] [border:1px_solid_#5a2330] rounded-[9px]">
          <div className="text-[15px]/[normal] box-border text-[#F87171] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
            Danger Zone
          </div>
          <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[12px] justify-between items-center">
            <div className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[2px] justify-start items-start">
              <div className="text-[12px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]">
                Revoke all credential grants
              </div>
              <div className="text-[10px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left">
                Immediately revokes every active grant issued to this agent.
              </div>
            </div>
            <button
              type="button"
              className="box-border w-fit shrink-0 h-fit flex flex-row gap-0 p-[8px_12px] justify-start items-start bg-[#2A1518] [border:1px_solid_#5a2330] rounded-[6px] cursor-pointer"
            >
              <div className="text-[11px]/[normal] box-border text-[#F87171] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
                Revoke all
              </div>
            </button>
          </div>
          <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[12px] justify-between items-center p-[10px_0px_0px_0px] [border-width:1px_0px_0px_0px] [border-style:solid] [border-color:#3a2027]">
            <div className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[2px] justify-start items-start">
              <div className="text-[12px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]">
                Deregister agent
              </div>
              <div className="text-[10px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left">
                Removes the agent card from the registry. Reputation history is retained.
              </div>
            </div>
            <button
              type="button"
              className="box-border w-fit shrink-0 h-fit flex flex-row gap-0 p-[8px_12px] justify-start items-start bg-[#7f1d1d] rounded-[6px] cursor-pointer"
            >
              <div className="text-[11px]/[normal] box-border text-[#FEE2E2] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
                Deregister
              </div>
            </button>
          </div>
        </div>
      </div>

      {/* Right column: hiring grants status */}
      <div className="box-border w-[280px] shrink-0 h-fit flex flex-col gap-[10px] p-[16px] justify-start items-start bg-[var(--ag2-panel)] [border:1px_solid_var(--ag2-border)] rounded-[9px]">
        <div className="text-[15px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
          Hiring Grants
        </div>
        <div className="text-[10px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left">
          Status of hiring grants tied to this agent.
        </div>
        {[
          { org: "TechCorp Inc.", status: "active" as const },
          { org: "DataFlow Systems", status: "active" as const },
          { org: "InnovateLabs", status: "active" as const },
          { org: "Growth Labs", status: "expired" as const },
          { org: "FinSmart", status: "revoked" as const },
        ].map((g) => {
          const style =
            g.status === "active"
              ? { bg: "#073C31", text: "#38D996" }
              : g.status === "expired"
                ? { bg: "#2A2733", text: "#9CA3AF" }
                : { bg: "#3A1414", text: "#F87171" };
          return (
            <div
              key={g.org}
              className="box-border w-full h-fit shrink-0 flex flex-row gap-[8px] justify-between items-center p-[9px_0px] [border-width:1px_0px_0px_0px] [border-style:solid] [border-color:var(--ag2-border)]"
            >
              <div className="text-[11px]/[normal] box-border text-[var(--ag2-strong)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap] overflow-hidden text-ellipsis">
                {g.org}
              </div>
              <div
                className="box-border w-fit shrink-0 h-fit flex flex-row gap-0 p-[3px_8px] justify-start items-start rounded-[4px]"
                style={{ backgroundColor: style.bg }}
              >
                <div
                  className="text-[9px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]"
                  style={{ color: style.text }}
                >
                  {g.status}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
