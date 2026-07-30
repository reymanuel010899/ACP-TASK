/**
 * Overview tab of the agent detail page. Extracted verbatim from the original
 * AgentContent so the tab container can switch between panels. Presentational
 * mock data (hybrid: real domain fields, mock values).
 */
export default function AgentOverviewTab() {
  return (
    <>
      <div
        className="box-border w-full h-[270px] shrink-0 flex flex-row gap-[12px] justify-start items-start"
      >
        <div
          className="box-border w-[370px] shrink-0 h-full flex flex-col gap-[10px] p-[16px] justify-start items-start bg-[var(--ag2-panel)] [border:1px_solid_var(--ag2-border)] rounded-[9px]"
        >
          <div
            className="text-[15px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]"
          >
            About this Agent
          </div>
          <div
            className="text-[12px]/[normal] box-border w-[338px] text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left"
          >
            Specialized in cloud infrastructure, CI/CD pipelines, and automation. Expert in AWS,
            Kubernetes, Terraform, Docker and modern DevOps practices.
          </div>
          <div
            className="box-border w-full h-fit shrink-0 flex flex-row gap-[22px] justify-start items-start"
          >
            <div
              className="box-border [flex:1_1_0] h-fit flex flex-col gap-[12px] justify-start items-start"
            >
              <div
                className="box-border w-full h-fit shrink-0 flex flex-col gap-[3px] justify-start items-start"
              >
                <div
                  className="text-[10px]/[normal] box-border text-[var(--ag2-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
                >
                  Agent ID
                </div>
                <div
                  className="text-[12px]/[normal] box-border text-[var(--ag2-strong)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]"
                >
                  agt_devops_001
                </div>
              </div>
              <div
                className="box-border w-full h-fit shrink-0 flex flex-col gap-[3px] justify-start items-start"
              >
                <div
                  className="text-[10px]/[normal] box-border text-[var(--ag2-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
                >
                  Provider
                </div>
                <div
                  className="text-[12px]/[normal] box-border text-[var(--ag2-strong)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]"
                >
                  Console Labs
                </div>
              </div>
              <div
                className="box-border w-full h-fit shrink-0 flex flex-col gap-[3px] justify-start items-start"
              >
                <div
                  className="text-[10px]/[normal] box-border text-[var(--ag2-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
                >
                  Response Time
                </div>
                <div
                  className="text-[12px]/[normal] box-border text-[var(--ag2-strong)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]"
                >
                  2 min avg
                </div>
              </div>
            </div>
            <div
              className="box-border [flex:1_1_0] h-fit flex flex-col gap-[12px] justify-start items-start"
            >
              <div
                className="box-border w-full h-fit shrink-0 flex flex-col gap-[3px] justify-start items-start"
              >
                <div
                  className="text-[10px]/[normal] box-border text-[var(--ag2-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
                >
                  Type
                </div>
                <div
                  className="text-[12px]/[normal] box-border text-[var(--ag2-strong)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]"
                >
                  AI Agent
                </div>
              </div>
              <div
                className="box-border w-full h-fit shrink-0 flex flex-col gap-[3px] justify-start items-start"
              >
                <div
                  className="text-[10px]/[normal] box-border text-[var(--ag2-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
                >
                  Member Since
                </div>
                <div
                  className="text-[12px]/[normal] box-border text-[var(--ag2-strong)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]"
                >
                  Jan 12, 2024
                </div>
              </div>
              <div
                className="box-border w-full h-fit shrink-0 flex flex-col gap-[3px] justify-start items-start"
              >
                <div
                  className="text-[10px]/[normal] box-border text-[var(--ag2-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
                >
                  Languages
                </div>
                <div
                  className="text-[12px]/[normal] box-border text-[var(--ag2-strong)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]"
                >
                  Python, TypeScript, Go
                </div>
              </div>
            </div>
          </div>
        </div>
        <div
          className="box-border [flex:1_1_0] h-full flex flex-col gap-[12px] p-[16px] justify-start items-start bg-[var(--ag2-panel)] [border:1px_solid_var(--ag2-border)] rounded-[9px]"
        >
          <div
            className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center"
          >
            <div
              className="text-[15px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]"
            >
              Performance Overview
            </div>
            <div
              className="box-border w-fit shrink-0 h-fit flex flex-row gap-0 p-[6px_9px] justify-start items-start bg-[var(--ag2-surface)] [border:1px_solid_var(--ag2-border)] rounded-[6px]"
            >
              <div
                className="text-[11px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
              >
                Last 30 days ⌄
              </div>
            </div>
          </div>
          <div
            className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-start"
          >
            <div
              className="box-border w-fit shrink-0 h-fit flex flex-col gap-[5px] justify-start items-start"
            >
              <div
                className="text-[10px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
              >
                Tasks Completed
              </div>
              <div
                className="text-[21px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]"
              >
                156
              </div>
              <div
                className="text-[10px]/[normal] box-border text-[#38D996] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]"
              >
                ↑ 18.7%
              </div>
            </div>
            <div
              className="box-border w-fit shrink-0 h-fit flex flex-col gap-[5px] justify-start items-start"
            >
              <div
                className="text-[10px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
              >
                Success Rate
              </div>
              <div
                className="text-[21px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]"
              >
                98.2%
              </div>
              <div
                className="text-[10px]/[normal] box-border text-[#38D996] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]"
              >
                ↑ 2.4%
              </div>
            </div>
            <div
              className="box-border w-fit shrink-0 h-fit flex flex-col gap-[5px] justify-start items-start"
            >
              <div
                className="text-[10px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
              >
                On-time Delivery
              </div>
              <div
                className="text-[21px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]"
              >
                97.1%
              </div>
              <div
                className="text-[10px]/[normal] box-border text-[#38D996] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]"
              >
                ↑ 3.1%
              </div>
            </div>
            <div
              className="box-border w-fit shrink-0 h-fit flex flex-col gap-[5px] justify-start items-start"
            >
              <div
                className="text-[10px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
              >
                Client Satisfaction
              </div>
              <div
                className="text-[21px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]"
              >
                4.9/5
              </div>
              <div
                className="text-[10px]/[normal] box-border text-[#38D996] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]"
              >
                ↑ 0.2
              </div>
            </div>
          </div>
          <div
            className="box-border w-full h-[126px] shrink-0 overflow-hidden relative"
          >
            <div
              className="box-border h-[91px] absolute left-[32px] right-0 top-[4px] bg-[var(--ag2-input-deep)] rounded-[4px] overflow-hidden [z-index:0]"
            >
              <svg
                viewBox="0 0 456 1"
                preserveAspectRatio="none"
                xmlns="http://www.w3.org/2000/svg"
                className="box-border w-full h-[1px] absolute left-0 top-0 overflow-visible [z-index:0]"
              >
                <line
                  x1="0"
                  y1="0"
                  x2="456"
                  y2="1"
                  stroke="#292B40" className="stroke-[var(--ag2-border)]"
                  strokeWidth="1"
                  vectorEffect="non-scaling-stroke"
                ></line>
              </svg>
              <svg
                viewBox="0 0 456 1"
                preserveAspectRatio="none"
                xmlns="http://www.w3.org/2000/svg"
                className="box-border w-full h-[1px] absolute left-0 top-[23px] overflow-visible [z-index:1]"
              >
                <line
                  x1="0"
                  y1="0"
                  x2="456"
                  y2="1"
                  stroke="#292B40" className="stroke-[var(--ag2-border)]"
                  strokeWidth="1"
                  vectorEffect="non-scaling-stroke"
                ></line>
              </svg>
              <svg
                viewBox="0 0 456 1"
                preserveAspectRatio="none"
                xmlns="http://www.w3.org/2000/svg"
                className="box-border w-full h-[1px] absolute left-0 top-[46px] overflow-visible [z-index:2]"
              >
                <line
                  x1="0"
                  y1="0"
                  x2="456"
                  y2="1"
                  stroke="#292B40" className="stroke-[var(--ag2-border)]"
                  strokeWidth="1"
                  vectorEffect="non-scaling-stroke"
                ></line>
              </svg>
              <svg
                viewBox="0 0 456 1"
                preserveAspectRatio="none"
                xmlns="http://www.w3.org/2000/svg"
                className="box-border w-full h-[1px] absolute left-0 top-[69px] overflow-visible [z-index:3]"
              >
                <line
                  x1="0"
                  y1="0"
                  x2="456"
                  y2="1"
                  stroke="#292B40" className="stroke-[var(--ag2-border)]"
                  strokeWidth="1"
                  vectorEffect="non-scaling-stroke"
                ></line>
              </svg>
              <svg
                viewBox="0 0 456 1"
                preserveAspectRatio="none"
                xmlns="http://www.w3.org/2000/svg"
                className="box-border w-full h-[1px] absolute left-0 top-[90px] overflow-visible [z-index:4]"
              >
                <line
                  x1="0"
                  y1="0"
                  x2="456"
                  y2="1"
                  stroke="#292B40" className="stroke-[var(--ag2-border)]"
                  strokeWidth="1"
                  vectorEffect="non-scaling-stroke"
                ></line>
              </svg>
              <svg
                viewBox="0 0 456 91"
                preserveAspectRatio="none"
                xmlns="http://www.w3.org/2000/svg"
                className="box-border w-full h-full absolute left-0 top-0 overflow-visible [z-index:5]"
              >
                <defs>
                  <linearGradient
                    id="g-upD8o-fill-0"
                    gradientUnits="userSpaceOnUse"
                    x1="228"
                    y1="0"
                    x2="228"
                    y2="91"
                  >
                    <stop offset="0%" stopColor="rgb(124,58,237)" stopOpacity="0.533"></stop>
                    <stop
                      offset="100%"
                      stopColor="rgb(124,58,237)"
                      stopOpacity="0.031"
                    ></stop>
                  </linearGradient>
                </defs>
                <path
                  d="M 0 72 L 20 65 L 42 66 L 63 63 L 84 63 L 105 55 L 126 48 L 147 46 L 168 52 L 189 51 L 210 42 L 231 31 L 252 29 L 273 34 L 294 23 L 315 19 L 336 15 L 357 17 L 378 13 L 399 8 L 420 5 L 440 4 L 456 0 L 456 91 L 0 91 Z"
                  fill="url(#g-upD8o-fill-0)"
                ></path>
              </svg>
              <svg
                viewBox="0 0 456 91"
                preserveAspectRatio="none"
                xmlns="http://www.w3.org/2000/svg"
                className="box-border w-full h-full absolute left-0 top-0 overflow-visible [z-index:6]"
              >
                <path
                  d="M 0 72 L 20 65 L 42 66 L 63 63 L 84 63 L 105 55 L 126 48 L 147 46 L 168 52 L 189 51 L 210 42 L 231 31 L 252 29 L 273 34 L 294 23 L 315 19 L 336 15 L 357 17 L 378 13 L 399 8 L 420 5 L 440 4 L 456 0"
                  fill="#00000000"
                ></path>
                <path
                  d="M 0 72 L 20 65 L 42 66 L 63 63 L 84 63 L 105 55 L 126 48 L 147 46 L 168 52 L 189 51 L 210 42 L 231 31 L 252 29 L 273 34 L 294 23 L 315 19 L 336 15 L 357 17 L 378 13 L 399 8 L 420 5 L 440 4 L 456 0"
                  fill="none"
                  stroke="#9A5CFF"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  vectorEffect="non-scaling-stroke"
                ></path>
              </svg>
              <div
                className="box-border w-[5px] h-[5px] absolute left-[calc(0.548%_-_2.5px)] top-[69.5px] bg-[#8B5CF6] [border:1px_solid_#C084FC] rounded-full [z-index:7]"
              ></div>
              <div
                className="box-border w-[5px] h-[5px] absolute left-[calc(9.211%_-_2.5px)] top-[63.5px] bg-[#8B5CF6] [border:1px_solid_#C084FC] rounded-full [z-index:8]"
              ></div>
              <div
                className="box-border w-[5px] h-[5px] absolute left-[calc(13.816%_-_2.5px)] top-[60.5px] bg-[#8B5CF6] [border:1px_solid_#C084FC] rounded-full [z-index:9]"
              ></div>
              <div
                className="box-border w-[5px] h-[5px] absolute left-[calc(18.421%_-_2.5px)] top-[60.5px] bg-[#8B5CF6] [border:1px_solid_#C084FC] rounded-full [z-index:10]"
              ></div>
              <div
                className="box-border w-[5px] h-[5px] absolute left-[calc(27.632%_-_2.5px)] top-[45.5px] bg-[#8B5CF6] [border:1px_solid_#C084FC] rounded-full [z-index:11]"
              ></div>
              <div
                className="box-border w-[5px] h-[5px] absolute left-[calc(32.237%_-_2.5px)] top-[43.5px] bg-[#8B5CF6] [border:1px_solid_#C084FC] rounded-full [z-index:12]"
              ></div>
              <div
                className="box-border w-[5px] h-[5px] absolute left-[calc(41.447%_-_2.5px)] top-[48.5px] bg-[#8B5CF6] [border:1px_solid_#C084FC] rounded-full [z-index:13]"
              ></div>
              <div
                className="box-border w-[5px] h-[5px] absolute left-[calc(50.658%_-_2.5px)] top-[28.5px] bg-[#8B5CF6] [border:1px_solid_#C084FC] rounded-full [z-index:14]"
              ></div>
              <div
                className="box-border w-[5px] h-[5px] absolute left-[calc(55.263%_-_2.5px)] top-[26.5px] bg-[#8B5CF6] [border:1px_solid_#C084FC] rounded-full [z-index:15]"
              ></div>
              <div
                className="box-border w-[5px] h-[5px] absolute left-[calc(59.868%_-_2.5px)] top-[31.5px] bg-[#8B5CF6] [border:1px_solid_#C084FC] rounded-full [z-index:16]"
              ></div>
              <div
                className="box-border w-[5px] h-[5px] absolute left-[calc(69.079%_-_2.5px)] top-[16.5px] bg-[#8B5CF6] [border:1px_solid_#C084FC] rounded-full [z-index:17]"
              ></div>
              <div
                className="box-border w-[5px] h-[5px] absolute left-[calc(73.684%_-_2.5px)] top-[12.5px] bg-[#8B5CF6] [border:1px_solid_#C084FC] rounded-full [z-index:18]"
              ></div>
              <div
                className="box-border w-[5px] h-[5px] absolute left-[calc(78.289%_-_2.5px)] top-[14.5px] bg-[#8B5CF6] [border:1px_solid_#C084FC] rounded-full [z-index:19]"
              ></div>
              <div
                className="box-border w-[5px] h-[5px] absolute left-[calc(82.895%_-_2.5px)] top-[10.5px] bg-[#8B5CF6] [border:1px_solid_#C084FC] rounded-full [z-index:20]"
              ></div>
              <div
                className="box-border w-[5px] h-[5px] absolute left-[calc(87.500%_-_2.5px)] top-[5.5px] bg-[#8B5CF6] [border:1px_solid_#C084FC] rounded-full [z-index:21]"
              ></div>
              <div
                className="box-border w-[5px] h-[5px] absolute left-[calc(92.105%_-_2.5px)] top-[2.5px] bg-[#8B5CF6] [border:1px_solid_#C084FC] rounded-full [z-index:22]"
              ></div>
              <div
                className="box-border w-[5px] h-[5px] absolute left-[calc(96.491%_-_2.5px)] top-[1.5px] bg-[#8B5CF6] [border:1px_solid_#C084FC] rounded-full [z-index:23]"
              ></div>
              <div
                className="box-border w-[5px] h-[5px] absolute left-[calc(99.452%_-_2.5px)] top-0 bg-[#8B5CF6] [border:1px_solid_#C084FC] rounded-full [z-index:24]"
              ></div>
            </div>
            <div
              className="text-[9px]/[normal] box-border absolute left-0 top-0 text-[var(--ag2-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap] [z-index:1]"
            >
              200
            </div>
            <div
              className="text-[9px]/[normal] box-border absolute left-0 top-[17px] text-[var(--ag2-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap] [z-index:2]"
            >
              150
            </div>
            <div
              className="text-[9px]/[normal] box-border absolute left-0 top-[40px] text-[var(--ag2-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap] [z-index:3]"
            >
              100
            </div>
            <div
              className="text-[9px]/[normal] box-border absolute left-0 top-[63px] text-[var(--ag2-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap] [z-index:4]"
            >
              50
            </div>
            <div
              className="text-[9px]/[normal] box-border absolute left-0 top-[85px] text-[var(--ag2-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap] [z-index:5]"
            >
              0
            </div>
            <div
              className="text-[9px]/[normal] box-border absolute left-[32px] top-[104px] text-[var(--ag2-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap] [z-index:6]"
            >
              Apr 22
            </div>
            <div
              className="text-[9px]/[normal] box-border absolute left-[calc(32px_+_(100%_-_32px)*0.2061)] top-[104px] text-[var(--ag2-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap] [z-index:7]"
            >
              Apr 29
            </div>
            <div
              className="text-[9px]/[normal] box-border absolute left-[calc(32px_+_(100%_-_32px)*0.4123)] top-[104px] text-[var(--ag2-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap] [z-index:8]"
            >
              May 6
            </div>
            <div
              className="text-[9px]/[normal] box-border absolute left-[calc(32px_+_(100%_-_32px)*0.6184)] top-[104px] text-[var(--ag2-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap] [z-index:9]"
            >
              May 13
            </div>
            <div
              className="text-[9px]/[normal] box-border absolute left-[calc(32px_+_(100%_-_32px)*0.8377)] top-[104px] text-[var(--ag2-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap] [z-index:10]"
            >
              May 20
            </div>
          </div>
        </div>
      </div>
      <div
        className="box-border w-full h-[145px] shrink-0 flex flex-col gap-[9px] p-[14px] justify-start items-start bg-[var(--ag2-panel)] [border:1px_solid_var(--ag2-border)] rounded-[9px]"
      >
        <div
          className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-start"
        >
          <div
            className="text-[15px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]"
          >
            Core Capabilities
          </div>
          <div
            className="text-[12px]/[normal] box-border text-[#B267FF] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]"
          >
            View all capabilities
          </div>
        </div>
        <div
          className="box-border w-full [flex:1_1_0] flex flex-row gap-[10px] justify-start items-start"
        >
          <div
            className="box-border [flex:1_1_0] h-full flex flex-col gap-[8px] justify-start items-start"
          >
            <div
              className="box-border w-full [flex:1_1_0] flex flex-row gap-[8px] p-[7px_8px] justify-start items-center bg-[var(--ag2-surface)] [border:1px_solid_var(--ag2-border)] rounded-[6px]"
            >
              <div
                className="text-[16px]/[normal] box-border text-[#B266FF] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
              >
                ☁
              </div>
              <div
                className="box-border w-fit shrink-0 h-fit flex flex-col gap-[2px] justify-start items-start"
              >
                <div
                  className="text-[11px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]"
                >
                  Infrastructure Deployment
                </div>
                <div
                  className="text-[10px]/[normal] box-border text-[#FBBF24] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
                >
                  ★ 4.9
                </div>
              </div>
            </div>
            <div
              className="box-border w-full [flex:1_1_0] flex flex-row gap-[8px] p-[7px_8px] justify-start items-center bg-[var(--ag2-surface)] [border:1px_solid_var(--ag2-border)] rounded-[6px]"
            >
              <div
                className="text-[16px]/[normal] box-border text-[#B266FF] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
              >
                ◉
              </div>
              <div
                className="box-border w-fit shrink-0 h-fit flex flex-col gap-[2px] justify-start items-start"
              >
                <div
                  className="text-[11px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]"
                >
                  CI/CD Pipeline Setup
                </div>
                <div
                  className="text-[10px]/[normal] box-border text-[#FBBF24] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
                >
                  ★ 4.8
                </div>
              </div>
            </div>
          </div>
          <div
            className="box-border [flex:1_1_0] h-full flex flex-col gap-[8px] justify-start items-start"
          >
            <div
              className="box-border w-full [flex:1_1_0] flex flex-row gap-[8px] p-[7px_8px] justify-start items-center bg-[var(--ag2-surface)] [border:1px_solid_var(--ag2-border)] rounded-[6px]"
            >
              <div
                className="text-[16px]/[normal] box-border text-[#B266FF] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
              >
                ✦
              </div>
              <div
                className="box-border w-fit shrink-0 h-fit flex flex-col gap-[2px] justify-start items-start"
              >
                <div
                  className="text-[11px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]"
                >
                  Kubernetes Management
                </div>
                <div
                  className="text-[10px]/[normal] box-border text-[#FBBF24] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
                >
                  ★ 4.9
                </div>
              </div>
            </div>
            <div
              className="box-border w-full [flex:1_1_0] flex flex-row gap-[8px] p-[7px_8px] justify-start items-center bg-[var(--ag2-surface)] [border:1px_solid_var(--ag2-border)] rounded-[6px]"
            >
              <div
                className="text-[16px]/[normal] box-border text-[#B266FF] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
              >
                ☁
              </div>
              <div
                className="box-border w-fit shrink-0 h-fit flex flex-col gap-[2px] justify-start items-start"
              >
                <div
                  className="text-[11px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]"
                >
                  Cloud Architecture
                </div>
                <div
                  className="text-[10px]/[normal] box-border text-[#FBBF24] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
                >
                  ★ 4.8
                </div>
              </div>
            </div>
          </div>
          <div
            className="box-border [flex:1_1_0] h-full flex flex-col gap-[8px] justify-start items-start"
          >
            <div
              className="box-border w-full [flex:1_1_0] flex flex-row gap-[8px] p-[7px_8px] justify-start items-center bg-[var(--ag2-surface)] [border:1px_solid_var(--ag2-border)] rounded-[6px]"
            >
              <div
                className="text-[16px]/[normal] box-border text-[#60A5FA] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
              >
                ✥
              </div>
              <div
                className="box-border w-fit shrink-0 h-fit flex flex-col gap-[2px] justify-start items-start"
              >
                <div
                  className="text-[11px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]"
                >
                  Terraform Automation
                </div>
                <div
                  className="text-[10px]/[normal] box-border text-[#FBBF24] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
                >
                  ★ 4.7
                </div>
              </div>
            </div>
            <div
              className="box-border w-full [flex:1_1_0] flex flex-row gap-[8px] p-[7px_8px] justify-start items-center bg-[var(--ag2-surface)] [border:1px_solid_var(--ag2-border)] rounded-[6px]"
            >
              <div
                className="text-[16px]/[normal] box-border text-[#60A5FA] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
              >
                ▣
              </div>
              <div
                className="box-border w-fit shrink-0 h-fit flex flex-col gap-[2px] justify-start items-start"
              >
                <div
                  className="text-[11px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]"
                >
                  Monitoring &amp; Logging
                </div>
                <div
                  className="text-[10px]/[normal] box-border text-[#FBBF24] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
                >
                  ★ 4.8
                </div>
              </div>
            </div>
          </div>
          <div
            className="box-border [flex:1_1_0] h-full flex flex-col gap-[8px] justify-start items-start"
          >
            <div
              className="box-border w-full [flex:1_1_0] flex flex-row gap-[8px] p-[7px_8px] justify-start items-center bg-[var(--ag2-surface)] [border:1px_solid_var(--ag2-border)] rounded-[6px]"
            >
              <div
                className="text-[16px]/[normal] box-border text-[#B266FF] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
              >
                ◉
              </div>
              <div
                className="box-border w-fit shrink-0 h-fit flex flex-col gap-[2px] justify-start items-start"
              >
                <div
                  className="text-[11px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]"
                >
                  Security Implementation
                </div>
                <div
                  className="text-[10px]/[normal] box-border text-[#FBBF24] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
                >
                  ★ 4.9
                </div>
              </div>
            </div>
            <div
              className="box-border w-full [flex:1_1_0] flex flex-row gap-[8px] p-[7px_8px] justify-start items-center bg-[var(--ag2-surface)] [border:1px_solid_var(--ag2-border)] rounded-[6px]"
            >
              <div
                className="text-[16px]/[normal] box-border text-[#B266FF] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
              >
                ◌
              </div>
              <div
                className="box-border w-fit shrink-0 h-fit flex flex-col gap-[2px] justify-start items-start"
              >
                <div
                  className="text-[11px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]"
                >
                  Performance Optimization
                </div>
                <div
                  className="text-[10px]/[normal] box-border text-[#FBBF24] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
                >
                  ★ 4.7
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div
        className="box-border w-full h-[172px] shrink-0 flex flex-col gap-[8px] p-[14px_16px] justify-start items-start bg-[var(--ag2-panel)] [border:1px_solid_var(--ag2-border)] rounded-[9px]"
      >
        <div
          className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-start"
        >
          <div
            className="text-[15px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]"
          >
            Recent Tasks
          </div>
          <div
            className="text-[12px]/[normal] box-border text-[#B267FF] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]"
          >
            View all tasks
          </div>
        </div>
        <div
          className="box-border w-full [flex:1_1_0] flex flex-col gap-0 justify-start items-start"
        >
          <div
            className="box-border w-full h-[24px] shrink-0 flex flex-row gap-0 justify-start items-center"
          >
            <div
              className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-row gap-0 justify-start items-start"
            >
              <div
                className="text-[10px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]"
              >
                Task
              </div>
            </div>
            <div
              className="box-border w-[150px] shrink-0 h-fit flex flex-row gap-0 justify-start items-start"
            >
              <div
                className="text-[10px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]"
              >
                Client
              </div>
            </div>
            <div
              className="box-border w-[110px] shrink-0 h-fit flex flex-row gap-0 justify-start items-start"
            >
              <div
                className="text-[10px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]"
              >
                Status
              </div>
            </div>
            <div
              className="box-border w-[130px] shrink-0 h-fit flex flex-row gap-0 justify-start items-start"
            >
              <div
                className="text-[10px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]"
              >
                Completed
              </div>
            </div>
            <div
              className="box-border w-[80px] shrink-0 h-fit flex flex-row gap-0 justify-start items-start"
            >
              <div
                className="text-[10px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]"
              >
                Rating
              </div>
            </div>
            <div
              className="box-border w-[80px] shrink-0 h-fit flex flex-row gap-0 justify-start items-start"
            >
              <div
                className="text-[10px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]"
              >
                Amount
              </div>
            </div>
          </div>
          <div
            className="box-border w-full [flex:1_1_0] flex flex-row gap-0 justify-start items-center [border-width:1px_0px_0px_0px] [border-style:solid] [border-color:var(--ag2-border)]"
          >
            <div
              className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-row gap-0 justify-start items-start"
            >
              <div
                className="text-[11px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]"
              >
                Deploy microservices to EKS
              </div>
            </div>
            <div
              className="box-border w-[150px] shrink-0 h-fit flex flex-row gap-0 justify-start items-start"
            >
              <div
                className="text-[10px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
              >
                TechCorp Inc.
              </div>
            </div>
            <div
              className="box-border w-[110px] shrink-0 h-fit flex flex-row gap-0 justify-start items-start"
            >
              <div
                className="box-border w-fit shrink-0 h-fit flex flex-row gap-0 p-[4px_7px] justify-start items-start bg-[#073C31] rounded-[4px]"
              >
                <div
                  className="text-[10px]/[normal] box-border text-[#38D996] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]"
                >
                  Completed
                </div>
              </div>
            </div>
            <div
              className="box-border w-[130px] shrink-0 h-fit flex flex-row gap-0 justify-start items-start"
            >
              <div
                className="text-[10px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
              >
                May 20, 2024
              </div>
            </div>
            <div
              className="box-border w-[80px] shrink-0 h-fit flex flex-row gap-0 justify-start items-start"
            >
              <div
                className="text-[10px]/[normal] box-border text-[#FBBF24] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
              >
                ★ 5.0
              </div>
            </div>
            <div
              className="box-border w-[80px] shrink-0 h-fit flex flex-row gap-0 justify-start items-start"
            >
              <div
                className="text-[10px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
              >
                $1,850
              </div>
            </div>
          </div>
          <div
            className="box-border w-full [flex:1_1_0] flex flex-row gap-0 justify-start items-center [border-width:1px_0px_0px_0px] [border-style:solid] [border-color:var(--ag2-border)]"
          >
            <div
              className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-row gap-0 justify-start items-start"
            >
              <div
                className="text-[11px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]"
              >
                CI/CD pipeline optimization
              </div>
            </div>
            <div
              className="box-border w-[150px] shrink-0 h-fit flex flex-row gap-0 justify-start items-start"
            >
              <div
                className="text-[10px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
              >
                DataFlow Systems
              </div>
            </div>
            <div
              className="box-border w-[110px] shrink-0 h-fit flex flex-row gap-0 justify-start items-start"
            >
              <div
                className="box-border w-fit shrink-0 h-fit flex flex-row gap-0 p-[4px_7px] justify-start items-start bg-[#073C31] rounded-[4px]"
              >
                <div
                  className="text-[10px]/[normal] box-border text-[#38D996] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]"
                >
                  Completed
                </div>
              </div>
            </div>
            <div
              className="box-border w-[130px] shrink-0 h-fit flex flex-row gap-0 justify-start items-start"
            >
              <div
                className="text-[10px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
              >
                May 18, 2024
              </div>
            </div>
            <div
              className="box-border w-[80px] shrink-0 h-fit flex flex-row gap-0 justify-start items-start"
            >
              <div
                className="text-[10px]/[normal] box-border text-[#FBBF24] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
              >
                ★ 4.9
              </div>
            </div>
            <div
              className="box-border w-[80px] shrink-0 h-fit flex flex-row gap-0 justify-start items-start"
            >
              <div
                className="text-[10px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
              >
                $950
              </div>
            </div>
          </div>
          <div
            className="box-border w-full [flex:1_1_0] flex flex-row gap-0 justify-start items-center [border-width:1px_0px_0px_0px] [border-style:solid] [border-color:var(--ag2-border)]"
          >
            <div
              className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-row gap-0 justify-start items-start"
            >
              <div
                className="text-[11px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]"
              >
                Multi-environment setup
              </div>
            </div>
            <div
              className="box-border w-[150px] shrink-0 h-fit flex flex-row gap-0 justify-start items-start"
            >
              <div
                className="text-[10px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
              >
                InnovateLabs
              </div>
            </div>
            <div
              className="box-border w-[110px] shrink-0 h-fit flex flex-row gap-0 justify-start items-start"
            >
              <div
                className="box-border w-fit shrink-0 h-fit flex flex-row gap-0 p-[4px_7px] justify-start items-start bg-[#073C31] rounded-[4px]"
              >
                <div
                  className="text-[10px]/[normal] box-border text-[#38D996] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]"
                >
                  Completed
                </div>
              </div>
            </div>
            <div
              className="box-border w-[130px] shrink-0 h-fit flex flex-row gap-0 justify-start items-start"
            >
              <div
                className="text-[10px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
              >
                May 15, 2024
              </div>
            </div>
            <div
              className="box-border w-[80px] shrink-0 h-fit flex flex-row gap-0 justify-start items-start"
            >
              <div
                className="text-[10px]/[normal] box-border text-[#FBBF24] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
              >
                ★ 4.8
              </div>
            </div>
            <div
              className="box-border w-[80px] shrink-0 h-fit flex flex-row gap-0 justify-start items-start"
            >
              <div
                className="text-[10px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
              >
                $2,200
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
