/**
 * Integrations — right rail (matches the provided Integrations screenshot):
 * integration-health donut (canvas), recent activity, and category list.
 * Dashboard `--ag-*` tokens for structure; accent/brand hues literal.
 */

import DonutChart, { type DonutSegment } from "@/components/charts/DonutChart";

const HEALTH: (DonutSegment & { count: string; pct: string })[] = [
  { label: "Healthy", value: 28, count: "28", pct: "66%", color: "#22C55E" },
  { label: "Warning", value: 6, count: "6", pct: "14%", color: "#F59E0B" },
  { label: "Error", value: 2, count: "2", pct: "5%", color: "#EF4444" },
  { label: "Disconnected", value: 6, count: "6", pct: "14%", color: "#94A3B8" },
];

const ACTIVITY: { glyph: string; color: string; title: string; by: string; time: string }[] = [
  { glyph: "#", color: "#E01E5A", title: "Slack integration was updated", by: "by Ana Martinez", time: "2h ago" },
  { glyph: "◉", color: "#E6E1EE", title: "GitHub repository synced", by: "by Rey Ferreras", time: "5h ago" },
  { glyph: "aws", color: "#FF9900", title: "AWS credentials refreshed", by: "by System", time: "1d ago" },
  { glyph: "S", color: "#635BFF", title: "Stripe webhook connected", by: "by Sofia Rodriguez", time: "2d ago" },
  { glyph: "✳", color: "#FF4A00", title: "New Zap created", by: "by Ana Martinez", time: "3d ago" },
];

const CATEGORIES: { icon: string; color: string; label: string; count: string; active?: boolean }[] = [
  { icon: "▣", color: "#8B5CF6", label: "All Integrations", count: "42", active: true },
  { icon: "◉", color: "#3B82F6", label: "Communication", count: "6" },
  { icon: "▤", color: "#22C55E", label: "Development", count: "7" },
  { icon: "☁", color: "#06B6D4", label: "Cloud", count: "8" },
  { icon: "▦", color: "#F59E0B", label: "Productivity", count: "6" },
  { icon: "$", color: "#635BFF", label: "Payments", count: "4" },
  { icon: "◆", color: "#EC4899", label: "Marketing", count: "4" },
  { icon: "●", color: "#94A3B8", label: "Other", count: "7" },
];

const TITLE =
  "text-[14px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]";
const VIEWALL =
  "text-[10px]/[normal] box-border text-[#C084FC] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]";

function BrandTile({ glyph, color }: { glyph: string; color: string }) {
  return (
    <div className="box-border w-[30px] shrink-0 h-[30px] flex flex-row gap-0 justify-center items-center bg-[var(--ag-input-bg)] [border:1px_solid_var(--ag-card-border)] rounded-[7px]">
      <div className="text-[12px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-bold text-center [white-space:nowrap]" style={{ color }}>
        {glyph}
      </div>
    </div>
  );
}

export default function IntegrationsRightPanel() {
  return (
    <div className="box-border w-[320px] shrink-0 h-full flex flex-col gap-[12px] p-[14px] justify-start items-start bg-[var(--ag-right-bg)] [border-width:0px_0px_0px_1px] [border-style:solid] [border-color:var(--ag-divider)] overflow-y-auto">
      {/* Integration health */}
      <div className="box-border w-full shrink-0 flex flex-col gap-[12px] p-[14px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]">
        <div className={TITLE}>Integration Health</div>
        <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[16px] justify-start items-center">
          <DonutChart data={HEALTH} size={104} thickness={16}>
            <div className="text-[20px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-center [white-space:nowrap]">
              42
            </div>
            <div className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-center [white-space:nowrap]">
              Total
            </div>
          </DonutChart>
          <div className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[9px] justify-start items-start">
            {HEALTH.map((h) => (
              <div key={h.label} className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
                <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-[7px] justify-start items-center">
                  <div className="box-border w-[8px] shrink-0 h-[8px] rounded-full" style={{ backgroundColor: h.color }}></div>
                  <div className="text-[10px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                    {h.label}
                  </div>
                </div>
                <div className="text-[10px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                  {h.count} ({h.pct})
                </div>
              </div>
            ))}
          </div>
        </div>
        <div className="box-border w-full h-[34px] shrink-0 flex flex-row gap-0 justify-center items-center bg-[var(--ag-input-bg)] [border:1px_solid_var(--ag-card-border)] rounded-[6px]">
          <div className="text-[11px]/[normal] box-border text-[#C084FC] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
            View Health Report
          </div>
        </div>
      </div>

      {/* Recent activity */}
      <div className="box-border w-full shrink-0 flex flex-col gap-[11px] p-[14px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]">
        <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
          <div className={TITLE}>Recent Activity</div>
          <div className={VIEWALL}>View all</div>
        </div>
        {ACTIVITY.map((a) => (
          <div key={a.title} className="box-border w-full h-fit shrink-0 flex flex-row gap-[9px] justify-start items-center">
            <BrandTile glyph={a.glyph} color={a.color} />
            <div className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[3px] justify-start items-start">
              <div className="text-[10px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [overflow:hidden] [text-overflow:ellipsis] [white-space:nowrap]">
                {a.title}
              </div>
              <div className="text-[8px]/[normal] box-border text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                {a.by}
              </div>
            </div>
            <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-[6px] justify-end items-center">
              <div className="text-[8px]/[normal] box-border text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                {a.time}
              </div>
              <div className="text-[10px]/[normal] box-border text-[#22C55E] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">●</div>
            </div>
          </div>
        ))}
      </div>

      {/* Categories */}
      <div className="box-border w-full [flex:1_1_0] flex flex-col gap-[8px] p-[14px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]">
        <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
          <div className={TITLE}>Categories</div>
          <div className={VIEWALL}>View all</div>
        </div>
        {CATEGORIES.map((c) => (
          <div
            key={c.label}
            className={`box-border w-full h-fit shrink-0 flex flex-row gap-0 p-[6px_8px] justify-between items-center rounded-[6px] ${
              c.active ? "bg-[var(--ag-input-bg)]" : ""
            }`}
          >
            <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-[9px] justify-start items-center">
              <div className="box-border w-[9px] shrink-0 h-[9px] rounded-[3px]" style={{ backgroundColor: c.color }}></div>
              <div className="text-[11px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                {c.label}
              </div>
            </div>
            <div className="text-[10px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
              {c.count}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
