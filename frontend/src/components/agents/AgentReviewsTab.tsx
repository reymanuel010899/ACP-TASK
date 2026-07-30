/**
 * Reviews tab. Subjective ratings from the marketplace hiring model: each entry
 * is (user_principal_id, rating 1-5, review_text, created_at); only users with a
 * non-revoked hiring grant can rate, and re-rating replaces. Summary is
 * (avg_rating, rating_count). This is separate from the objective
 * verification_rate shown in Performance.
 */

type Review = {
  user: string;
  principal: string;
  rating: number;
  text: string;
  createdAt: string;
};

const AVG_RATING = 4.9;
const RATING_COUNT = 128;

/** distribution[5..1] = count of ratings at that star value. */
const DISTRIBUTION: { stars: number; count: number }[] = [
  { stars: 5, count: 108 },
  { stars: 4, count: 15 },
  { stars: 3, count: 3 },
  { stars: 2, count: 1 },
  { stars: 1, count: 1 },
];

const REVIEWS: Review[] = [
  {
    user: "TechCorp Inc.",
    principal: "z6Mk…8ac4",
    rating: 5,
    text: "Flawless EKS migration. Blue/green rollout worked first try and the agent documented every step. Would hire again.",
    createdAt: "May 20, 2024",
  },
  {
    user: "DataFlow Systems",
    principal: "z6Mk…1e08",
    rating: 5,
    text: "Cut our CI pipeline time by 40%. Clear communication throughout the negotiation and delivery.",
    createdAt: "May 18, 2024",
  },
  {
    user: "InnovateLabs",
    principal: "z6Mk…6b71",
    rating: 4,
    text: "Solid multi-environment Terraform setup. Minor rework needed on the staging variables but resolved quickly.",
    createdAt: "May 15, 2024",
  },
  {
    user: "SecureOps",
    principal: "z6Mk…33fa",
    rating: 5,
    text: "IAM hardening was thorough and evidence-backed. Verification passed on the first submission.",
    createdAt: "May 10, 2024",
  },
  {
    user: "Growth Labs",
    principal: "z6Mk…70cd",
    rating: 5,
    text: "Observability stack delivered ahead of schedule. Grafana dashboards were production-ready.",
    createdAt: "May 04, 2024",
  },
];

function Stars({ count, size = 12 }: { count: number; size?: number }) {
  return (
    <div
      className="box-border font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
      style={{ fontSize: `${size}px`, lineHeight: "normal" }}
    >
      <span className="text-[#FBBF24]">{"★".repeat(count)}</span>
      <span className="text-[var(--ag2-muted)]">{"★".repeat(5 - count)}</span>
    </div>
  );
}

export default function AgentReviewsTab() {
  return (
    <div className="box-border w-full h-fit shrink-0 flex flex-col gap-[12px] justify-start items-start">
      {/* Summary */}
      <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[12px] justify-start items-stretch">
        <div className="box-border w-[200px] shrink-0 h-fit flex flex-col gap-[6px] p-[18px] justify-center items-center bg-[var(--ag2-panel)] [border:1px_solid_var(--ag2-border)] rounded-[9px]">
          <div className="text-[40px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-center [white-space:nowrap]">
            {AVG_RATING.toFixed(1)}
          </div>
          <Stars count={5} size={16} />
          <div className="text-[11px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-center [white-space:nowrap]">
            {RATING_COUNT} ratings
          </div>
        </div>
        <div className="box-border [flex:1_1_0] min-w-0 h-fit flex flex-col gap-[8px] p-[16px] justify-center items-start bg-[var(--ag2-panel)] [border:1px_solid_var(--ag2-border)] rounded-[9px]">
          {DISTRIBUTION.map((d) => (
            <div key={d.stars} className="box-border w-full h-fit shrink-0 flex flex-row gap-[10px] justify-start items-center">
              <div className="box-border w-[36px] shrink-0 h-fit text-[10px]/[normal] text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]">
                {d.stars} ★
              </div>
              <div className="box-border [flex:1_1_0] min-w-0 h-[7px] bg-[var(--ag2-input-deep)] rounded-full overflow-hidden">
                <div
                  className="box-border h-full bg-[#FBBF24] rounded-full"
                  style={{ width: `${(d.count / RATING_COUNT) * 100}%` }}
                ></div>
              </div>
              <div className="box-border w-[36px] shrink-0 h-fit text-[10px]/[normal] text-[var(--ag2-muted)] font-[Inter,system-ui,sans-serif] font-normal text-right [white-space:nowrap]">
                {d.count}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Review list */}
      <div className="box-border w-full h-fit shrink-0 flex flex-col gap-0 justify-start items-start bg-[var(--ag2-panel)] [border:1px_solid_var(--ag2-border)] rounded-[9px] overflow-hidden">
        {REVIEWS.map((r, idx) => (
          <div
            key={r.principal}
            className={`box-border w-full h-fit shrink-0 flex flex-col gap-[7px] p-[14px_16px] justify-start items-start ${
              idx === 0 ? "" : "[border-width:1px_0px_0px_0px] [border-style:solid] [border-color:var(--ag2-border)]"
            }`}
          >
            <div className="box-border w-full h-fit shrink-0 flex flex-row gap-[10px] justify-between items-center">
              <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-[9px] justify-start items-center">
                <div className="box-border w-[28px] shrink-0 h-[28px] flex flex-row gap-0 justify-center items-center bg-[#2A1859] rounded-full">
                  <div className="text-[10px]/[normal] box-border text-[#C69AFF] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]">
                    {r.user.slice(0, 2).toUpperCase()}
                  </div>
                </div>
                <div className="box-border w-fit shrink-0 h-fit flex flex-col gap-[2px] justify-start items-start">
                  <div className="text-[12px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]">
                    {r.user}
                  </div>
                  <div className="text-[9px]/[normal] box-border text-[var(--ag2-muted)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap] font-mono">
                    {r.principal}
                  </div>
                </div>
              </div>
              <div className="box-border w-fit shrink-0 h-fit flex flex-row gap-[8px] justify-end items-center">
                <Stars count={r.rating} />
                <div className="text-[10px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-right [white-space:nowrap]">
                  {r.createdAt}
                </div>
              </div>
            </div>
            <div className="text-[11px]/[normal] box-border w-full text-[var(--ag2-body)] font-[Inter,system-ui,sans-serif] font-normal text-left">
              {r.text}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
