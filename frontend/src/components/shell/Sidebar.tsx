import Link from "next/link";

/**
 * Single shared app sidebar (Pencil "Sidebar 2" design), used by every page.
 * Nav is data-driven: items with an `href` are links; the rest are placeholders
 * until their screens exist.
 */

export type NavKey =
  | "dashboard"
  | "agents"
  | "marketplace"
  | "organizations"
  | "capabilities"
  | "credentials-vault"
  | "tasks"
  | "contracts"
  | "approvals"
  | "negotiations"
  | "disputes"
  | "evidence-audit"
  | "billing"
  | "security"
  | "integrations"
  | "settings";

type NavItem = {
  key: NavKey;
  icon: string;
  label: string;
  href?: string;
};

type NavSection = {
  label: string;
  items: NavItem[];
};

const NAV_SECTIONS: NavSection[] = [
  {
    label: "OVERVIEW",
    items: [{ key: "dashboard", icon: "⌘", label: "Dashboard", href: "/" }],
  },
  {
    label: "ECOSYSTEM",
    items: [
      { key: "agents", icon: "✧", label: "Agents", href: "/agents" },
      { key: "marketplace", icon: "▣", label: "Marketplace", href: "/marketplace" },
      { key: "organizations", icon: "♙", label: "Organizations", href: "/organizations" },
      { key: "capabilities", icon: "✦", label: "Capabilities" },
      { key: "credentials-vault", icon: "◇", label: "Credentials Vault" },
    ],
  },
  {
    label: "OPERATIONS",
    items: [
      { key: "tasks", icon: "▤", label: "Tasks" },
      { key: "contracts", icon: "▧", label: "Contracts" },
      { key: "approvals", icon: "♢", label: "Approvals" },
      { key: "negotiations", icon: "▱", label: "Negotiations" },
      { key: "disputes", icon: "◈", label: "Disputes" },
      { key: "evidence-audit", icon: "▧", label: "Evidence & Audit" },
    ],
  },
  {
    label: "SETTINGS",
    items: [
      { key: "billing", icon: "▤", label: "Billing" },
      { key: "security", icon: "⚙", label: "Security" },
      { key: "integrations", icon: "⌁", label: "Integrations" },
      { key: "settings", icon: "⚙", label: "Settings" },
    ],
  },
];

// Class recipes from the Pencil export: active = purple pill + bright label.
// Active bg/icon/text come from theme vars (dark: deep purple pill; light: soft lavender pill).
const itemClass = (isActive: boolean) =>
  `box-border w-full h-fit shrink-0 flex flex-row gap-[10px] p-[9px_14px] justify-start items-center ${
    isActive ? "bg-[var(--ag2-nav-active-bg)]" : "bg-[var(--ag-sidebar)]"
  } rounded-[7px] relative`;
const iconClass = (isActive: boolean) =>
  `text-[15px]/[normal] box-border ${
    isActive ? "text-[var(--ag2-nav-active-icon)]" : "text-[var(--ag2-nav-icon)]"
  } font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]`;
const labelClass = (isActive: boolean) =>
  `text-[13px]/[normal] box-border ${
    isActive
      ? "text-[var(--ag2-nav-active-text)] font-[Inter,system-ui,sans-serif] font-semibold"
      : "text-[var(--ag2-nav)] font-[Inter,system-ui,sans-serif] font-normal"
  } text-left [white-space:nowrap]`;

function NavEntry({ item, active }: { item: NavItem; active: NavKey }) {
  const isActive = item.key === active;
  const inner = (
    <>
      <div className={iconClass(isActive)}>{item.icon}</div>
      <div className={labelClass(isActive)}>{item.label}</div>
    </>
  );
  if (item.href) {
    return (
      <Link href={item.href} className={itemClass(isActive)}>
        {inner}
      </Link>
    );
  }
  return <div className={itemClass(isActive)}>{inner}</div>;
}

export default function Sidebar({ active }: { active: NavKey }) {
  return (
    <div className="box-border w-[190px] shrink-0 h-full flex flex-col gap-0 justify-start items-start bg-[var(--ag-sidebar)] [border-width:0px_1px_0px_0px] [border-style:solid] [border-color:var(--ag-divider)] relative overflow-y-auto">
      <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[9px] p-[22px_18px_18px_18px] justify-start items-center">
        <div className="box-border w-[27px] shrink-0 h-[27px] flex flex-row gap-0 justify-center items-center bg-[#2B1251] rounded-[8px]">
          <div className="text-[17px]/[normal] box-border text-[#B975FF] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
            ✦
          </div>
        </div>
        <div className="text-[17px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
          AGENTIO
        </div>
      </div>
      <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[10px] p-[14px_18px] justify-start items-center">
        <div className="box-border w-[32px] shrink-0 h-[32px] bg-[#D99975] rounded-full"></div>
        <div className="text-[12px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
          Rey Ferreras
        </div>
      </div>
      {NAV_SECTIONS.map((section) => (
        <div key={section.label} className="contents">
          <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 p-[13px_18px_5px_18px] justify-start items-start">
            <div className="text-[10px]/[normal] box-border text-[var(--ag2-muted)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
              {section.label}
            </div>
          </div>
          {section.items.map((item) => (
            <NavEntry key={item.key} item={item} active={active} />
          ))}
        </div>
      ))}
      <div className="box-border w-[162px] h-fit shrink-0 mt-auto mb-[14px] ml-[14px] flex flex-row gap-[9px] p-[12px_14px] justify-start items-center bg-[var(--ag2-panel)] [border:1px_solid_var(--ag2-border)] rounded-[9px]">
        <div className="text-[14px]/[normal] box-border text-[#22C55E] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
          ●
        </div>
        <div className="box-border w-fit shrink-0 h-fit flex flex-col gap-[2px] justify-start items-start">
          <div className="text-[11px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
            Agentio Network
          </div>
          <div className="text-[9px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            All systems operational
          </div>
        </div>
      </div>
    </div>
  );
}
