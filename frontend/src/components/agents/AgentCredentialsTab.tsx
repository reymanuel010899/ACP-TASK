/**
 * Credentials tab. The vault is zero-knowledge — it only ever exposes credential
 * METADATA (credential_id, name, credential_type, created_at), never the
 * ciphertext/nonce. This view lists the credentials this agent can use via
 * grant records (scope, granted_by, granted_at) issued by their owners.
 */

type GrantStatus = "active" | "revoked" | "expired";

const STATUS_STYLE: Record<GrantStatus, { label: string; bg: string; text: string }> = {
  active: { label: "Active", bg: "#073C31", text: "#38D996" },
  revoked: { label: "Revoked", bg: "#3A1414", text: "#F87171" },
  expired: { label: "Expired", bg: "#2A2733", text: "#9CA3AF" },
};

type CredentialGrant = {
  credentialId: string;
  name: string;
  credentialType: string;
  icon: string;
  scope: string;
  grantedBy: string;
  grantedAt: string;
  status: GrantStatus;
};

const GRANTS: CredentialGrant[] = [
  {
    credentialId: "cr_9f2a…",
    name: "AWS Deploy Role",
    credentialType: "aws_iam_role",
    icon: "☁",
    scope: "deploy:eks,ecr",
    grantedBy: "TechCorp Inc.",
    grantedAt: "May 12, 2024",
    status: "active",
  },
  {
    credentialId: "cr_4b71…",
    name: "GitHub Actions Token",
    credentialType: "oauth_token",
    icon: "◉",
    scope: "repo:write,workflow",
    grantedBy: "DataFlow Systems",
    grantedAt: "May 08, 2024",
    status: "active",
  },
  {
    credentialId: "cr_c380…",
    name: "Terraform Cloud API Key",
    credentialType: "api_key",
    icon: "✥",
    scope: "workspaces:apply",
    grantedBy: "InnovateLabs",
    grantedAt: "Apr 29, 2024",
    status: "active",
  },
  {
    credentialId: "cr_1d55…",
    name: "Datadog Ingest Key",
    credentialType: "api_key",
    icon: "▣",
    scope: "metrics:write,logs:write",
    grantedBy: "Growth Labs",
    grantedAt: "Apr 21, 2024",
    status: "expired",
  },
  {
    credentialId: "cr_7e90…",
    name: "Kubeconfig (prod)",
    credentialType: "kubeconfig",
    icon: "✦",
    scope: "namespace:payments",
    grantedBy: "FinSmart",
    grantedAt: "Apr 15, 2024",
    status: "revoked",
  },
];

export default function AgentCredentialsTab() {
  const activeCount = GRANTS.filter((g) => g.status === "active").length;

  return (
    <div className="box-border w-full h-fit shrink-0 flex flex-col gap-[12px] justify-start items-start">
      {/* Zero-knowledge banner */}
      <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[10px] p-[12px_14px] justify-start items-center bg-[#16132b] [border:1px_solid_#33305a] rounded-[9px]">
        <div className="text-[16px]/[normal] box-border text-[#B266FF] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
          ◇
        </div>
        <div className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[2px] justify-start items-start">
          <div className="text-[12px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
            Zero-knowledge vault
          </div>
          <div className="text-[10px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left">
            Only credential metadata and access grants are shown. Secret material is encrypted client-side and never leaves the vault.
          </div>
        </div>
        <div className="box-border w-fit shrink-0 h-fit flex flex-col gap-[1px] justify-center items-end">
          <div className="text-[18px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-right [white-space:nowrap]">
            {activeCount}
          </div>
          <div className="text-[9px]/[normal] box-border text-[var(--ag2-muted)] font-[Inter,system-ui,sans-serif] font-normal text-right [white-space:nowrap]">
            active grants
          </div>
        </div>
      </div>

      {/* Grants table */}
      <div className="box-border w-full h-fit shrink-0 flex flex-col gap-0 justify-start items-start bg-[var(--ag2-panel)] [border:1px_solid_var(--ag2-border)] rounded-[9px] overflow-hidden">
        <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[10px] p-[11px_16px] justify-start items-center bg-[var(--ag2-surface)]">
          <HeaderCell className="[flex:1_1_0] min-w-0" label="Credential" />
          <HeaderCell className="w-[140px]" label="Type" />
          <HeaderCell className="w-[170px]" label="Scope" />
          <HeaderCell className="w-[140px]" label="Granted by" />
          <HeaderCell className="w-[100px]" label="Granted" />
          <HeaderCell className="w-[90px]" label="Status" />
        </div>
        {GRANTS.map((g) => {
          const s = STATUS_STYLE[g.status];
          return (
            <div
              key={g.credentialId}
              className="box-border w-full h-fit shrink-0 flex flex-row gap-[10px] p-[12px_16px] justify-start items-center [border-width:1px_0px_0px_0px] [border-style:solid] [border-color:var(--ag2-border)]"
            >
              <div className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-row gap-[9px] justify-start items-center">
                <div className="box-border w-[30px] shrink-0 h-[30px] flex flex-row gap-0 justify-center items-center bg-[var(--ag2-tile)] rounded-[7px]">
                  <div className="text-[14px]/[normal] box-border text-[#B266FF] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                    {g.icon}
                  </div>
                </div>
                <div className="box-border min-w-0 h-fit flex flex-col gap-[2px] justify-start items-start">
                  <div className="text-[12px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]">
                    {g.name}
                  </div>
                  <div className="text-[9px]/[normal] box-border text-[var(--ag2-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap] font-mono">
                    {g.credentialId}
                  </div>
                </div>
              </div>
              <div className="box-border w-[140px] shrink-0 h-fit text-[10px]/[normal] text-[var(--ag2-strong)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap] font-mono overflow-hidden text-ellipsis">
                {g.credentialType}
              </div>
              <div className="box-border w-[170px] shrink-0 h-fit text-[10px]/[normal] text-[#A78BFA] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap] font-mono overflow-hidden text-ellipsis">
                {g.scope}
              </div>
              <div className="box-border w-[140px] shrink-0 h-fit text-[11px]/[normal] text-[var(--ag2-strong)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap] overflow-hidden text-ellipsis">
                {g.grantedBy}
              </div>
              <div className="box-border w-[100px] shrink-0 h-fit text-[10px]/[normal] text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                {g.grantedAt}
              </div>
              <div className="box-border w-[90px] shrink-0 h-fit">
                <div
                  className="box-border w-fit h-fit flex flex-row gap-0 p-[4px_8px] justify-start items-start rounded-[4px]"
                  style={{ backgroundColor: s.bg }}
                >
                  <div
                    className="text-[10px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]"
                    style={{ color: s.text }}
                  >
                    {s.label}
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function HeaderCell({ label, className }: { label: string; className: string }) {
  return (
    <div className={`box-border ${className} h-fit flex flex-row gap-0 justify-start items-center`}>
      <div className="text-[10px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
        {label}
      </div>
    </div>
  );
}
