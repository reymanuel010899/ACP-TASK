/**
 * Capabilities — right rail (Pencil "Capabilities" design): category breakdown,
 * top capabilities leaderboard, and recently added list. Same `--ag-*` token
 * conventions as CapabilitiesContent.
 */

const CATEGORIES: { icon: string; color: string; label: string; count: string }[] = [
  { icon: "⬡", color: "#3B82F6", label: "DevOps", count: "48" },
  { icon: "☁", color: "#F59E0B", label: "Cloud", count: "36" },
  { icon: "♢", color: "#EF4444", label: "Security", count: "32" },
  { icon: "⌘", color: "#6D3CE0", label: "Development", count: "42" },
  { icon: "✎", color: "#06B6D4", label: "Design", count: "28" },
  { icon: "$", color: "#22C55E", label: "Finance", count: "22" },
  { icon: "⚑", color: "#8B5CF6", label: "Marketing", count: "18" },
  { icon: "⚙", color: "#64748B", label: "Operations", count: "12" },
  { icon: "●", color: "#64748B", label: "Other", count: "10" },
];

const TOP: { rank: string; icon: string; color: string; name: string; stats: string }[] = [
  { rank: "1", icon: "✧", color: "#3B82F6", name: "Kubernetes Deployment", stats: "★ 4.9 (342 tasks)" },
  { rank: "2", icon: "☁", color: "#F59E0B", name: "AWS Infrastructure Setup", stats: "★ 4.8 (289 tasks)" },
  { rank: "3", icon: "</>", color: "#6D3CE0", name: "API Development", stats: "★ 4.8 (456 tasks)" },
  { rank: "4", icon: "♢", color: "#EF4444", name: "Security Assessment", stats: "★ 4.7 (198 tasks)" },
  { rank: "5", icon: "▥", color: "#F59E0B", name: "Financial Analysis", stats: "★ 4.6 (312 tasks)" },
];

const RECENT: { icon: string; color: string; name: string; time: string }[] = [
  { icon: "⚑", color: "#6D3CE0", name: "Terraform Automation", time: "Added 2 days ago" },
  { icon: "◇", color: "#8B5CF6", name: "CI/CD Pipeline Setup", time: "Added 4 days ago" },
  { icon: "♟", color: "#3B82F6", name: "Data Analysis with Python", time: "Added 1 week ago" },
];

function CardHeader({ title }: { title: string }) {
  return (
    <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
      <div className="text-[14px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
        {title}
      </div>
      <div className="text-[10px]/[normal] box-border text-[#8B5CF6] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
        View all
      </div>
    </div>
  );
}

export default function CapabilitiesRightPanel() {
  return (
    <div className="box-border w-[280px] shrink-0 h-full flex flex-col gap-[14px] p-[16px_14px] justify-start items-start bg-[var(--ag-right-bg)] [border-width:0px_0px_0px_1px] [border-style:solid] [border-color:var(--ag-divider)] overflow-y-auto">
      {/* Categories */}
      <div className="box-border w-full h-fit shrink-0 flex flex-col gap-[12px] p-[14px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]">
        <CardHeader title="Categories" />
        {CATEGORIES.map((c) => (
          <div key={c.label} className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
            <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-[8px] justify-start items-center">
              <div
                className="box-border w-[20px] shrink-0 h-[20px] flex flex-row gap-0 justify-center items-center rounded-[5px]"
                style={{ backgroundColor: c.color }}
              >
                <div className="text-[11px]/[normal] box-border text-[#FFFFFF] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                  {c.icon}
                </div>
              </div>
              <div className="text-[11px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                {c.label}
              </div>
            </div>
            <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-0 p-[3px_6px] justify-start items-start bg-[#202039] rounded-[4px]">
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                {c.count}
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Top capabilities */}
      <div className="box-border w-full h-fit shrink-0 flex flex-col gap-[12px] p-[14px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]">
        <CardHeader title="Top Capabilities" />
        {TOP.map((t) => (
          <div key={t.rank} className="box-border w-full h-fit shrink-0 flex flex-row gap-[8px] justify-start items-center">
            <div className="text-[11px]/[normal] box-border text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
              {t.rank}
            </div>
            <div
              className="box-border w-[28px] shrink-0 h-[28px] flex flex-row gap-0 justify-center items-center rounded-[7px]"
              style={{ backgroundColor: t.color }}
            >
              <div className="text-[14px]/[normal] box-border text-[#FFFFFF] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                {t.icon}
              </div>
            </div>
            <div className="box-border w-fit shrink-0 h-fit flex flex-col gap-[2px] justify-start items-start">
              <div className="text-[10px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
                {t.name}
              </div>
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                {t.stats}
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Recently added */}
      <div className="box-border w-full h-fit shrink-0 flex flex-col gap-[12px] p-[14px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]">
        <CardHeader title="Recently Added" />
        {RECENT.map((r) => (
          <div key={r.name} className="box-border w-full h-fit shrink-0 flex flex-row gap-[9px] justify-start items-center">
            <div
              className="box-border w-[32px] shrink-0 h-[32px] flex flex-row gap-0 justify-center items-center rounded-[7px]"
              style={{ backgroundColor: r.color }}
            >
              <div className="text-[15px]/[normal] box-border text-[#FFFFFF] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                {r.icon}
              </div>
            </div>
            <div className="box-border w-fit shrink-0 h-fit flex flex-col gap-[2px] justify-start items-start">
              <div className="text-[10px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
                {r.name}
              </div>
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                {r.time}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
