/**
 * Task Detail — center column (Pencil "Task Detail Main" design).
 *
 * Dashboard `--ag-*` design language: structural card/border/text colors go
 * through the theme vars; accent + status hues stay literal, matching the
 * sibling dashboard components.
 */

const TIMELINE: { icon: string; iconColor: string; label: string; date: string }[] = [
  { icon: "✓", iconColor: "#22C55E", label: "Created", date: "May 20 · 09:15 AM" },
  { icon: "✓", iconColor: "#22C55E", label: "Assigned", date: "May 20 · 09:15 AM" },
  { icon: "◉", iconColor: "#8B5CF6", label: "In Progress", date: "May 20 · 09:15 AM" },
  { icon: "□", iconColor: "var(--ag-text-secondary)", label: "Review", date: "Pending" },
  { icon: "□", iconColor: "var(--ag-text-secondary)", label: "Completed", date: "Pending" },
];

const TABS = ["Overview", "Messages 4", "Files 7", "Activity", "Approvals 2", "Payments", "Timeline"];

const DETAILS: { key: string; value: string }[] = [
  { key: "Task ID", value: "T-8432" },
  { key: "Category", value: "Design" },
  { key: "Subcategory", value: "UI/UX Design" },
  { key: "Estimated Budget", value: "$1,200 – $1,800" },
  { key: "Deadline", value: "May 29, 2024 · 5:00 PM" },
  { key: "Work Type", value: "Fixed Price" },
  { key: "Visibility", value: "Private" },
  { key: "Created By", value: "Rey Ferreras" },
];

const REQUIREMENTS = [
  "Modern and clean design",
  "Fully responsive (desktop, tablet, mobile)",
  "Use our brand colors and style guide",
  "Include sections: Hero, Features, How it works, Pricing, CTA, FAQ",
  "Optimized for conversion and performance",
];

const ACTIVITY: { user: string; detail: string }[] = [
  { user: "UI/UX Designer", detail: "uploaded 3 new files" },
  { user: "Ana Martinez", detail: "requested approval" },
  { user: "System", detail: "Task moved to In Progress" },
  { user: "UI/UX Designer", detail: "was assigned to this task" },
];

const ATTACHMENTS: { icon: string; name: string; detail: string }[] = [
  { icon: "▰", name: "References", detail: "3 files" },
  { icon: "●", name: "Landing Page Wireframe.fig", detail: "Figma File · 2.4 MB" },
  { icon: "▣", name: "Style Guide.pdf", detail: "PDF Document · 4.8 MB" },
  { icon: "▥", name: "Assets.zip", detail: "ZIP Archive · 12.6 MB" },
  { icon: "▧", name: "Moodboard.png", detail: "Image · 1.3 MB" },
];

const TAGS = ["Design", "Web Development", "UI/UX"];

