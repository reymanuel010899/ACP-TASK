export default function RightRail() {
  return (
    <div
      className="box-border w-[320px] shrink-0 h-full flex flex-col gap-[20px] p-[24px_20px] justify-start items-start bg-[var(--ag-right-bg)] [border-width:0px_0px_0px_1px] [border-style:solid] [border-color:var(--ag-divider)] overflow-y-auto"
    >
      <div
        className="box-border w-full h-fit shrink-0 flex flex-col gap-[12px] justify-start items-start"
      >
        <div
          className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center"
        >
          <div
            className="text-[16px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]"
          >
            Recent Activity
          </div>
          <div
            className="text-[12px]/[normal] box-border text-[#8B5CF6] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
          >
            View all
          </div>
        </div>
        <div
          className="box-border w-full h-fit shrink-0 flex flex-col gap-0 justify-start items-start"
        >
          <div
            className="box-border w-full h-fit shrink-0 flex flex-row gap-[10px] p-[10px_0px] justify-start items-start"
          >
            <div
              className="box-border w-[32px] shrink-0 h-[32px] flex flex-row gap-0 justify-center items-center bg-[#3B82F620] rounded-[16px]"
            >
              <svg
                data-icon-name="rocket"
                data-icon-set="lucide"
                viewBox="0 0 13.99993896484375 14"
                preserveAspectRatio="xMidYMid meet"
                xmlns="http://www.w3.org/2000/svg"
                className="box-border w-[16px] shrink-0 h-[16px]"
              >
                <path
                  d="M12.41748 0.60156q-2.03027 0.08545-3.80762 1.14844-0.43408 0.25293-0.81347 0.56055-0.82373 0.62891-1.43897 1.45605l-0.1709 0.22217q-0.01367 0.01367-0.16748-0.02734-0.90918-0.18115-1.58252-0.14698-0.66992 0.03418-1.11767 0.28711-0.44775 0.25293-0.78614 0.76905-0.44775 0.65967-0.71435 1.72265-0.05469 0.25293-0.06152 0.3999-0.00684 0.14697 0.04785 0.25977 0.11279 0.2085 0.3247 0.29394 0.06836 0.02734 0.26319 0.02735l2.60449 0 1.42871 1.42871 0 2.60449q0 0.19482 0.02735 0.26318 0.08545 0.21192 0.29394 0.32471 0.14014 0.06836 0.38623 0.03418 0.24609-0.03418 0.72119-0.18799 1.59619-0.49219 2.05762-1.37402 0.50244-0.96387 0.12646-2.70019l-0.02734-0.12647q0-0.02734 0.02734-0.04443 0.0957-0.05469 0.54688-0.43409 1.16211-0.99121 1.86621-2.30712 0.70752-1.31592 0.90576-2.83008 0.02734-0.29395 0.04785-0.67676 0.02051-0.38623 0.00684-0.47168-0.04101-0.2085-0.18799-0.3418-0.14697-0.1333-0.37256-0.14697-0.12646 0-0.43408 0.01367z m-0.19482 1.24756q0 0.18115-0.09912 0.65625-0.4751 2.60449-2.68653 4.28613-0.42041 0.32129-0.99463 0.64258-0.57422 0.32129-1.17578 0.57422l-0.12646 0.05469-1.20313-1.2168 0.15381-0.32129q0.32129-0.72803 0.72803-1.36377 0.40674-0.63916 0.81006-1.11425 0.77246-0.86816 1.84228-1.44922 1.06982-0.58105 2.23194-0.76221 0.30762-0.04443 0.42041-0.04443l0.09912-0.01368 0 0.07178z m-7.21192 3.13428q0.43408 0.04102 0.47852 0.07178 0.02734 0.01367-0.06494 0.17431-0.08887 0.16064-0.25293 0.49903-0.16064 0.33496-0.24268 0.51611l-0.07178 0.16748-0.88183 0q-0.88184 0.01367-0.88184-0.01367 0-0.02734 0.0752-0.22217 0.07861-0.19824 0.15039-0.33838 0.22217-0.44775 0.4375-0.62207 0.21875-0.17432 0.59814-0.23242 0.30762-0.02734 0.65625 0z m3.96485 3.65381q0.01367 0.11279 0.04101 0.40674 0.04102 0.67334-0.12646 1.04931-0.14014 0.30762-0.71436 0.57422-0.11279 0.07178-0.33154 0.15723-0.21533 0.08203-0.24268 0.08203-0.02734 0-0.01367-0.88184l0-0.88183 0.34863-0.15381q0.36572-0.15381 0.67334-0.31446 0.30762-0.16406 0.32129-0.16406 0.01367 0 0.04444 0.12647z m-5.81055 0.12646q-0.22559 0.02734-0.45801 0.1333-0.229 0.10596-0.41015 0.2461-0.5332 0.42041-0.88184 1.30224-0.19824 0.48877-0.36572 1.14844-0.16748 0.65625-0.16748 0.9502 0 0.14014 0.03418 0.22558 0.0376 0.08203 0.1333 0.18115 0.09912 0.0957 0.18115 0.1333 0.08545 0.03418 0.22558 0.03418 0.30762 0 1.01514-0.18115 0.70752-0.18457 1.18262-0.39306 0.75537-0.32129 1.14844-0.78272 0.39307-0.46484 0.46142-1.09375 0-0.11279-0.01367-0.28711-0.01367-0.17432-0.04102-0.28711-0.12646-0.4751-0.47851-0.81689-0.34863-0.34521-0.82373-0.48535-0.14014-0.02734-0.41358-0.03418-0.27344-0.00684-0.32812 0.00683z m0.38965 1.16211q0.1709 0.02734 0.29394 0.11963 0.12646 0.09229 0.18457 0.229 0.05469 0.11279 0.05469 0.25977 0 0.14697-0.02734 0.24609-0.19824 0.56055-1.65088 0.96729-0.19824 0.05469-0.20508 0.04101-0.00684-0.01367 0.08203-0.30761 0.09229-0.29395 0.15039-0.46143 0.32129-0.85449 0.70069-1.03906 0.10938-0.05469 0.30761-0.06836 0.01367 0 0.10938 0.01367z"
                  fill="#3B82F6"
                ></path>
              </svg>
            </div>
            <div
              className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[2px] justify-start items-start"
            >
              <div
                className="text-[13px]/[normal] box-border w-full truncate text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-medium text-left"
              >
                DevOps Agent completed deployment
              </div>
              <div
                className="text-[11px]/[normal] box-border text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
              >
                Task #T-8432
              </div>
            </div>
            <div
              className="text-[11px]/[normal] box-border text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
            >
              2m ago
            </div>
          </div>
          <div
            className="box-border w-full h-[1px] shrink-0 bg-[var(--ag-divider)]"
          ></div>
          <div
            className="box-border w-full h-fit shrink-0 flex flex-row gap-[10px] p-[10px_0px] justify-start items-start"
          >
            <div
              className="box-border w-[32px] shrink-0 h-[32px] flex flex-row gap-0 justify-center items-center bg-[#F59E0B20] rounded-[16px]"
            >
              <svg
                data-icon-name="megaphone"
                data-icon-set="lucide"
                viewBox="0 0 13.99993896484375 14"
                preserveAspectRatio="xMidYMid meet"
                xmlns="http://www.w3.org/2000/svg"
                className="box-border w-[16px] shrink-0 h-[16px]"
              >
                <path
                  d="M11.43652 1.18945q-0.06836 0.01367-0.19482 0.06494-0.12647 0.04785-0.19482 0.08887l-0.23926 0.16748q-1.49707 1.12109-3.42823 1.37403-0.1709 0.01367-0.58789 0.02734l-4.17334 0.01367-0.14013 0.04102q-0.4751 0.14014-0.80664 0.47168-0.32813 0.32813-0.45459 0.81689-0.02734 0.07178-0.02735 0.30762l-0.01367 1.55517q0 0.92285 0.01367 1.10059 0.01367 0.17432 0.07178 0.3418l0.01367 0.05468q0.16748 0.46143 0.58789 0.7793 0.42041 0.31445 0.92285 0.35547l0.15381 0 0.01367 0.12646q0.07178 0.82715 0.3418 1.6543 0.27344 0.82373 0.69385 1.52442 0.44775 0.7417 0.77246 0.99121 0.26318 0.21191 0.59131 0.3042 0.33154 0.08887 0.63916 0.06152 0.57422-0.07178 0.98096-0.42041 0.40674-0.34863 0.56054-0.89551 0.02734-0.12646 0.04102-0.35547 0.01367-0.23242-0.01367-0.35888-0.04102-0.23926-0.11963-0.40674-0.07861-0.16748-0.27344-0.46143-0.19482-0.29394-0.28027-0.46142-0.28027-0.5332-0.38965-1.07666l-0.04444-0.22559 0.36573 0q2.2251 0.06836 4.01611 1.41504 0.23926 0.18115 0.39307 0.25293 0.15381 0.06836 0.37939 0.08203 0.38965 0.01367 0.7041-0.20166 0.31787-0.21875 0.47168-0.59473l0.04102-0.12646 0-6.57959q0-0.67334-0.02735-0.86817 0-0.14014-0.0581-0.23925l-0.01367-0.04102q-0.11279-0.23926-0.32129-0.41357-0.2085-0.17432-0.4751-0.23243-0.08545-0.02734-0.23242-0.02734-0.14697 0-0.25977 0.01367z m0.23926 4.64844q0 3.48633-0.02734 3.47266l-0.15381-0.1128q-0.78613-0.58789-1.73975-0.97754-0.9502-0.39307-1.92773-0.54687-0.33838-0.05811-0.63233-0.07178-0.29395-0.01367-1.0083-0.01367l-0.93652-0.01367 0-3.5 0.90918 0q0.71436 0 1.00146-0.01367 0.28711-0.01367 0.65284-0.05811 0.72803-0.10938 1.47656-0.36914 0.74853-0.25977 1.39111-0.63574 0.49219-0.28027 0.84082-0.56055 0.12647-0.08545 0.14014-0.08545 0.01367 0 0.01367 3.48633z m-7.60156-0.01367l0 1.75-1.18945 0q-0.11279 0-0.19141-0.03418-0.0752-0.0376-0.16748-0.11279-0.08887-0.07861-0.1333-0.16748-0.04102-0.09229-0.05469-0.32813-0.01367-0.23926 0-1.19287l0-1.20313 0.04102-0.09912q0.07178-0.14014 0.18798-0.229 0.11963-0.09229 0.25977-0.11963 0.08545 0 0.67334-0.01367l0.57422 0 0 1.75z m1.24414 3.16504q0.09912 0.66992 0.37939 1.30224 0.18115 0.38965 0.4751 0.83741 0.15381 0.25293 0.19483 0.33838 0.04443 0.08203 0.04443 0.19482-0.01367 0.28027-0.19482 0.44775-0.23926 0.19482-0.53321 0.1128-0.12646-0.02734-0.21191-0.10254-0.08203-0.07861-0.2085-0.26319-0.92285-1.30225-1.12109-2.86767l-0.02735-0.22559q0-0.01367 0.57422-0.01367l0.58789 0 0.04102 0.23926z"
                  fill="#F59E0B"
                ></path>
              </svg>
            </div>
            <div
              className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[2px] justify-start items-start"
            >
              <div
                className="text-[13px]/[normal] box-border w-full truncate text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-medium text-left"
              >
                Marketing Agent started campaign
              </div>
              <div
                className="text-[11px]/[normal] box-border text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
              >
                Campaign #C-221
              </div>
            </div>
            <div
              className="text-[11px]/[normal] box-border text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
            >
              15m ago
            </div>
          </div>
          <div
            className="box-border w-full h-[1px] shrink-0 bg-[var(--ag-divider)]"
          ></div>
          <div
            className="box-border w-full h-fit shrink-0 flex flex-row gap-[10px] p-[10px_0px] justify-start items-start"
          >
            <div
              className="box-border w-[32px] shrink-0 h-[32px] flex flex-row gap-0 justify-center items-center bg-[#22C55E20] rounded-[16px]"
            >
              <svg
                data-icon-name="dollar-sign"
                data-icon-set="lucide"
                viewBox="0 0 13.99993896484375 14"
                preserveAspectRatio="xMidYMid meet"
                xmlns="http://www.w3.org/2000/svg"
                className="box-border w-[16px] shrink-0 h-[16px]"
              >
                <path
                  d="M6.90088 0.60156q-0.18115 0.02734-0.32129 0.16748-0.08203 0.08545-0.11279 0.15723-0.02734 0.06836-0.04102 0.23584 0 0.12646 0 0.51953l0 0.64258-0.57422 0.01367q-0.56055 0-0.82031 0.04443-0.25635 0.04102-0.56396 0.18116-0.61865 0.27686-1.01856 0.81689-0.39648 0.54004-0.50928 1.22705-0.01367 0.12305-0.01367 0.36914 0 0.24609 0.02735 0.38623 0.14014 0.85449 0.73486 1.44922 0.59473 0.59473 1.44922 0.73486 0.15381 0.02734 0.71435 0.02735l0.57422 0 0 2.92578-3.07959 0.01367-0.09912 0.04102q-0.2666 0.12646-0.31445 0.42041-0.04785 0.29395 0.14697 0.50586 0.08545 0.08203 0.18115 0.14013l0.1128 0.04102 3.05224 0.01367 0 0.62891q0 0.40674 0 0.5332 0.01367 0.16748 0.04102 0.23926 0.03076 0.06836 0.11279 0.15381 0.18115 0.18115 0.42041 0.18115 0.23926 0 0.42041-0.18115 0.08203-0.08545 0.10938-0.15381 0.03076-0.07178 0.04443-0.23926 0-0.12647 0-0.5332l0-0.62891 0.46142 0q0.50586 0 0.75538-0.03418 0.25293-0.03418 0.51953-0.11963 0.56055-0.19482 0.97754-0.6084 0.42041-0.41357 0.63232-0.98779 0.14014-0.34863 0.15381-0.76221 0.01367-0.41357-0.07178-0.77587-0.18115-0.67334-0.67334-1.17579-0.48877-0.50586-1.15869-0.68701-0.21191-0.07178-0.41357-0.08545-0.20166-0.01367-0.63575-0.01367l-0.54687 0 0-2.92578 2.17041 0q0.25293-0.01367 0.33496-0.02734 0.08545-0.01367 0.15381-0.07178l0.01367-0.01367q0.21191-0.14014 0.24609-0.36914 0.03418-0.23242-0.09912-0.43409-0.1333-0.20508-0.38281-0.23242-0.11279-0.02734-1.2749-0.02734l-1.16211 0 0-1.18945q0-0.11279-0.02735-0.16748-0.07178-0.19824-0.25292-0.30079-0.18115-0.10596-0.39307-0.06494z m-0.4751 4.35449l0 1.46973-0.56055-0.01367q-0.44775 0-0.60156-0.02051-0.15381-0.02051-0.32129-0.10596-0.30762-0.12646-0.5332-0.40673-0.22217-0.28027-0.29395-0.60157-0.01367-0.11279-0.0205-0.30078-0.00684-0.18799 0.0205-0.30078 0.05811-0.32129 0.27344-0.60156 0.21875-0.28027 0.52637-0.43408 0.18115-0.08545 0.35547-0.1128 0.17432-0.02734 0.63916-0.02734l0.51611 0 0 1.45605z m2.36524 2.65918q0.39307 0.09912 0.70068 0.40674 0.30762 0.30762 0.39307 0.70069 0.01367 0.11279 0.0205 0.30078 0.00684 0.18799-0.0205 0.30078-0.07178 0.39307-0.35206 0.70068-0.28027 0.30762-0.68359 0.42041-0.08545 0.02734-0.19824 0.03418-0.10938 0.00684-0.50244 0.02051l-0.57422 0 0-2.92578 0.54687 0.01367q0.56055 0 0.66993 0.02734z"
                  fill="#22C55E"
                ></path>
              </svg>
            </div>
            <div
              className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[2px] justify-start items-start"
            >
              <div
                className="text-[13px]/[normal] box-border w-full truncate text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-medium text-left"
              >
                Finance Agent processed invoice
              </div>
              <div
                className="text-[11px]/[normal] box-border text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
              >
                Invoice #INV-5538
              </div>
            </div>
            <div
              className="text-[11px]/[normal] box-border text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
            >
              32m ago
            </div>
          </div>
          <div
            className="box-border w-full h-[1px] shrink-0 bg-[var(--ag-divider)]"
          ></div>
          <div
            className="box-border w-full h-fit shrink-0 flex flex-row gap-[10px] p-[10px_0px] justify-start items-start"
          >
            <div
              className="box-border w-[32px] shrink-0 h-[32px] flex flex-row gap-0 justify-center items-center bg-[#EF444420] rounded-[16px]"
            >
              <svg
                data-icon-name="shield-alert"
                data-icon-set="lucide"
                viewBox="0 0 13.99993896484375 14"
                preserveAspectRatio="xMidYMid meet"
                xmlns="http://www.w3.org/2000/svg"
                className="box-border w-[16px] shrink-0 h-[16px]"
              >
                <path
                  d="M6.84619 0.60156q-0.34863 0.02734-0.68701 0.30762-0.51611 0.42041-1.00147 0.70068-0.48193 0.28027-1.01513 0.4751-0.30762 0.11279-0.58789 0.1709-0.28027 0.05469-0.66992 0.08203-0.23926 0.01367-0.36573 0.07178-0.19482 0.06836-0.37939 0.22217-0.18115 0.15381-0.26319 0.34863l-0.01367 0.03076q-0.07178 0.12646-0.08545 0.22217-0.01367 0.15381-0.02734 0.60156l0 1.78076q0 2.25244 0.01367 2.46094 0.14014 1.6543 1.10742 2.88477 0.14014 0.16748 0.43409 0.46142 0.29395 0.29394 0.48877 0.44775 0.92285 0.7417 2.2832 1.27491 0.46143 0.18115 0.65625 0.23926 0.23926 0.05469 0.43408 0.01367 0.16748-0.02734 0.5332-0.15381 1.35693-0.51953 2.27979-1.20313 0.37939-0.2666 0.71435-0.60498 1.37402-1.3706 1.54151-3.37353 0.01367-0.23584 0.01367-2.46094 0-2.22852-0.02734-2.35498-0.07178-0.32129-0.31787-0.56396-0.24268-0.24609-0.5503-0.31788-0.09912-0.02734-0.37939-0.04101-0.48877-0.02734-0.96387-0.18115-0.81348-0.2666-1.55518-0.77246-0.2666-0.18115-0.64257-0.48877-0.42041-0.33496-0.96729-0.28028z m0.43408 1.34326q0.64258 0.51953 1.32959 0.86817 1.2168 0.61865 2.25244 0.68701l0.21192 0-0.01367 4.31348q0 0.33496-0.02735 0.50244-0.22559 1.34326-1.1416 2.27637-0.91602 0.92969-2.66601 1.57226l-0.21192 0.08545-0.18115-0.05469q-2.32422-0.85449-3.2334-2.22851-0.47852-0.71436-0.63232-1.63721-0.02734-0.18115-0.02735-0.50244l-0.01367-4.32715 0.19483 0q0.86816-0.05469 1.84912-0.48193 0.98096-0.42725 1.83545-1.12793 0.16748-0.14014 0.19482-0.14014 0.02734 0 0.28027 0.19482z m-0.37939 2.15674q-0.0957 0.01367-0.17432 0.05127-0.0752 0.03418-0.15381 0.12647-0.0752 0.08887-0.11279 0.16748-0.03418 0.0752-0.03418 0.25634l0 2.46436 0.04102 0.08545q0.04443 0.06836 0.12646 0.15381 0.08545 0.08203 0.16065 0.12646 0.07861 0.04102 0.24609 0.04102 0.16748 0 0.24268-0.04102 0.07861-0.04443 0.16064-0.12646 0.08545-0.08545 0.12988-0.15381l0.04102-0.08545 0-2.33789q0-0.2666-0.02051-0.3418-0.02051-0.07861-0.07861-0.16064l-0.01367-0.01367q-0.09912-0.12646-0.2461-0.18116-0.14697-0.05811-0.31445-0.03076z m-0.05469 4.67578q-0.2085 0.05811-0.32129 0.22559-0.11279 0.16748-0.09912 0.37256 0.01367 0.20166 0.15381 0.35547 0.08545 0.08203 0.15381 0.12646 0.21191 0.0957 0.42041 0.03418 0.2085-0.06494 0.33496-0.24609 0.12646-0.18115 0.08545-0.40674-0.01367-0.10938-0.05127-0.17773-0.03418-0.07178-0.11963-0.14014-0.08203-0.07178-0.16064-0.11279-0.0752-0.04443-0.19483-0.05127-0.11621-0.00684-0.20166 0.0205z"
                  fill="#EF4444"
                ></path>
              </svg>
            </div>
            <div
              className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[2px] justify-start items-start"
            >
              <div
                className="text-[13px]/[normal] box-border w-full truncate text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-medium text-left"
              >
                Security Agent flagged vulnerability
              </div>
              <div
                className="text-[11px]/[normal] box-border text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
              >
                Server #srv-prod-3
              </div>
            </div>
            <div
              className="text-[11px]/[normal] box-border text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
            >
              1h ago
            </div>
          </div>
          <div
            className="box-border w-full h-[1px] shrink-0 bg-[var(--ag-divider)]"
          ></div>
          <div
            className="box-border w-full h-fit shrink-0 flex flex-row gap-[10px] p-[10px_0px] justify-start items-start"
          >
            <div
              className="box-border w-[32px] shrink-0 h-[32px] flex flex-row gap-0 justify-center items-center bg-[#8B5CF620] rounded-[16px]"
            >
              <svg
                data-icon-name="file-check"
                data-icon-set="lucide"
                viewBox="0 0 13.99993896484375 14"
                preserveAspectRatio="xMidYMid meet"
                xmlns="http://www.w3.org/2000/svg"
                className="box-border w-[16px] shrink-0 h-[16px]"
              >
                <path
                  d="M3.33252 0.60156q-0.58789 0.04102-1.02197 0.44776-0.43408 0.40674-0.53321 0.99463-0.02734 0.16748-0.02734 4.95605 0 4.78857 0.02734 4.95605 0.09912 0.5332 0.46827 0.92627 0.37256 0.38965 0.90576 0.50245 0.10938 0.01367 0.66992 0.02734l3.17871 0 3.17871 0q0.56055-0.01367 0.66992-0.02734 0.5332-0.11279 0.90235-0.50245 0.37256-0.39307 0.47168-0.92627 0.02734-0.16748 0.02734-3.80078 0-3.6333-0.02734-3.80078-0.08545-0.51953-0.40674-0.92285-0.11279-0.14014-1.24756-1.2749-0.89551-0.88184-1.10742-1.06983-0.2085-0.19141-0.41699-0.29052-0.30762-0.15381-0.67334-0.19483-0.14014-0.02734-2.4917-0.02734-2.35156 0-2.54639 0.02734z m4.25537 2.42334l0 1.27149 0.04102 0.14013q0.08545 0.22559 0.24609 0.40674 0.16064 0.18115 0.35547 0.28028 0.14014 0.07178 0.22558 0.08544 0.12646 0.02734 0.40674 0.04102l2.21143 0 0 6.11816q0 0.43408-0.0376 0.51954-0.03418 0.08203-0.11963 0.17431-0.08203 0.08887-0.16406 0.1333l-0.09912 0.04102-7.30762 0-0.09912-0.04102q-0.08203-0.04443-0.16748-0.1333-0.08203-0.09228-0.11963-0.17431-0.03418-0.08545-0.03418-0.70069l0-4.18701 0-4.18701q0-0.61523 0.02734-0.6836 0.05811-0.12646 0.16749-0.23242 0.11279-0.10596 0.23925-0.1333 0.08545-0.01367 2.14307-0.01367l2.07129 0 0.01367 1.2749z m2.21143 0.01367l1.03564 1.03565-2.08496 0 0-1.03565q0-1.03564 0-1.04931l1.04932 1.04931z m-1.18946 3.9751q-0.06836 0.02734-0.12646 0.05127-0.05469 0.02051-1.06299 1.02539l-0.99463 0.99463-0.40674-0.40332q-0.2666-0.2666-0.3623-0.33838-0.12646-0.11279-0.19824-0.14013-0.06836-0.02734-0.19483-0.02735-0.12646 0-0.16748 0.01367-0.04102 0.01367-0.09912 0.04102-0.18115 0.09912-0.28027 0.2666-0.04102 0.08545-0.04102 0.25293l0 0.01367q0 0.14014 0.03418 0.21192 0.0376 0.06836 0.17774 0.22216 0.0957 0.11279 0.48876 0.50586l0.04102 0.04102q0.42041 0.42041 0.55371 0.54687 0.1333 0.12305 0.20166 0.15381 0.14014 0.06836 0.29395 0.05469 0.15381-0.01367 0.28027-0.09912 0.07178-0.05469 1.28857-1.27149 0.86816-0.86816 1.04932-1.06298 0.18457-0.19824 0.21191-0.27002 0.0957-0.27686-0.0581-0.52295-0.15381-0.24609-0.44775-0.25977-0.12646-0.01367-0.18116 0z"
                  fill="#8B5CF6"
                ></path>
              </svg>
            </div>
            <div
              className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[2px] justify-start items-start"
            >
              <div
                className="text-[13px]/[normal] box-border w-full truncate text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-medium text-left"
              >
                Legal Agent reviewed contract
              </div>
              <div
                className="text-[11px]/[normal] box-border text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
              >
                Contract #CT-884
              </div>
            </div>
            <div
              className="text-[11px]/[normal] box-border text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
            >
              2h ago
            </div>
          </div>
        </div>
      </div>
      <div
        className="box-border w-full h-fit shrink-0 flex flex-col gap-[12px] justify-start items-start"
      >
        <div
          className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center"
        >
          <div
            className="text-[16px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]"
          >
            My Tasks
          </div>
          <div
            className="text-[12px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
          >
            View all
          </div>
        </div>
        <div
          className="box-border w-full h-fit shrink-0 flex flex-col gap-[12px] justify-start items-start"
        >
          <div
            className="box-border w-full h-fit shrink-0 flex flex-row gap-[10px] p-[10px_12px] justify-start items-start bg-[var(--ag-card)] rounded-[8px]"
          >
            <div
              className="box-border w-[36px] shrink-0 h-[36px] [background-image:linear-gradient(0deg,_#6D3CE0_0%,_#3B82F6_100%)] bg-no-repeat bg-[length:100%_100%] rounded-full"
            ></div>
            <div
              className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[4px] justify-start items-start"
            >
              <div
                className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center"
              >
                <div
                  className="text-[13px]/[normal] box-border min-w-0 truncate text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]"
                >
                  Deploy new infrastructure
                </div>
                <div
                  className="box-border w-fit shrink-0 h-fit flex flex-row gap-0 p-[2px_8px] justify-start items-start bg-[#22C55E20] rounded-[10px]"
                >
                  <div
                    className="text-[10px]/[normal] box-border text-[#22C55E] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]"
                  >
                    In Progress
                  </div>
                </div>
              </div>
              <div
                className="text-[11px]/[normal] box-border text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
              >
                DevOps Agent
              </div>
              <div
                className="box-border w-full h-fit shrink-0 flex flex-row gap-[8px] justify-start items-center"
              >
                <div
                  className="box-border [flex:1_1_0] h-[4px] bg-[var(--ag-card-border)] rounded-[2px] relative"
                >
                  <div
                    className="box-border w-[70%] h-[4px] absolute left-0 top-0 bg-[#3B82F6] rounded-[2px] [z-index:0]"
                  ></div>
                </div>
                <div
                  className="text-[11px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
                >
                  70%
                </div>
              </div>
            </div>
            <svg
              data-icon-name="ellipsis-vertical"
              data-icon-set="lucide"
              viewBox="0 0 13.99993896484375 14"
              preserveAspectRatio="xMidYMid meet"
              xmlns="http://www.w3.org/2000/svg"
              className="box-border w-[16px] shrink-0 h-[16px]"
            >
              <path
                d="M6.74707 1.77734q-0.30762 0.07178-0.56055 0.30762-0.18115 0.18457-0.2666 0.3794-0.08203 0.19482-0.08203 0.44775 0 0.25293 0.0752 0.44092 0.07861 0.18799 0.2666 0.37939 0.19141 0.18799 0.37939 0.2666 0.18799 0.0752 0.44092 0.0752 0.25293 0 0.44092-0.0752 0.18799-0.07861 0.37597-0.2666 0.19141-0.19141 0.26661-0.37939 0.07861-0.18799 0.07861-0.44092 0-0.36572-0.18115-0.62891-0.21191-0.30762-0.54004-0.44091-0.32813-0.1333-0.69385-0.06495z m0.12647 4.07422q-0.2085 0.01367-0.37598 0.09912-0.23926 0.11279-0.3999 0.31446-0.16064 0.20166-0.23243 0.44091-0.02734 0.11279-0.02734 0.29395 0 0.18115 0.02734 0.29395 0.08545 0.30762 0.30762 0.5332 0.22559 0.22217 0.5332 0.30762 0.11279 0.02734 0.29395 0.02734 0.18115 0 0.29395-0.02734 0.30762-0.08545 0.52978-0.30762 0.22559-0.22559 0.31104-0.5332 0.02734-0.11279 0.02734-0.29395 0-0.18115-0.02734-0.29395-0.07178-0.23926-0.23243-0.44091-0.16064-0.20166-0.3999-0.31446-0.26318-0.14014-0.6289-0.09912z m-0.15381 4.10156q-0.28027 0.0581-0.53321 0.30762-0.19482 0.19824-0.27343 0.38623-0.0752 0.18799-0.0752 0.44092 0 0.36572 0.18115 0.62891 0.23926 0.35205 0.6084 0.47851 0.37256 0.12305 0.7417 0 0.37256-0.12646 0.61182-0.47851 0.18115-0.26318 0.18115-0.62891 0-0.25293-0.07861-0.44092-0.0752-0.18799-0.27002-0.38623-0.25293-0.24951-0.54688-0.30762-0.11279-0.02734-0.27344-0.02734-0.16064 0-0.27343 0.02734z"
                fill="#6B7280" className="fill-[var(--ag-text-muted)]"
              ></path>
            </svg>
          </div>
          <div
            className="box-border w-full h-fit shrink-0 flex flex-row gap-[10px] p-[10px_12px] justify-start items-start bg-[var(--ag-card)] rounded-[8px]"
          >
            <div
              className="box-border w-[36px] shrink-0 h-[36px] [background-image:linear-gradient(0deg,_#6D3CE0_0%,_#3B82F6_100%)] bg-no-repeat bg-[length:100%_100%] rounded-full"
            ></div>
            <div
              className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[4px] justify-start items-start"
            >
              <div
                className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center"
              >
                <div
                  className="text-[13px]/[normal] box-border min-w-0 truncate text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]"
                >
                  Analyze Q2 financials
                </div>
                <div
                  className="box-border w-fit shrink-0 h-fit flex flex-row gap-0 p-[2px_8px] justify-start items-start bg-[#22C55E20] rounded-[10px]"
                >
                  <div
                    className="text-[10px]/[normal] box-border text-[#22C55E] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]"
                  >
                    In Progress
                  </div>
                </div>
              </div>
              <div
                className="text-[11px]/[normal] box-border text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
              >
                Finance Agent
              </div>
              <div
                className="box-border w-full h-fit shrink-0 flex flex-row gap-[8px] justify-start items-center"
              >
                <div
                  className="box-border [flex:1_1_0] h-[4px] bg-[var(--ag-card-border)] rounded-[2px] relative"
                >
                  <div
                    className="box-border w-[45%] h-[4px] absolute left-0 top-0 bg-[#3B82F6] rounded-[2px] [z-index:0]"
                  ></div>
                </div>
                <div
                  className="text-[11px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
                >
                  45%
                </div>
              </div>
            </div>
            <svg
              data-icon-name="ellipsis-vertical"
              data-icon-set="lucide"
              viewBox="0 0 13.99993896484375 14"
              preserveAspectRatio="xMidYMid meet"
              xmlns="http://www.w3.org/2000/svg"
              className="box-border w-[16px] shrink-0 h-[16px]"
            >
              <path
                d="M6.74707 1.77734q-0.30762 0.07178-0.56055 0.30762-0.18115 0.18457-0.2666 0.3794-0.08203 0.19482-0.08203 0.44775 0 0.25293 0.0752 0.44092 0.07861 0.18799 0.2666 0.37939 0.19141 0.18799 0.37939 0.2666 0.18799 0.0752 0.44092 0.0752 0.25293 0 0.44092-0.0752 0.18799-0.07861 0.37597-0.2666 0.19141-0.19141 0.26661-0.37939 0.07861-0.18799 0.07861-0.44092 0-0.36572-0.18115-0.62891-0.21191-0.30762-0.54004-0.44091-0.32813-0.1333-0.69385-0.06495z m0.12647 4.07422q-0.2085 0.01367-0.37598 0.09912-0.23926 0.11279-0.3999 0.31446-0.16064 0.20166-0.23243 0.44091-0.02734 0.11279-0.02734 0.29395 0 0.18115 0.02734 0.29395 0.08545 0.30762 0.30762 0.5332 0.22559 0.22217 0.5332 0.30762 0.11279 0.02734 0.29395 0.02734 0.18115 0 0.29395-0.02734 0.30762-0.08545 0.52978-0.30762 0.22559-0.22559 0.31104-0.5332 0.02734-0.11279 0.02734-0.29395 0-0.18115-0.02734-0.29395-0.07178-0.23926-0.23243-0.44091-0.16064-0.20166-0.3999-0.31446-0.26318-0.14014-0.6289-0.09912z m-0.15381 4.10156q-0.28027 0.0581-0.53321 0.30762-0.19482 0.19824-0.27343 0.38623-0.0752 0.18799-0.0752 0.44092 0 0.36572 0.18115 0.62891 0.23926 0.35205 0.6084 0.47851 0.37256 0.12305 0.7417 0 0.37256-0.12646 0.61182-0.47851 0.18115-0.26318 0.18115-0.62891 0-0.25293-0.07861-0.44092-0.0752-0.18799-0.27002-0.38623-0.25293-0.24951-0.54688-0.30762-0.11279-0.02734-0.27344-0.02734-0.16064 0-0.27343 0.02734z"
                fill="#6B7280" className="fill-[var(--ag-text-muted)]"
              ></path>
            </svg>
          </div>
          <div
            className="box-border w-full h-fit shrink-0 flex flex-row gap-[10px] p-[10px_12px] justify-start items-start bg-[var(--ag-card)] rounded-[8px]"
          >
            <div
              className="box-border w-[36px] shrink-0 h-[36px] [background-image:linear-gradient(0deg,_#6D3CE0_0%,_#3B82F6_100%)] bg-no-repeat bg-[length:100%_100%] rounded-full"
            ></div>
            <div
              className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[4px] justify-start items-start"
            >
              <div
                className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center"
              >
                <div
                  className="text-[13px]/[normal] box-border min-w-0 truncate text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]"
                >
                  Review security scan
                </div>
                <div
                  className="box-border w-fit shrink-0 h-fit flex flex-row gap-0 p-[2px_8px] justify-start items-start bg-[#F59E0B20] rounded-[10px]"
                >
                  <div
                    className="text-[10px]/[normal] box-border text-[#F59E0B] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]"
                  >
                    Pending Review
                  </div>
                </div>
              </div>
              <div
                className="text-[11px]/[normal] box-border text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
              >
                Security Agent
              </div>
              <div
                className="text-[11px]/[normal] box-border text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
              >
                Waiting for approval
              </div>
            </div>
            <svg
              data-icon-name="ellipsis-vertical"
              data-icon-set="lucide"
              viewBox="0 0 13.99993896484375 14"
              preserveAspectRatio="xMidYMid meet"
              xmlns="http://www.w3.org/2000/svg"
              className="box-border w-[16px] shrink-0 h-[16px]"
            >
              <path
                d="M6.74707 1.77734q-0.30762 0.07178-0.56055 0.30762-0.18115 0.18457-0.2666 0.3794-0.08203 0.19482-0.08203 0.44775 0 0.25293 0.0752 0.44092 0.07861 0.18799 0.2666 0.37939 0.19141 0.18799 0.37939 0.2666 0.18799 0.0752 0.44092 0.0752 0.25293 0 0.44092-0.0752 0.18799-0.07861 0.37597-0.2666 0.19141-0.19141 0.26661-0.37939 0.07861-0.18799 0.07861-0.44092 0-0.36572-0.18115-0.62891-0.21191-0.30762-0.54004-0.44091-0.32813-0.1333-0.69385-0.06495z m0.12647 4.07422q-0.2085 0.01367-0.37598 0.09912-0.23926 0.11279-0.3999 0.31446-0.16064 0.20166-0.23243 0.44091-0.02734 0.11279-0.02734 0.29395 0 0.18115 0.02734 0.29395 0.08545 0.30762 0.30762 0.5332 0.22559 0.22217 0.5332 0.30762 0.11279 0.02734 0.29395 0.02734 0.18115 0 0.29395-0.02734 0.30762-0.08545 0.52978-0.30762 0.22559-0.22559 0.31104-0.5332 0.02734-0.11279 0.02734-0.29395 0-0.18115-0.02734-0.29395-0.07178-0.23926-0.23243-0.44091-0.16064-0.20166-0.3999-0.31446-0.26318-0.14014-0.6289-0.09912z m-0.15381 4.10156q-0.28027 0.0581-0.53321 0.30762-0.19482 0.19824-0.27343 0.38623-0.0752 0.18799-0.0752 0.44092 0 0.36572 0.18115 0.62891 0.23926 0.35205 0.6084 0.47851 0.37256 0.12305 0.7417 0 0.37256-0.12646 0.61182-0.47851 0.18115-0.26318 0.18115-0.62891 0-0.25293-0.07861-0.44092-0.0752-0.18799-0.27002-0.38623-0.25293-0.24951-0.54688-0.30762-0.11279-0.02734-0.27344-0.02734-0.16064 0-0.27343 0.02734z"
                fill="#6B7280" className="fill-[var(--ag-text-muted)]"
              ></path>
            </svg>
          </div>
          <div
            className="box-border w-full h-fit shrink-0 flex flex-row gap-[10px] p-[10px_12px] justify-start items-start bg-[var(--ag-card)] rounded-[8px]"
          >
            <div
              className="box-border w-[36px] shrink-0 h-[36px] [background-image:linear-gradient(0deg,_#6D3CE0_0%,_#3B82F6_100%)] bg-no-repeat bg-[length:100%_100%] rounded-full"
            ></div>
            <div
              className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[4px] justify-start items-start"
            >
              <div
                className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center"
              >
                <div
                  className="text-[13px]/[normal] box-border min-w-0 truncate text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]"
                >
                  Generate marketing report
                </div>
                <div
                  className="box-border w-fit shrink-0 h-fit flex flex-row gap-0 p-[2px_8px] justify-start items-start bg-[#22C55E20] rounded-[10px]"
                >
                  <div
                    className="text-[10px]/[normal] box-border text-[#22C55E] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]"
                  >
                    Completed
                  </div>
                </div>
              </div>
              <div
                className="text-[11px]/[normal] box-border text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
              >
                Marketing Agent
              </div>
              <div
                className="box-border w-full h-fit shrink-0 flex flex-row gap-[8px] justify-start items-center"
              >
                <div
                  className="box-border [flex:1_1_0] h-[4px] bg-[var(--ag-card-border)] rounded-[2px] relative"
                >
                  <div
                    className="box-border w-[100%] h-[4px] absolute left-0 top-0 bg-[#22C55E] rounded-[2px] [z-index:0]"
                  ></div>
                </div>
                <div
                  className="text-[11px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
                >
                  100%
                </div>
              </div>
            </div>
            <svg
              data-icon-name="ellipsis-vertical"
              data-icon-set="lucide"
              viewBox="0 0 13.99993896484375 14"
              preserveAspectRatio="xMidYMid meet"
              xmlns="http://www.w3.org/2000/svg"
              className="box-border w-[16px] shrink-0 h-[16px]"
            >
              <path
                d="M6.74707 1.77734q-0.30762 0.07178-0.56055 0.30762-0.18115 0.18457-0.2666 0.3794-0.08203 0.19482-0.08203 0.44775 0 0.25293 0.0752 0.44092 0.07861 0.18799 0.2666 0.37939 0.19141 0.18799 0.37939 0.2666 0.18799 0.0752 0.44092 0.0752 0.25293 0 0.44092-0.0752 0.18799-0.07861 0.37597-0.2666 0.19141-0.19141 0.26661-0.37939 0.07861-0.18799 0.07861-0.44092 0-0.36572-0.18115-0.62891-0.21191-0.30762-0.54004-0.44091-0.32813-0.1333-0.69385-0.06495z m0.12647 4.07422q-0.2085 0.01367-0.37598 0.09912-0.23926 0.11279-0.3999 0.31446-0.16064 0.20166-0.23243 0.44091-0.02734 0.11279-0.02734 0.29395 0 0.18115 0.02734 0.29395 0.08545 0.30762 0.30762 0.5332 0.22559 0.22217 0.5332 0.30762 0.11279 0.02734 0.29395 0.02734 0.18115 0 0.29395-0.02734 0.30762-0.08545 0.52978-0.30762 0.22559-0.22559 0.31104-0.5332 0.02734-0.11279 0.02734-0.29395 0-0.18115-0.02734-0.29395-0.07178-0.23926-0.23243-0.44091-0.16064-0.20166-0.3999-0.31446-0.26318-0.14014-0.6289-0.09912z m-0.15381 4.10156q-0.28027 0.0581-0.53321 0.30762-0.19482 0.19824-0.27343 0.38623-0.0752 0.18799-0.0752 0.44092 0 0.36572 0.18115 0.62891 0.23926 0.35205 0.6084 0.47851 0.37256 0.12305 0.7417 0 0.37256-0.12646 0.61182-0.47851 0.18115-0.26318 0.18115-0.62891 0-0.25293-0.07861-0.44092-0.0752-0.18799-0.27002-0.38623-0.25293-0.24951-0.54688-0.30762-0.11279-0.02734-0.27344-0.02734-0.16064 0-0.27343 0.02734z"
                fill="#6B7280" className="fill-[var(--ag-text-muted)]"
              ></path>
            </svg>
          </div>
        </div>
      </div>
      <div
        className="box-border w-full h-fit shrink-0 flex flex-col gap-[12px] justify-start items-start"
      >
        <div
          className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center"
        >
          <div
            className="text-[16px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]"
          >
            Wallet &amp; Balance
          </div>
          <div
            className="text-[12px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
          >
            View all
          </div>
        </div>
        <div
          className="box-border w-full h-fit shrink-0 flex flex-col gap-[6px] p-[16px_18px] justify-start items-start [background-image:linear-gradient(0deg,_#7C3AED_0%,_#4F46E5_100%)] bg-no-repeat bg-[length:100%_100%] rounded-[12px]"
        >
          <div
            className="text-[12px]/[normal] box-border text-[#FFFFFFB0] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
          >
            Total Balance
          </div>
          <div
            className="text-[28px]/[normal] box-border text-[#FFFFFF] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]"
          >
            $12,540.75
          </div>
          <div
            className="text-[12px]/[normal] box-border text-[#86EFAC] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
          >
            +18.6% this month
          </div>
        </div>
        <div
          className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-start items-start"
        >
          <div
            className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[4px] justify-start items-center"
          >
            <div
              className="text-[11px]/[normal] box-border text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
            >
              Escrow
            </div>
            <div
              className="text-[13px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]"
            >
              $4,230.00
            </div>
          </div>
          <div
            className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[4px] justify-start items-center"
          >
            <div
              className="text-[11px]/[normal] box-border text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
            >
              Available
            </div>
            <div
              className="text-[13px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]"
            >
              $6,870.75
            </div>
          </div>
          <div
            className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[4px] justify-start items-center"
          >
            <div
              className="text-[11px]/[normal] box-border text-[var(--ag-text-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
            >
              Pending
            </div>
            <div
              className="text-[13px]/[normal] box-border text-[var(--ag-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]"
            >
              $1,440.00
            </div>
          </div>
        </div>
        <div
          className="box-border w-full h-fit shrink-0 flex flex-row gap-[10px] justify-start items-start"
        >
          <div
            className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-row gap-[6px] p-[10px_0px] justify-center items-center bg-[#6D3CE0] rounded-[8px]"
          >
            <div
              className="text-[13px]/[normal] box-border text-[#FFFFFF] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]"
            >
              + Add Funds
            </div>
          </div>
          <div
            className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-row gap-[6px] p-[10px_0px] justify-center items-center [border:1px_solid_var(--ag-card-border)] rounded-[8px]"
          >
            <svg
              data-icon-name="arrow-up-right"
              data-icon-set="lucide"
              viewBox="0 0 13.99993896484375 14"
              preserveAspectRatio="xMidYMid meet"
              xmlns="http://www.w3.org/2000/svg"
              className="box-border w-[14px] shrink-0 h-[14px]"
            >
              <path
                d="M3.94775 3.51367q-0.14014 0.04102-0.25976 0.15381-0.11963 0.11279-0.16065 0.25293-0.05469 0.19482 0.02735 0.39307 0.08545 0.19482 0.25293 0.29394 0.08545 0.02734 0.19482 0.04102 0.1709 0.01367 0.65967 0.02734l3.83496 0-2.45068 2.45068q-1.65088 1.65088-2.05762 2.07129-0.40332 0.42041-0.43408 0.4751-0.10938 0.23926-0.01367 0.46485 0.09912 0.22217 0.32128 0.32128 0.22559 0.0957 0.46485-0.01367 0.05469-0.03076 0.4751-0.43408 0.42041-0.40674 2.07129-2.05762l2.45068-2.45068 0 2.21143q0 2.2251 0.02734 2.31054 0.02734 0.18115 0.15381 0.29395 0.19824 0.19482 0.46143 0.17431 0.2666-0.02051 0.42041-0.24609l0.02734-0.02734q0.04443-0.05469 0.05811-0.18116 0.01367-0.15381 0.02734-0.68701l0-5.37646-0.04102-0.09571q-0.02734-0.11279-0.12646-0.21191-0.09912-0.09912-0.21192-0.12646l-0.0957-0.04102-3.01123 0q-2.99414 0-3.06592 0.01367z"
                fill="#9CA3AF" className="fill-[var(--ag-text-secondary)]"
              ></path>
            </svg>
            <div
              className="text-[13px]/[normal] box-border text-[var(--ag-text-secondary)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]"
            >
              Send Payment
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
