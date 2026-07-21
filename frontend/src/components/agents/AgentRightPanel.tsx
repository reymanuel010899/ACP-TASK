export default function AgentRightPanel() {
  return (
    <div
      className="box-border w-[300px] shrink-0 h-full flex flex-col gap-[20px] p-[24px_20px] justify-start items-start bg-[var(--ag-right-bg)] [border-width:0px_0px_0px_1px] [border-style:solid] [border-color:var(--ag-divider)] overflow-y-auto"
    >
      <div
        className="box-border w-full h-fit shrink-0 flex flex-col gap-[13px] p-[16px] justify-start items-start bg-[var(--ag2-panel)] [border:1px_solid_var(--ag2-border)] rounded-[9px]"
      >
        <div
          className="text-[15px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]"
        >
          Agent Status
        </div>
        <div
          className="box-border w-fit h-fit shrink-0 flex flex-row gap-[9px] justify-start items-center"
        >
          <div
            className="box-border w-[24px] shrink-0 h-[24px] bg-[#073C31] rounded-full"
          ></div>
          <div
            className="box-border w-fit shrink-0 h-fit flex flex-col gap-[3px] justify-start items-start"
          >
            <div
              className="text-[12px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]"
            >
              Active
            </div>
            <div
              className="text-[10px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
            >
              Available for new tasks
            </div>
          </div>
        </div>
        <div
          className="box-border w-full h-fit shrink-0 flex flex-col gap-[4px] p-[8px_0px_0px_0px] justify-start items-start [border-width:1px_0px_0px_0px] [border-style:solid] [border-color:var(--ag2-border)]"
        >
          <div
            className="text-[10px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
          >
            Current Load
          </div>
          <div
            className="text-[13px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]"
          >
            3 / 10 tasks
          </div>
        </div>
        <div
          className="box-border w-full h-fit shrink-0 flex flex-col gap-[4px] p-[8px_0px_0px_0px] justify-start items-start [border-width:1px_0px_0px_0px] [border-style:solid] [border-color:var(--ag2-border)]"
        >
          <div
            className="text-[10px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
          >
            Queue
          </div>
          <div
            className="text-[13px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]"
          >
            2 tasks
          </div>
        </div>
        <div
          className="box-border w-full h-fit shrink-0 flex flex-col gap-[4px] p-[8px_0px_0px_0px] justify-start items-start [border-width:1px_0px_0px_0px] [border-style:solid] [border-color:var(--ag2-border)]"
        >
          <div
            className="text-[10px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
          >
            Availability
          </div>
          <div
            className="text-[13px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]"
          >
            90%
          </div>
        </div>
        <div
          className="box-border w-full h-fit shrink-0 flex flex-col gap-[4px] p-[8px_0px_0px_0px] justify-start items-start [border-width:1px_0px_0px_0px] [border-style:solid] [border-color:var(--ag2-border)]"
        >
          <div
            className="text-[10px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
          >
            Response Time
          </div>
          <div
            className="text-[13px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]"
          >
            2 min avg
          </div>
        </div>
        <div
          className="box-border w-full h-fit shrink-0 flex flex-col gap-[4px] p-[8px_0px_0px_0px] justify-start items-start [border-width:1px_0px_0px_0px] [border-style:solid] [border-color:var(--ag2-border)]"
        >
          <div
            className="text-[10px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
          >
            Location
          </div>
          <div
            className="text-[13px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]"
          >
            ◉ Global
          </div>
        </div>
        <div
          className="box-border w-full h-fit shrink-0 flex flex-row gap-0 p-[11px_10px] justify-center items-start bg-[#5D20DC] rounded-[6px]"
        >
          <div
            className="text-[12px]/[normal] box-border text-[#F4F2FF] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]"
          >
            ✣ Assign New Task
          </div>
        </div>
      </div>
      <div
        className="box-border w-full h-[230px] shrink-0 flex flex-col gap-[9px] p-[16px] justify-start items-start bg-[var(--ag2-panel)] [border:1px_solid_var(--ag2-border)] rounded-[9px]"
      >
        <div
          className="text-[15px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]"
        >
          Top Skills
        </div>
        <div
          className="box-border w-full [flex:1_1_0] relative"
        >
          <svg
            viewBox="0 0 140 140"
            preserveAspectRatio="none"
            xmlns="http://www.w3.org/2000/svg"
            className="box-border w-[140px] h-[140px] [transform:rotate(18deg)] [transform-origin:top_left] absolute left-[40px] top-[6px] overflow-visible [z-index:0]"
          >
            <path
              d="M70 0l66.57396 48.36881-25.42899 78.26238-82.28994 0-25.42899-78.26238 66.57396-48.36881z"
              fill="#21134122"
            ></path>
            <path
              d="M70.29389-0.40451l66.86785 48.58234-25.6535 78.95336-83.01648 0-25.6535-78.95336 67.16174-48.79586 0.29389 0.21352z m-0.58778 0.80902l0.29389-0.40451 0.29389 0.40451-66.57395 48.3688-0.2939-0.4045 0.47553-0.15451 25.42899 78.26238-0.47553 0.15451 0-0.5 82.28994 0 0 0.5-0.47553-0.15451 25.42899-78.26238 0.47553 0.15451-0.2939 0.4045-66.57395-48.3688z"
              fill="#6332B6"
              fillRule="evenodd"
            ></path>
          </svg>
          <svg
            viewBox="0 0 102 102"
            preserveAspectRatio="none"
            xmlns="http://www.w3.org/2000/svg"
            className="box-border w-[102px] h-[102px] [transform:rotate(18deg)] [transform-origin:top_left] absolute left-[59px] top-[25px] overflow-visible [z-index:1]"
          >
            <path
              d="M51 0l48.50388 35.24014-18.52683 57.01973-59.9541 0-18.52683-57.01973 48.50388-35.24014z"
              fill="#21134122"
            ></path>
            <path
              d="M51.29389-0.40451l48.79778 35.45366-18.75135 57.71072-60.68064 0-18.75135-57.71072 49.09167-35.66718 0.29389 0.21352z m-0.58778 0.80902l0.29389-0.40451 0.29389 0.40451-48.50388 35.24013-0.29389-0.40451 0.47553-0.1545 18.52683 57.01972-0.47553 0.15452 0-0.5 59.9541 0 0 0.5-0.47552-0.15452 18.52683-57.01972 0.47552 0.15451-0.29389 0.4045-48.50388-35.24013z"
              fill="#6332B6"
              fillRule="evenodd"
            ></path>
          </svg>
          <svg
            viewBox="0 0 64 64"
            preserveAspectRatio="none"
            xmlns="http://www.w3.org/2000/svg"
            className="box-border w-[64px] h-[64px] [transform:rotate(18deg)] [transform-origin:top_left] absolute left-[78px] top-[44px] overflow-visible [z-index:2]"
          >
            <path
              d="M32 0l30.43381 22.11146-11.62468 35.77708-37.61826 0-11.62468-35.77708 30.43381-22.11146z"
              fill="#21134122"
            ></path>
            <path
              d="M32.29389-0.40451l30.7277 22.32498-11.84919 36.46807-38.3448 0-11.84919-36.46807 31.02159-22.5385 0.29389 0.21352z m-0.58778 0.80902l0.29389-0.40451 0.29389 0.40451-30.43381 22.11146-0.29389-0.40451 0.47553-0.15451 11.62468 35.77708-0.47553 0.15451 0-0.5 37.61826 0 0 0.5-0.47553-0.1545 11.62468-35.77709 0.47553 0.15451-0.29389 0.40451-30.43381-22.11146z"
              fill="#6332B6"
              fillRule="evenodd"
            ></path>
          </svg>
          <svg
            viewBox="0 0 110 115"
            preserveAspectRatio="none"
            xmlns="http://www.w3.org/2000/svg"
            className="box-border w-[110px] h-[115px] [transform:rotate(18deg)] [transform-origin:top_left] absolute left-[55px] top-[14px] overflow-visible [z-index:3]"
          >
            <path
              d="M55 0l52.30811 39.73152-19.97992 64.28696-64.65638 0-19.97992-64.28696 52.30811-39.73152z"
              fill="#6D28D955"
            ></path>
            <path
              d="M55.60487-0.79633l52.86617 40.15541-20.40646 65.6594-66.12916 0-20.40646-65.6594 53.47104-40.61484 0.60487 0.45943z m-1.20974 1.59266l0.60487-0.79633 0.60487 0.79633-52.30811 39.73152-0.60487-0.79633 0.95494-0.29679 19.97992 64.28696-0.95494 0.29679 0-1 64.65638 0 0 1-0.95495-0.29679 19.97992-64.28696 0.95495 0.29679-0.60487 0.79633-52.30811-39.73152z"
              fill="#A855F7"
              fillRule="evenodd"
            ></path>
          </svg>
          <div
            className="text-[9px]/[normal] box-border absolute left-0 top-0 text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap] [z-index:4]"
          >
            Infrastructure 98%
          </div>
          <div
            className="text-[9px]/[normal] box-border absolute left-0 top-0 text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap] [z-index:5]"
          >
            Automation 95%
          </div>
          <div
            className="text-[9px]/[normal] box-border absolute left-0 top-0 text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap] [z-index:6]"
          >
            Security 92%
          </div>
          <div
            className="text-[9px]/[normal] box-border absolute left-0 top-0 text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap] [z-index:7]"
          >
            Monitoring 90%
          </div>
          <div
            className="text-[9px]/[normal] box-border absolute left-0 top-0 text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap] [z-index:8]"
          >
            Cloud 97%
          </div>
        </div>
      </div>
      <div
        className="box-border w-full [flex:1_1_0] flex flex-col gap-[11px] p-[16px] justify-start items-start bg-[var(--ag2-panel)] [border:1px_solid_var(--ag2-border)] rounded-[9px]"
      >
        <div
          className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-start"
        >
          <div
            className="text-[15px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]"
          >
            Certifications
          </div>
          <div
            className="text-[11px]/[normal] box-border text-[#B267FF] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
          >
            View all
          </div>
        </div>
        <div
          className="box-border w-full h-fit shrink-0 flex flex-row gap-[9px] justify-start items-center"
        >
          <div
            className="box-border w-[29px] shrink-0 h-[29px] flex flex-row gap-0 justify-center items-center bg-[#1F1931] [border:1px_solid_#6A3AA8] rounded-[15px]"
          >
            <div
              className="text-[9px]/[normal] box-border text-[#C084FC] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]"
            >
              aws
            </div>
          </div>
          <div
            className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[2px] justify-start items-start"
          >
            <div
              className="text-[10px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]"
            >
              AWS Solutions Architect
            </div>
            <div
              className="text-[9px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
            >
              Professional
            </div>
          </div>
          <div
            className="text-[9px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
          >
            2024
          </div>
        </div>
        <div
          className="box-border w-full h-fit shrink-0 flex flex-row gap-[9px] justify-start items-center"
        >
          <div
            className="box-border w-[29px] shrink-0 h-[29px] flex flex-row gap-0 justify-center items-center bg-[#1F1931] [border:1px_solid_#6A3AA8] rounded-[15px]"
          >
            <div
              className="text-[9px]/[normal] box-border text-[#C084FC] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]"
            >
              ✦
            </div>
          </div>
          <div
            className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[2px] justify-start items-start"
          >
            <div
              className="text-[10px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]"
            >
              Certified Kubernetes Administrator
            </div>
            <div
              className="text-[9px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
            >
              CKA
            </div>
          </div>
          <div
            className="text-[9px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
          >
            2024
          </div>
        </div>
        <div
          className="box-border w-full h-fit shrink-0 flex flex-row gap-[9px] justify-start items-center"
        >
          <div
            className="box-border w-[29px] shrink-0 h-[29px] flex flex-row gap-0 justify-center items-center bg-[#1F1931] [border:1px_solid_#6A3AA8] rounded-[15px]"
          >
            <div
              className="text-[9px]/[normal] box-border text-[#C084FC] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]"
            >
              ✥
            </div>
          </div>
          <div
            className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[2px] justify-start items-start"
          >
            <div
              className="text-[10px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]"
            >
              HashiCorp Terraform Associate
            </div>
            <div
              className="text-[9px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
            >
              003
            </div>
          </div>
          <div
            className="text-[9px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
          >
            2023
          </div>
        </div>
      </div>
    </div>
  );
}