export default function TaskDetailContent() {
  return (
    <div className="box-border w-full [flex:1_1_0] flex flex-col gap-[10px] p-[8px_16px_16px_16px] justify-start items-start">
      {/* Header card */}
      <div className="box-border w-full h-[306px] shrink-0 flex flex-col gap-[10px] p-[16px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]">
        <div className="text-[11px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
          ‹ Back to Tasks
        </div>
        <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-start">
          {/* Identity */}
          <div className="box-border w-fit shrink-0 h-fit flex flex-col gap-[8px] justify-start items-start">
            <div className="box-border w-fit h-fit shrink-0 flex flex-row gap-[10px] justify-start items-center">
              <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-0 p-[6px_9px] justify-start items-start bg-[#172752] rounded-[5px]">
                <div className="text-[10px]/[normal] box-border text-[#3B82F6] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
                  In Progress
                </div>
              </div>
              <div className="text-[11px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                T-8432
              </div>
            </div>
            <div className="text-[22px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
              Redesign landing page for Console website
            </div>
            <div className="text-[12px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
              Create a modern, high-converting landing page for our new product launch.
            </div>
            <div className="box-border w-fit h-fit shrink-0 flex flex-row gap-[6px] justify-start items-start">
              {TAGS.map((t) => (
                <div key={t} className="box-border w-fit shrink-0 h-fit flex flex-row gap-0 p-[5px_9px] justify-start items-start bg-[var(--ag-input-bg)] rounded-[5px]">
                  <div className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                    {t}
                  </div>
                </div>
              ))}
            </div>
          </div>
          {/* Actions */}
          <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-[10px] justify-start items-start">
            {[
              { label: "••• More", primary: false },
              { label: "⌘ Share", primary: false },
              { label: "✎ Edit Task", primary: true },
            ].map((b) => (
              <div
                key={b.label}
                className={`box-border w-fit shrink-0 h-fit flex flex-row gap-0 p-[10px_13px] justify-start items-start rounded-[6px] ${
                  b.primary
                    ? "bg-[var(--ag-purple)] [border:1px_solid_var(--ag-purple)]"
                    : "bg-[var(--ag-input-bg)] [border:1px_solid_#30304A]"
                }`}
              >
                <div className="text-[11px]/[normal] box-border text-[#FFFFFF] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
                  {b.label}
                </div>
              </div>
            ))}
          </div>
        </div>
        {/* Timeline */}
        <div className="box-border w-full [flex:1_1_0] flex flex-row gap-0 p-[16px_20px] justify-between items-center bg-[var(--ag-input-bg)] [border:1px_solid_var(--ag2-border)] rounded-[7px]">
          {TIMELINE.map((s) => (
            <div key={s.label} className="box-border w-fit shrink-0 h-fit flex flex-col gap-[6px] justify-start items-center">
              <div
                className="text-[20px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
                style={{ color: s.iconColor }}
              >
                {s.icon}
              </div>
              <div className="text-[10px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
                {s.label}
              </div>
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                {s.date}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Tabs */}
      <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[25px] p-[0px_4px_8px_4px] justify-start items-start [border-width:0px_0px_1px_0px] [border-style:solid] [border-color:var(--ag2-border)]">
        {TABS.map((tab, i) => (
          <div
            key={tab}
            className={
              i === 0
                ? "text-[11px]/[normal] box-border text-[#8B5CF6] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]"
                : "text-[11px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
            }
          >
            {tab}
          </div>
        ))}
      </div>

      {/* Overview panels */}
      <div className="box-border w-full h-[315px] shrink-0 flex flex-row gap-[8px] justify-start items-start">
        {/* Task Details */}
        <div className="box-border w-[260px] shrink-0 h-full flex flex-col gap-[13px] p-[14px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]">
          <div className="text-[14px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
            Task Details
          </div>
          {DETAILS.map((d) => (
            <div key={d.key} className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-start">
              <div className="text-[10px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                {d.key}
              </div>
              <div className="text-[10px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                {d.value}
              </div>
            </div>
          ))}
        </div>
        {/* Description */}
        <div className="box-border [flex:1_1_0] h-full flex flex-col gap-[12px] p-[14px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]">
          <div className="text-[14px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
            Description
          </div>
          <div className="text-[11px]/[17px] box-border w-full text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left">
            We need a new landing page for Console to highlight our platform capabilities and drive
            sign-ups for our beta launch.
          </div>
          <div className="text-[12px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
            Requirements
          </div>
          {REQUIREMENTS.map((r) => (
            <div key={r} className="box-border w-fit h-fit shrink-0 flex flex-row gap-[7px] justify-start items-start">
              <div className="text-[10px]/[normal] box-border text-[#8B5CF6] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                ●
              </div>
              <div className="text-[10px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                {r}
              </div>
            </div>
          ))}
          <div className="text-[12px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
            References
          </div>
          <div className="box-border w-fit h-fit shrink-0 flex flex-row gap-[8px] justify-start items-start">
            {["▣ Brand Guidelines.pdf", "▣ Current Website.pdf"].map((ref) => (
              <div key={ref} className="box-border w-fit shrink-0 h-fit flex flex-row gap-0 p-[8px_9px] justify-start items-start bg-[var(--ag-input-bg)] rounded-[5px]">
                <div className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                  {ref}
                </div>
              </div>
            ))}
          </div>
        </div>
        {/* Activity feed */}
        <div className="box-border w-[260px] shrink-0 h-full flex flex-col gap-[12px] p-[14px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]">
          <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-start">
            <div className="text-[14px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
              Activity Feed
            </div>
            <div className="text-[10px]/[normal] box-border text-[#8B5CF6] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
              View all
            </div>
          </div>
          {ACTIVITY.map((a, i) => (
            <div key={i} className="box-border w-fit h-fit shrink-0 flex flex-row gap-[8px] justify-start items-start">
              <div className="box-border w-[26px] shrink-0 h-[26px] bg-[var(--ag-purple)] rounded-full"></div>
              <div className="box-border w-fit shrink-0 h-fit flex flex-col gap-[3px] justify-start items-start">
                <div className="text-[10px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
                  {a.user}
                </div>
                <div className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                  {a.detail}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Attachments */}
      <div className="box-border w-full [flex:1_1_0] flex flex-col gap-[10px] p-[14px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]">
        <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-start">
          <div className="text-[14px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
            Attachments (7)
          </div>
          <div className="text-[14px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            ▦ ☷
          </div>
        </div>
        <div className="box-border w-full h-[78px] shrink-0 flex flex-row gap-[10px] justify-start items-start">
          {ATTACHMENTS.map((a) => (
            <div key={a.name} className="box-border [flex:1_1_0] h-full flex flex-col gap-[7px] p-[12px] justify-start items-start bg-[var(--ag-input-bg)] [border:1px_solid_var(--ag-card-border)] rounded-[6px]">
              <div className="text-[20px]/[normal] box-border text-[#8B5CF6] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                {a.icon}
              </div>
              <div className="text-[10px]/[normal] box-border w-full text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [overflow:hidden] [text-overflow:ellipsis] [white-space:nowrap]">
                {a.name}
              </div>
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                {a.detail}
              </div>
            </div>
          ))}
          <div className="box-border [flex:1_1_0] h-full flex flex-col gap-[7px] p-[12px] justify-start items-start bg-[var(--ag-input-bg)] [border:1px_solid_#52516A] rounded-[6px]">
            <div className="text-[20px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
              ＋
            </div>
            <div className="text-[10px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
              Upload File
            </div>
            <div className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
              or drag and drop
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
