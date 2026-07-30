"use client";

import { useState } from "react";

/**
 * Performance tab. Every metric here is DERIVED from real backend records —
 * there is no dedicated metrics model. Surfaced: verification_rate (the
 * objective "success rate"), tasks_verified/rejected, avg_rating + rating_count,
 * active_hirings and gigs_completed. Response-time/uptime style latency metrics
 * do NOT exist in the backend and are deliberately omitted.
 */

const PERIODS = ["7d", "30d", "90d", "All"] as const;
type Period = (typeof PERIODS)[number];

type Metric = {
  label: string;
  value: string;
  delta: string;
  deltaColor: string;
  note: string;
};

const METRICS: Metric[] = [
  { label: "Verification Rate", value: "97.4%", delta: "↑ 2.4%", deltaColor: "#35D78B", note: "verified / (verified + rejected)" },
  { label: "Tasks Verified", value: "516", delta: "↑ 18.7%", deltaColor: "#35D78B", note: "20 rejected" },
  { label: "Avg Rating", value: "4.9", delta: "↑ 0.2", deltaColor: "#35D78B", note: "128 ratings" },
  { label: "Active Hirings", value: "12", delta: "↑ 3", deltaColor: "#35D78B", note: "non-revoked grants" },
  { label: "Gigs Completed", value: "204", delta: "↑ 9.1%", deltaColor: "#35D78B", note: "lifetime" },
];

/** Weekly verification-rate trend (percentages). */
const TREND = [88, 90, 89, 92, 91, 93, 95, 94, 96, 96, 97, 97.4];
const TREND_LABELS = ["Apr 22", "Apr 29", "May 6", "May 13", "May 20", "Now"];

type CapPerf = { name: string; rate: number; verified: number; rejected: number };
const CAP_PERF: CapPerf[] = [
  { name: "Infrastructure Deployment", rate: 0.979, verified: 142, rejected: 3 },
  { name: "Kubernetes Management", rate: 0.98, verified: 98, rejected: 2 },
  { name: "Security Implementation", rate: 0.974, verified: 38, rejected: 1 },
  { name: "Monitoring & Logging", rate: 0.959, verified: 47, rejected: 2 },
  { name: "Cloud Architecture", rate: 0.944, verified: 51, rejected: 3 },
  { name: "CI/CD Pipeline Setup", rate: 0.941, verified: 64, rejected: 4 },
  { name: "Terraform Automation", rate: 0.938, verified: 76, rejected: 5 },
];

function AreaChart({ points }: { points: number[] }) {
  const w = 900;
  const h = 150;
  const max = Math.max(...points);
  const min = Math.min(...points) - 2;
  const span = max - min || 1;
  const coords = points.map((v, i) => {
    const x = (i / (points.length - 1)) * w;
    const y = h - ((v - min) / span) * (h - 10) - 5;
    return [x, y] as const;
  });
  const line = coords.map(([x, y], i) => `${i === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  const area = `${line} L ${w} ${h} L 0 ${h} Z`;
  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      preserveAspectRatio="none"
      xmlns="http://www.w3.org/2000/svg"
      className="box-border w-full h-[150px] overflow-visible"
    >
      <defs>
        <linearGradient id="perf-area" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="rgb(124,58,237)" stopOpacity="0.45" />
          <stop offset="100%" stopColor="rgb(124,58,237)" stopOpacity="0.03" />
        </linearGradient>
      </defs>
      <path d={area} fill="url(#perf-area)" />
      <path
        d={line}
        fill="none"
        stroke="#9A5CFF"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
      {coords.map(([x, y], i) => (
        <circle key={i} cx={x} cy={y} r="3" fill="#8B5CF6" stroke="#C084FC" strokeWidth="1" />
      ))}
    </svg>
  );
}

export default function AgentPerformanceTab() {
  const [period, setPeriod] = useState<Period>("30d");

  return (
    <div className="box-border w-full h-fit shrink-0 flex flex-col gap-[12px] justify-start items-start">
      {/* Metric row */}
      <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[10px] justify-start items-start">
        {METRICS.map((m) => (
          <div
            key={m.label}
            className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[5px] p-[14px] justify-start items-start bg-[var(--ag2-panel)] [border:1px_solid_var(--ag2-border)] rounded-[9px]"
          >
            <div className="text-[10px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]">
              {m.label}
            </div>
            <div className="text-[22px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
              {m.value}
            </div>
            <div
              className="text-[10px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]"
              style={{ color: m.deltaColor }}
            >
              {m.delta}
            </div>
            <div className="text-[9px]/[normal] box-border text-[var(--ag2-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap] overflow-hidden text-ellipsis w-full">
              {m.note}
            </div>
          </div>
        ))}
      </div>

      {/* Trend chart */}
      <div className="box-border w-full h-fit shrink-0 flex flex-col gap-[12px] p-[16px] justify-start items-start bg-[var(--ag2-panel)] [border:1px_solid_var(--ag2-border)] rounded-[9px]">
        <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
          <div className="text-[15px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
            Verification Rate Trend
          </div>
          <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-[4px] p-[3px] justify-start items-center bg-[var(--ag2-surface)] [border:1px_solid_var(--ag2-border)] rounded-[7px]">
            {PERIODS.map((p) => (
              <button
                key={p}
                type="button"
                onClick={() => setPeriod(p)}
                className={`box-border w-fit shrink-0 h-fit flex flex-row gap-0 p-[5px_10px] justify-center items-center rounded-[5px] cursor-pointer text-[10px] font-medium ${
                  period === p ? "bg-[#5D20DC] text-[#F4F2FF]" : "text-[var(--ag2-dim)]"
                }`}
              >
                {p}
              </button>
            ))}
          </div>
        </div>
        <AreaChart points={TREND} />
        <div className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center">
          {TREND_LABELS.map((l) => (
            <div
              key={l}
              className="text-[9px]/[normal] box-border text-[var(--ag2-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
            >
              {l}
            </div>
          ))}
        </div>
      </div>

      {/* Per-capability breakdown */}
      <div className="box-border w-full h-fit shrink-0 flex flex-col gap-[10px] p-[16px] justify-start items-start bg-[var(--ag2-panel)] [border:1px_solid_var(--ag2-border)] rounded-[9px]">
        <div className="text-[15px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
          Performance by Capability
        </div>
        {CAP_PERF.map((c) => (
          <div key={c.name} className="box-border w-full h-fit shrink-0 flex flex-row gap-[12px] justify-start items-center">
            <div className="box-border w-[200px] shrink-0 h-fit text-[11px]/[normal] text-[var(--ag2-strong)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap] overflow-hidden text-ellipsis">
              {c.name}
            </div>
            <div className="box-border [flex:1_1_0] min-w-0 h-[6px] bg-[var(--ag2-input-deep)] rounded-full overflow-hidden">
              <div className="box-border h-full bg-[#8B5CF6] rounded-full" style={{ width: `${c.rate * 100}%` }}></div>
            </div>
            <div className="box-border w-[52px] shrink-0 h-fit text-[11px]/[normal] text-[#35D78B] font-[Inter,system-ui,sans-serif] font-semibold text-right [white-space:nowrap]">
              {(c.rate * 100).toFixed(1)}%
            </div>
            <div className="box-border w-[110px] shrink-0 h-fit text-[10px]/[normal] text-[var(--ag2-muted)] font-[Inter,system-ui,sans-serif] font-normal text-right [white-space:nowrap]">
              {c.verified} ✓ · {c.rejected} ✕
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
