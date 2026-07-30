/**
 * Task Detail — right rail (Pencil "Task Detail Right Panel" design): task
 * summary with progress, participants, approvals, and task info. Same `--ag-*`
 * token conventions as TaskDetailContent.
 */

const SUMMARY: { key: string; value: string; color: string }[] = [
  { key: "Status", value: "◌ In Progress", color: "#8B5CF6" },
  { key: "Priority", value: "↟ High", color: "#EF4444" },
  { key: "Time Tracked", value: "12h 45m", color: "var(--ag-text)" },
  { key: "Budget", value: "$1,500.00", color: "var(--ag-text)" },
];

type Participant = { name: string; role: string; state: string; stateColor: string };
const PARTICIPANTS: Participant[] = [
  { name: "UI/UX Designer", role: "Service Provider", state: "● Active", stateColor: "#22C55E" },
  { name: "Rey Ferreras", role: "Task Owner", state: "● Active", stateColor: "#22C55E" },
  { name: "Ana Martinez", role: "Reviewer", state: "● Pending", stateColor: "#F59E0B" },
];

const APPROVALS: { name: string; detail: string }[] = [
  { name: "Design Review", detail: "Requested by UI/UX Designer" },
  { name: "Final Approval", detail: "Requested by UI/UX Designer" },
];

const INFO: { key: string; value: string; color: string }[] = [
  { key: "Contract", value: "C-884 ›", color: "var(--ag-text)" },
  { key: "Payment Method", value: "ESCROW", color: "#22C55E" },
  { key: "Milestone", value: "1 of 3 ◯", color: "var(--ag-text)" },
  { key: "Auto Close", value: "May 29, 2024", color: "var(--ag-text)" },
];

const CARD =
  "box-border w-full h-fit shrink-0 flex flex-col gap-[12px] p-[14px] justify-start items-start bg-[var(--ag-card)] [border:1px_solid_var(--ag-card-border)] rounded-[8px]";
const TITLE =
  "text-[14px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]";
const KEY =
  "text-[10px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]";

export default function TaskDetailRightPanel() {
  return (
    <div className="box-border w-[280px] shrink-0 h-full flex flex-col gap-[12px] p-[14px] justify-start items-start bg-[var(--ag-right-bg)] [border-width:0px_0px_0px_1px] [border-style:solid] [border-color:var(--ag-divider)] overflow-y-auto">
      {/* Task summary */}
      <div className={CARD}>
        <div className={TITLE}>Task Summary</div>
        {SUMMARY.map((s) => (
          <div key={s.key} className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-start">
            <div className={KEY}>{s.key}</div>
            <div
              className="text-[10px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]"
              style={{ color: s.color }}
            >
              {s.value}
            </div>
          </div>
        ))}
        <div className={KEY}>Progress 65%</div>
        <div className="box-border w-full h-[5px] shrink-0 bg-[var(--ag-input-bg)] rounded-[3px] overflow-hidden">
          <div className="box-border w-[65%] h-full bg-[var(--ag-purple)] rounded-[3px]"></div>
        </div>
      </div>

      {/* Participants */}
      <div className={CARD}>
        <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-start">
          <div className={TITLE}>Participants</div>
          <div className="text-[10px]/[normal] box-border text-[#8B5CF6] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            Manage
          </div>
        </div>
        {PARTICIPANTS.map((p) => (
          <div key={p.name} className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
            <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-[8px] justify-start items-center">
              <div className="box-border w-[27px] shrink-0 h-[27px] bg-[var(--ag-purple)] rounded-full"></div>
              <div className="box-border w-fit shrink-0 h-fit flex flex-col gap-[2px] justify-start items-start">
                <div className="text-[10px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
                  {p.name}
                </div>
                <div className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                  {p.role}
                </div>
              </div>
            </div>
            <div
              className="text-[9px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
              style={{ color: p.stateColor }}
            >
              {p.state}
            </div>
          </div>
        ))}
        <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 p-[9px_8px] justify-center items-start bg-[var(--ag-input-bg)] rounded-[6px]">
          <div className="text-[10px]/[normal] box-border text-[#8B5CF6] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            + Add Participant
          </div>
        </div>
      </div>

      {/* Approvals */}
      <div className={CARD}>
        <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-start">
          <div className={TITLE}>Approvals (2)</div>
          <div className="text-[10px]/[normal] box-border text-[#8B5CF6] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
            View all
          </div>
        </div>
        {APPROVALS.map((a) => (
          <div key={a.name} className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-start">
            <div className="box-border w-fit shrink-0 h-fit flex flex-col gap-[2px] justify-start items-start">
              <div className="text-[10px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
                {a.name}
              </div>
              <div className="text-[9px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                {a.detail}
              </div>
            </div>
            <div className="text-[9px]/[normal] box-border text-[#F59E0B] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
              Pending
            </div>
          </div>
        ))}
      </div>

      {/* Task info */}
      <div className={CARD}>
        <div className={TITLE}>Task Info</div>
        {INFO.map((i) => (
          <div key={i.key} className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-start">
            <div className={KEY}>{i.key}</div>
            <div
              className="text-[10px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
              style={{ color: i.color }}
            >
              {i.value}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
