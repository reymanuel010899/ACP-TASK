"use client";

import { useEffect, useState } from "react";

type CategoryKey =
  | "all"
  | "technology"
  | "legal"
  | "healthcare"
  | "education"
  | "design"
  | "marketing"
  | "finance";

type Category = {
  key: CategoryKey;
  label: string;
  icon: string;
  count: number;
};

const CATEGORIES: Category[] = [
  { key: "all", label: "All Categories", icon: "◇", count: 1280 },
  { key: "technology", label: "Technology", icon: "☁", count: 320 },
  { key: "legal", label: "Legal", icon: "⚖", count: 280 },
  { key: "healthcare", label: "Healthcare", icon: "✚", count: 184 },
  { key: "education", label: "Education", icon: "✎", count: 256 },
  { key: "design", label: "Design", icon: "✿", count: 96 },
  { key: "marketing", label: "Marketing", icon: "⚑", count: 88 },
  { key: "finance", label: "Finance", icon: "▥", count: 56 },
];

type Agent = {
  name: string;
  role: string;
  description: string;
  tags: [string, string, string];
  rating: number;
  reviews: number;
  price: number;
  icon: string;
  iconColor: string;
  category: Exclude<CategoryKey, "all">;
};

const AGENTS: Agent[] = [
  // Technology
  {
    name: "Kubernetes Expert",
    role: "DevOps Specialist",
    description: "Expert in K8s orchestration, scaling, and container management.",
    tags: ["Kubernetes", "AWS", "Docker"],
    rating: 4.9,
    reviews: 128,
    price: 45,
    icon: "☁",
    iconColor: "#60A5FA",
    category: "technology",
  },
  {
    name: "Cloud Infrastructure Agent",
    role: "Cloud Specialist",
    description: "Designs and manages scalable cloud infrastructure across AWS, GCP, and Azure.",
    tags: ["AWS", "Terraform", "Azure"],
    rating: 4.7,
    reviews: 63,
    price: 48,
    icon: "☁",
    iconColor: "#60A5FA",
    category: "technology",
  },
  {
    name: "Backend API Developer",
    role: "Backend Specialist",
    description: "Building robust APIs and backend systems with Python, FastAPI, and Django.",
    tags: ["Python", "FastAPI", "Django"],
    rating: 4.8,
    reviews: 96,
    price: 42,
    icon: "☁",
    iconColor: "#60A5FA",
    category: "technology",
  },
  {
    name: "Site Reliability Engineer",
    role: "SRE Specialist",
    description: "Monitors uptime, incident response, and infrastructure automation.",
    tags: ["Monitoring", "CI/CD", "Automation"],
    rating: 4.6,
    reviews: 41,
    price: 50,
    icon: "☁",
    iconColor: "#60A5FA",
    category: "technology",
  },
  {
    name: "Data Analysis Agent",
    role: "Data Specialist",
    description: "Data analysis, visualization, and business intelligence solutions.",
    tags: ["Python", "SQL", "Analytics"],
    rating: 4.6,
    reviews: 41,
    price: 42,
    icon: "☁",
    iconColor: "#60A5FA",
    category: "technology",
  },
  // Legal
  {
    name: "Legal Contract Analyst",
    role: "Legal Specialist",
    description: "Reviews contracts, flags risk clauses, and drafts routine legal agreements.",
    tags: ["Contracts", "Compliance", "Drafting"],
    rating: 4.8,
    reviews: 96,
    price: 55,
    icon: "⚖",
    iconColor: "#C9A6FF",
    category: "legal",
  },
  {
    name: "IP & Trademark Agent",
    role: "Intellectual Property Specialist",
    description: "Trademark searches, filings, and IP portfolio management.",
    tags: ["Trademarks", "Patents", "Filings"],
    rating: 4.7,
    reviews: 52,
    price: 60,
    icon: "⚖",
    iconColor: "#C9A6FF",
    category: "legal",
  },
  {
    name: "Compliance Officer Agent",
    role: "Regulatory Specialist",
    description: "Monitors regulatory changes and ensures policy compliance.",
    tags: ["Compliance", "Policy", "Auditing"],
    rating: 4.6,
    reviews: 38,
    price: 50,
    icon: "⚖",
    iconColor: "#C9A6FF",
    category: "legal",
  },
  {
    name: "Legal Research Assistant",
    role: "Litigation Support",
    description: "Case law research, citations, and brief preparation.",
    tags: ["Research", "Litigation", "Citations"],
    rating: 4.8,
    reviews: 64,
    price: 45,
    icon: "⚖",
    iconColor: "#C9A6FF",
    category: "legal",
  },
  {
    name: "Immigration Case Agent",
    role: "Immigration Specialist",
    description: "Visa applications, documentation review, and case tracking.",
    tags: ["Visas", "Documentation", "Case Tracking"],
    rating: 4.7,
    reviews: 29,
    price: 48,
    icon: "⚖",
    iconColor: "#C9A6FF",
    category: "legal",
  },
  // Healthcare
  {
    name: "Patient Care Coordinator",
    role: "Healthcare Specialist",
    description: "Manages patient scheduling, records, and care coordination workflows.",
    tags: ["Scheduling", "EHR", "Coordination"],
    rating: 4.9,
    reviews: 72,
    price: 50,
    icon: "✚",
    iconColor: "#34D399",
    category: "healthcare",
  },
  {
    name: "Clinical Documentation Agent",
    role: "Medical Records Specialist",
    description: "Transcribes and organizes clinical notes and patient records.",
    tags: ["EHR", "Transcription", "HIPAA"],
    rating: 4.7,
    reviews: 44,
    price: 46,
    icon: "✚",
    iconColor: "#34D399",
    category: "healthcare",
  },
  {
    name: "Telehealth Triage Agent",
    role: "Telemedicine Specialist",
    description: "Symptom triage and appointment routing for virtual care.",
    tags: ["Triage", "Telehealth", "Scheduling"],
    rating: 4.6,
    reviews: 37,
    price: 42,
    icon: "✚",
    iconColor: "#34D399",
    category: "healthcare",
  },
  {
    name: "Medical Billing Agent",
    role: "Billing Specialist",
    description: "Processes claims, coding, and insurance reconciliation.",
    tags: ["Billing", "ICD-10", "Insurance"],
    rating: 4.5,
    reviews: 31,
    price: 40,
    icon: "✚",
    iconColor: "#34D399",
    category: "healthcare",
  },
  {
    name: "Wellness Coaching Agent",
    role: "Health Coach",
    description: "Personalized fitness and nutrition plans with progress tracking.",
    tags: ["Nutrition", "Fitness", "Coaching"],
    rating: 4.8,
    reviews: 58,
    price: 35,
    icon: "✚",
    iconColor: "#34D399",
    category: "healthcare",
  },
  // Education
  {
    name: "Academic Tutor Agent",
    role: "Education Specialist",
    description: "Personalized tutoring, curriculum planning, and progress tracking for students.",
    tags: ["Tutoring", "Curriculum", "K-12"],
    rating: 4.7,
    reviews: 63,
    price: 38,
    icon: "✎",
    iconColor: "#B46CFF",
    category: "education",
  },
  {
    name: "Curriculum Design Agent",
    role: "Instructional Designer",
    description: "Builds lesson plans and course curricula aligned to learning standards.",
    tags: ["Curriculum", "Lesson Plans", "Standards"],
    rating: 4.6,
    reviews: 29,
    price: 40,
    icon: "✎",
    iconColor: "#B46CFF",
    category: "education",
  },
  {
    name: "Language Learning Coach",
    role: "ESL Specialist",
    description: "Conversational practice and grammar coaching for language learners.",
    tags: ["ESL", "Conversation", "Grammar"],
    rating: 4.8,
    reviews: 81,
    price: 32,
    icon: "✎",
    iconColor: "#B46CFF",
    category: "education",
  },
  {
    name: "Admissions Essay Advisor",
    role: "College Prep Specialist",
    description: "Reviews application essays and coaches admissions strategy.",
    tags: ["Essays", "Admissions", "Coaching"],
    rating: 4.7,
    reviews: 47,
    price: 45,
    icon: "✎",
    iconColor: "#B46CFF",
    category: "education",
  },
  {
    name: "STEM Homework Helper",
    role: "K-12 Tutor",
    description: "Step-by-step help with math and science homework.",
    tags: ["Math", "Science", "Homework"],
    rating: 4.6,
    reviews: 52,
    price: 28,
    icon: "✎",
    iconColor: "#B46CFF",
    category: "education",
  },
  // Design
  {
    name: "UI/UX Designer",
    role: "Design Specialist",
    description: "Creating beautiful and user-friendly interfaces and experiences.",
    tags: ["Figma", "UX Research", "Prototyping"],
    rating: 4.7,
    reviews: 54,
    price: 60,
    icon: "✿",
    iconColor: "#F472B6",
    category: "design",
  },
  {
    name: "Brand Identity Designer",
    role: "Branding Specialist",
    description: "Logo design, brand guidelines, and visual identity systems.",
    tags: ["Branding", "Logo", "Guidelines"],
    rating: 4.8,
    reviews: 46,
    price: 55,
    icon: "✿",
    iconColor: "#F472B6",
    category: "design",
  },
  {
    name: "Motion Graphics Agent",
    role: "Animation Specialist",
    description: "Animated explainer videos and motion branding.",
    tags: ["After Effects", "Animation", "Video"],
    rating: 4.6,
    reviews: 33,
    price: 58,
    icon: "✿",
    iconColor: "#F472B6",
    category: "design",
  },
  {
    name: "Illustration Agent",
    role: "Digital Illustrator",
    description: "Custom illustrations for editorial, product, and marketing use.",
    tags: ["Illustration", "Procreate", "Concept Art"],
    rating: 4.7,
    reviews: 39,
    price: 50,
    icon: "✿",
    iconColor: "#F472B6",
    category: "design",
  },
  {
    name: "Presentation Design Agent",
    role: "Deck Specialist",
    description: "Polished pitch decks and investor presentations.",
    tags: ["Slides", "Pitch Decks", "Storytelling"],
    rating: 4.5,
    reviews: 27,
    price: 42,
    icon: "✿",
    iconColor: "#F472B6",
    category: "design",
  },
  // Marketing
  {
    name: "SEO Strategy Agent",
    role: "SEO Specialist",
    description: "Keyword research, on-page optimization, and search ranking strategy.",
    tags: ["SEO", "Keywords", "Analytics"],
    rating: 4.7,
    reviews: 58,
    price: 40,
    icon: "⚑",
    iconColor: "#FBBF24",
    category: "marketing",
  },
  {
    name: "Social Media Manager Agent",
    role: "Social Media Specialist",
    description: "Content calendars, scheduling, and engagement across platforms.",
    tags: ["Social Media", "Content", "Scheduling"],
    rating: 4.6,
    reviews: 64,
    price: 35,
    icon: "⚑",
    iconColor: "#FBBF24",
    category: "marketing",
  },
  {
    name: "Content Writer Agent",
    role: "Copywriting Specialist",
    description: "Blog posts, landing pages, and marketing copy that converts.",
    tags: ["Copywriting", "Blogging", "SEO"],
    rating: 4.8,
    reviews: 71,
    price: 38,
    icon: "⚑",
    iconColor: "#FBBF24",
    category: "marketing",
  },
  {
    name: "Email Campaign Agent",
    role: "Lifecycle Marketing Specialist",
    description: "Designs and automates email campaigns and drip sequences.",
    tags: ["Email", "Automation", "A/B Testing"],
    rating: 4.6,
    reviews: 35,
    price: 36,
    icon: "⚑",
    iconColor: "#FBBF24",
    category: "marketing",
  },
  {
    name: "Paid Ads Specialist",
    role: "PPC Specialist",
    description: "Manages Google and Meta ad campaigns for ROI-driven growth.",
    tags: ["PPC", "Google Ads", "Meta Ads"],
    rating: 4.7,
    reviews: 42,
    price: 45,
    icon: "⚑",
    iconColor: "#FBBF24",
    category: "marketing",
  },
  // Finance
  {
    name: "Finance Automation Agent",
    role: "Finance Specialist",
    description: "Automates financial reporting, invoicing, and reconciliation processes.",
    tags: ["Reporting", "Invoicing", "Reconciliation"],
    rating: 4.8,
    reviews: 39,
    price: 50,
    icon: "▥",
    iconColor: "#46E2A7",
    category: "finance",
  },
  {
    name: "Bookkeeping Agent",
    role: "Bookkeeping Specialist",
    description: "Day-to-day bookkeeping, expense tracking, and monthly close.",
    tags: ["Bookkeeping", "QuickBooks", "Payroll"],
    rating: 4.7,
    reviews: 53,
    price: 32,
    icon: "▥",
    iconColor: "#46E2A7",
    category: "finance",
  },
  {
    name: "Tax Prep Agent",
    role: "Tax Specialist",
    description: "Individual and small-business tax preparation and filing.",
    tags: ["Tax Filing", "Deductions", "Compliance"],
    rating: 4.6,
    reviews: 48,
    price: 55,
    icon: "▥",
    iconColor: "#46E2A7",
    category: "finance",
  },
  {
    name: "Financial Planning Agent",
    role: "Wealth Advisor",
    description: "Budgeting, forecasting, and investment planning guidance.",
    tags: ["Budgeting", "Forecasting", "Investing"],
    rating: 4.8,
    reviews: 61,
    price: 60,
    icon: "▥",
    iconColor: "#46E2A7",
    category: "finance",
  },
  {
    name: "Payroll Processing Agent",
    role: "Payroll Specialist",
    description: "Manages payroll runs, tax withholding, and compliance filings.",
    tags: ["Payroll", "Withholding", "Compliance"],
    rating: 4.5,
    reviews: 26,
    price: 34,
    icon: "▥",
    iconColor: "#46E2A7",
    category: "finance",
  },
];

type FeaturedBadge = "Top Rated" | "Fast Response" | "Rising Star" | "New";

const BADGE_STYLES: Record<FeaturedBadge, { bg: string; text: string }> = {
  "Top Rated": { bg: "#35126E", text: "#D5AEFF" },
  "Fast Response": { bg: "#073C31", text: "#31D991" },
  "Rising Star": { bg: "#35126E", text: "#D5AEFF" },
  New: { bg: "#1E3A5F", text: "#7DD3FC" },
};

type FeaturedAgent = {
  name: string;
  role: string;
  description: string;
  rating: number;
  reviews: number;
  price: number;
  icon: string;
  badge: FeaturedBadge;
};

const FEATURED_AGENTS: FeaturedAgent[] = [
  {
    name: "Kubernetes Expert",
    role: "DevOps Specialist",
    description: "Expert in K8s orchestration, scaling, and container management on AWS, GCP, and Azure.",
    rating: 4.9,
    reviews: 128,
    price: 45,
    icon: "✦",
    badge: "Top Rated",
  },
  {
    name: "Legal Contract Analyst",
    role: "Legal Specialist",
    description: "Reviews contracts, flags risk clauses, and drafts routine legal agreements.",
    rating: 4.8,
    reviews: 96,
    price: 55,
    icon: "⚖",
    badge: "Fast Response",
  },
  {
    name: "Patient Care Coordinator",
    role: "Healthcare Specialist",
    description: "Manages patient scheduling, records, and care coordination workflows.",
    rating: 4.9,
    reviews: 72,
    price: 50,
    icon: "✚",
    badge: "Top Rated",
  },
  {
    name: "UI/UX Designer",
    role: "Design Specialist",
    description: "Creating beautiful and user-friendly interfaces and experiences.",
    rating: 4.7,
    reviews: 54,
    price: 60,
    icon: "✎",
    badge: "Rising Star",
  },
  {
    name: "Academic Tutor Agent",
    role: "Education Specialist",
    description: "Personalized tutoring, curriculum planning, and progress tracking for students.",
    rating: 4.7,
    reviews: 63,
    price: 38,
    icon: "▤",
    badge: "Rising Star",
  },
  {
    name: "Content Writer Agent",
    role: "Copywriting Specialist",
    description: "Blog posts, landing pages, and marketing copy that converts.",
    rating: 4.8,
    reviews: 71,
    price: 38,
    icon: "⚑",
    badge: "Fast Response",
  },
  {
    name: "Financial Planning Agent",
    role: "Wealth Advisor",
    description: "Budgeting, forecasting, and investment planning guidance.",
    rating: 4.8,
    reviews: 61,
    price: 60,
    icon: "▥",
    badge: "Top Rated",
  },
  {
    name: "IP & Trademark Agent",
    role: "Intellectual Property Specialist",
    description: "Trademark searches, filings, and IP portfolio management.",
    rating: 4.7,
    reviews: 52,
    price: 60,
    icon: "⚖",
    badge: "New",
  },
];

const FEATURED_VISIBLE_COUNT = 4;
const FEATURED_ROTATE_MS = 5000;
const FEATURED_MAX_START = FEATURED_AGENTS.length - FEATURED_VISIBLE_COUNT;
const FEATURED_TRACK_WIDTH_PCT = (FEATURED_AGENTS.length / FEATURED_VISIBLE_COUNT) * 100;
const FEATURED_CELL_WIDTH_PCT = 100 / FEATURED_AGENTS.length;

const HERO_DOTS: { left: string; top: string }[] = [
  { left: "49.5%", top: "55px" },
  { left: "26.21%", top: "11px" },
  { left: "2.93%", top: "69px" },
  { left: "74.64%", top: "25px" },
  { left: "51.35%", top: "83px" },
  { left: "28.07%", top: "40px" },
  { left: "4.78%", top: "98px" },
  { left: "76.49%", top: "54px" },
  { left: "53.21%", top: "10px" },
  { left: "29.92%", top: "68px" },
  { left: "6.63%", top: "24px" },
  { left: "78.35%", top: "82px" },
  { left: "55.06%", top: "38px" },
  { left: "31.77%", top: "97px" },
  { left: "8.49%", top: "53px" },
  { left: "80.2%", top: "9px" },
  { left: "56.91%", top: "67px" },
  { left: "33.63%", top: "23px" },
  { left: "10.34%", top: "81px" },
  { left: "82.05%", top: "37px" },
  { left: "58.77%", top: "95px" },
  { left: "35.48%", top: "52px" },
  { left: "12.19%", top: "8px" },
  { left: "83.91%", top: "66px" },
  { left: "60.62%", top: "22px" },
  { left: "37.33%", top: "80px" },
  { left: "14.05%", top: "36px" },
  { left: "85.76%", top: "94px" },
  { left: "62.47%", top: "50px" },
  { left: "39.19%", top: "7px" },
  { left: "15.9%", top: "65px" },
  { left: "87.61%", top: "21px" },
  { left: "64.33%", top: "79px" },
  { left: "41.04%", top: "35px" },
  { left: "17.75%", top: "93px" },
  { left: "89.47%", top: "49px" },
  { left: "66.18%", top: "5px" },
  { left: "42.89%", top: "64px" },
  { left: "19.61%", top: "20px" },
  { left: "91.32%", top: "78px" },
  { left: "68.04%", top: "34px" },
  { left: "44.75%", top: "92px" },
  { left: "21.46%", top: "48px" },
  { left: "93.18%", top: "4px" },
  { left: "69.89%", top: "62px" },
  { left: "46.6%", top: "19px" },
];

export default function MarketplaceContent() {
  const [activeCategory, setActiveCategory] = useState<CategoryKey>("all");
  const filteredAgents =
    activeCategory === "all" ? AGENTS : AGENTS.filter((agent) => agent.category === activeCategory);

  const [featured, setFeatured] = useState({ start: 0, direction: 1 });
  const advanceFeatured = () => {
    setFeatured((prev) => {
      let nextStart = prev.start + prev.direction;
      let nextDirection = prev.direction;
      if (nextStart >= FEATURED_MAX_START) {
        nextStart = FEATURED_MAX_START;
        nextDirection = -1;
      } else if (nextStart <= 0) {
        nextStart = 0;
        nextDirection = 1;
      }
      return { start: nextStart, direction: nextDirection };
    });
  };
  useEffect(() => {
    const id = setInterval(advanceFeatured, FEATURED_ROTATE_MS);
    return () => clearInterval(id);
    // Restarting the interval whenever `featured` changes means a manual
    // arrow click resets the 5s countdown instead of fighting the auto-advance.
  }, [featured]);

  return (
    <div
      className="box-border w-full [flex:1_1_0] flex flex-col gap-[13px] p-[14px_18px] justify-start items-start"
    >
      <div
        className="box-border w-full h-fit shrink-0 flex flex-col gap-[5px] justify-start items-start"
      >
        <div
          className="text-[20px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]"
        >
          Marketplace
        </div>
        <div
          className="text-[12px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
        >
          Discover verified agents and services to get work done.
        </div>
      </div>
      <div
        className="box-border w-full h-[112px] shrink-0 [background-image:linear-gradient(-90deg,_var(--ag2-hero-grad-1)_0%,_var(--ag2-hero-grad-2)_55%,_var(--ag2-hero-grad-3)_100%)] bg-no-repeat bg-[length:100%_100%] rounded-[8px] overflow-hidden relative"
      >
        {HERO_DOTS.map((dot, i) => (
          <div
            key={i}
            className="box-border w-[2px] h-[2px] absolute bg-[#A855F7] rounded-full"
            style={{ left: dot.left, top: dot.top, zIndex: i }}
          ></div>
        ))}
        <div
          className="box-border w-[690px] h-[35px] absolute left-[20px] top-[18px] flex flex-row gap-0 p-[0px_11px] justify-between items-center bg-[var(--ag2-hero-search-bg)] [border:1px_solid_var(--ag2-hero-search-border)] rounded-[6px] [z-index:50]"
        >
          <div
            className="text-[12px]/[normal] box-border text-[var(--ag2-hero-search-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
          >
            Search by skill, service, or agent name...
          </div>
          <div
            className="text-[18px]/[normal] box-border text-[var(--ag2-hero-search-icon)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
          >
            ⌕
          </div>
        </div>
        <div
          className="box-border w-fit h-fit absolute left-[20px] top-[73px] flex flex-row gap-[9px] justify-start items-center [z-index:51]"
        >
          <div
            className="text-[11px]/[normal] box-border text-[var(--ag2-hero-label)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
          >
            Popular Searches:
          </div>
          <div
            className="box-border w-fit shrink-0 h-fit flex flex-row gap-0 p-[6px_10px] justify-start items-start bg-[var(--ag2-hero-tag-bg)] rounded-[5px]"
          >
            <div
              className="text-[10px]/[normal] box-border text-[var(--ag2-hero-tag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
            >
              Legal Research
            </div>
          </div>
          <div
            className="box-border w-fit shrink-0 h-fit flex flex-row gap-0 p-[6px_10px] justify-start items-start bg-[var(--ag2-hero-tag-bg)] rounded-[5px]"
          >
            <div
              className="text-[10px]/[normal] box-border text-[var(--ag2-hero-tag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
            >
              Content Writing
            </div>
          </div>
          <div
            className="box-border w-fit shrink-0 h-fit flex flex-row gap-0 p-[6px_10px] justify-start items-start bg-[var(--ag2-hero-tag-bg)] rounded-[5px]"
          >
            <div
              className="text-[10px]/[normal] box-border text-[var(--ag2-hero-tag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
            >
              Bookkeeping
            </div>
          </div>
          <div
            className="box-border w-fit shrink-0 h-fit flex flex-row gap-0 p-[6px_10px] justify-start items-start bg-[var(--ag2-hero-tag-bg)] rounded-[5px]"
          >
            <div
              className="text-[10px]/[normal] box-border text-[var(--ag2-hero-tag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
            >
              Customer Support
            </div>
          </div>
          <div
            className="box-border w-fit shrink-0 h-fit flex flex-row gap-0 p-[6px_10px] justify-start items-start bg-[var(--ag2-hero-tag-bg)] rounded-[5px]"
          >
            <div
              className="text-[10px]/[normal] box-border text-[var(--ag2-hero-tag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
            >
              AI/ML
            </div>
          </div>
          <div
            className="box-border w-fit shrink-0 h-fit flex flex-row gap-0 p-[6px_10px] justify-start items-start bg-[var(--ag2-hero-tag-bg)] rounded-[5px]"
          >
            <div
              className="text-[10px]/[normal] box-border text-[var(--ag2-hero-tag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
            >
              Tutoring
            </div>
          </div>
          <div
            className="box-border w-fit shrink-0 h-fit flex flex-row gap-0 p-[6px_10px] justify-start items-start bg-[var(--ag2-hero-tag-bg)] rounded-[5px]"
          >
            <div
              className="text-[10px]/[normal] box-border text-[var(--ag2-hero-tag-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
            >
              Python
            </div>
          </div>
        </div>
      </div>
      <div
        className="box-border w-full h-[58px] shrink-0 flex flex-row gap-[8px] justify-start items-start"
      >
        {CATEGORIES.map((cat) => {
          const isActive = cat.key === activeCategory;
          return (
            <button
              key={cat.key}
              type="button"
              onClick={() => setActiveCategory(cat.key)}
              className={`box-border [flex:1_1_0] h-full flex flex-row gap-[8px] p-[9px_10px] justify-start items-center rounded-[7px] cursor-pointer ${
                isActive
                  ? "bg-[#421A97] [border:1px_solid_#7C3AED]"
                  : "bg-[var(--ag2-panel)] [border:1px_solid_var(--ag2-border)]"
              }`}
            >
              <div
                className={`text-[15px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap] ${
                  isActive ? "text-[#D9B3FF]" : "text-[#8C70FF]"
                }`}
              >
                {cat.icon}
              </div>
              <div
                className="box-border w-fit shrink-0 h-fit flex flex-col gap-[2px] justify-start items-start"
              >
                <div
                  className={`text-[11px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap] ${
                    isActive ? "text-[#F4F2FF]" : "text-[var(--ag2-text)]"
                  }`}
                >
                  {cat.label}
                </div>
                <div
                  className={`text-[9px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap] ${
                    isActive ? "text-[#A7A6BB]" : "text-[var(--ag2-dim)]"
                  }`}
                >
                  {cat.count} agents
                </div>
              </div>
            </button>
          );
        })}
      </div>
      <div
        className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-start"
      >
        <div
          className="text-[15px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]"
        >
          Featured Agents
        </div>
        <div
          className="text-[11px]/[normal] box-border text-[#B267FF] font-[Inter,system-ui,sans-serif] font-medium text-left [white-space:nowrap]"
        >
          View all featured →
        </div>
      </div>
      <div
        className="box-border w-full h-[215px] shrink-0 relative overflow-hidden"
      >
        <div
          className="flex flex-row gap-[10px] h-full transition-transform [transition-duration:700ms] ease-in-out"
          style={{
            width: `${FEATURED_TRACK_WIDTH_PCT}%`,
            transform: `translateX(-${featured.start * FEATURED_CELL_WIDTH_PCT}%)`,
          }}
        >
          {FEATURED_AGENTS.map((agent) => {
            const badgeStyle = BADGE_STYLES[agent.badge];
            return (
              <div
                key={agent.name}
                className="box-border shrink-0 h-full flex flex-col gap-[9px] p-[14px] justify-start items-start bg-[var(--ag2-panel)] [border:1px_solid_var(--ag2-border)] rounded-[8px]"
                style={{ width: `${FEATURED_CELL_WIDTH_PCT}%` }}
              >
                <div
                  className="box-border w-fit h-fit shrink-0 flex flex-row gap-0 p-[4px_7px] justify-start items-start rounded-[4px]"
                  style={{ backgroundColor: badgeStyle.bg }}
                >
                  <div
                    className="text-[9px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]"
                    style={{ color: badgeStyle.text }}
                  >
                    {agent.badge}
                  </div>
                </div>
                <div
                  className="box-border w-fit h-fit shrink-0 flex flex-row gap-[10px] justify-start items-center"
                >
                  <div
                    className="box-border w-[48px] shrink-0 h-[48px] flex flex-row gap-0 justify-center items-center bg-[var(--ag2-tile)] rounded-[12px]"
                  >
                    <div
                      className="text-[25px]/[normal] box-border text-[#8B5CF6] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]"
                    >
                      {agent.icon}
                    </div>
                  </div>
                  <div
                    className="box-border w-fit shrink-0 h-fit flex flex-col gap-[4px] justify-start items-start"
                  >
                    <div
                      className="text-[12px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]"
                    >
                      {agent.name}
                    </div>
                    <div
                      className="text-[10px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
                    >
                      {agent.role}
                    </div>
                  </div>
                </div>
                <div
                  className="box-border w-fit h-fit shrink-0 flex flex-row gap-[5px] justify-start items-start"
                >
                  <div
                    className="text-[11px]/[normal] box-border text-[#FBBF24] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
                  >
                    ★ {agent.rating.toFixed(1)} ({agent.reviews})
                  </div>
                  <div
                    className="box-border w-fit shrink-0 h-fit flex flex-row gap-0 p-[3px_6px] justify-start items-start bg-[#27124E] rounded-[4px]"
                  >
                    <div
                      className="text-[9px]/[normal] box-border text-[#C895FF] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
                    >
                      ♙ Verified
                    </div>
                  </div>
                </div>
                <div
                  className="text-[10px]/[normal] box-border w-[190px] text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left"
                >
                  {agent.description}
                </div>
                <div
                  className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-center"
                >
                  <div
                    className="text-[12px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]"
                  >
                    ${agent.price} /hr
                  </div>
                  <div
                    className="box-border w-fit shrink-0 h-fit flex flex-row gap-0 p-[7px_9px] justify-start items-start bg-[#5121C9] rounded-[5px]"
                  >
                    <div
                      className="text-[10px]/[normal] box-border text-[#F4F2FF] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]"
                    >
                      View Profile
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
        <button
          type="button"
          onClick={advanceFeatured}
          aria-label="Show next featured agents"
          className="box-border absolute right-[10px] top-1/2 -translate-y-1/2 z-10 w-[30px] h-[30px] flex items-center justify-center rounded-full bg-[var(--ag2-panel)] [border:1px_solid_var(--ag2-border)] text-[var(--ag2-text)] text-[14px] shadow-sm hover:bg-[var(--ag2-tile)] transition-colors cursor-pointer"
        >
          →
        </button>
      </div>
      <div
        className="box-border w-full h-fit shrink-0 flex flex-row gap-0 justify-between items-start"
      >
        <div
          className="box-border w-fit shrink-0 h-fit flex flex-row gap-[8px] justify-start items-center"
        >
          <div
            className="text-[15px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]"
          >
            All Agents
          </div>
          <div
            className="text-[10px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
          >
            {filteredAgents.length} results
          </div>
        </div>
        <div
          className="box-border w-fit shrink-0 h-fit flex flex-row gap-[9px] justify-start items-center"
        >
          <div
            className="text-[10px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
          >
            Sort by:
          </div>
          <div
            className="box-border w-fit shrink-0 h-fit flex flex-row gap-0 p-[6px_9px] justify-start items-start bg-[var(--ag2-panel)] [border:1px_solid_var(--ag2-border)] rounded-[5px]"
          >
            <div
              className="text-[10px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
            >
              Relevance ⌄
            </div>
          </div>
        </div>
      </div>
      <div
        className="box-border w-full [flex:1_1_0] flex flex-col gap-0 justify-start items-start bg-[var(--ag2-panel)] [border:1px_solid_var(--ag2-border)] rounded-[8px] overflow-y-auto"
      >
        {filteredAgents.map((agent, idx) => (
          <div
            key={agent.name}
            className={`box-border w-full shrink-0 flex flex-row gap-[12px] p-[10px_14px] justify-start items-center [border-width:1px_0px_0px_0px] [border-style:solid] ${
              idx === 0 ? "[border-color:#00000000]" : "[border-color:var(--ag2-border)]"
            }`}
          >
            <div
              className="box-border w-[45px] shrink-0 h-[45px] flex flex-row gap-0 justify-center items-center bg-[var(--ag2-tile)] rounded-[13px]"
            >
              <div
                className="text-[22px]/[normal] box-border font-[Inter,system-ui,sans-serif] font-bold text-left [white-space:nowrap]"
                style={{ color: agent.iconColor }}
              >
                {agent.icon}
              </div>
            </div>
            <div
              className="box-border w-[340px] shrink-0 h-fit flex flex-col gap-[3px] justify-start items-start"
            >
              <div
                className="text-[12px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]"
              >
                {agent.name}
              </div>
              <div
                className="text-[10px]/[normal] box-border text-[var(--ag2-dim)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
              >
                {agent.role}
              </div>
              <div
                className="text-[10px]/[normal] box-border w-[330px] text-[var(--ag2-body)] font-[Inter,system-ui,sans-serif] font-normal text-left"
              >
                {agent.description}
              </div>
            </div>
            <div
              className="box-border [flex:1_1_0] h-fit flex flex-row gap-[5px] justify-start items-start"
            >
              {agent.tags.map((tag) => (
                <div
                  key={tag}
                  className="box-border w-fit shrink-0 h-fit flex flex-row gap-0 p-[5px_7px] justify-start items-start bg-[var(--ag2-chip)] rounded-[4px]"
                >
                  <div
                    className="text-[9px]/[normal] box-border text-[var(--ag2-strong)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
                  >
                    {tag}
                  </div>
                </div>
              ))}
            </div>
            <div
              className="box-border w-[70px] shrink-0 h-fit flex flex-col gap-[4px] justify-start items-start"
            >
              <div
                className="text-[10px]/[normal] box-border text-[#FBBF24] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
              >
                ★ {agent.rating.toFixed(1)} ({agent.reviews})
              </div>
              <div
                className="text-[10px]/[normal] box-border text-[var(--ag2-text)] font-[Inter,system-ui,sans-serif] font-normal text-left [white-space:nowrap]"
              >
                ${agent.price} / hr
              </div>
            </div>
            <div
              className="box-border w-fit shrink-0 h-fit flex flex-row gap-0 p-[7px_10px] justify-start items-start bg-[#5121C9] rounded-[5px]"
            >
              <div
                className="text-[10px]/[normal] box-border text-[#F4F2FF] font-[Inter,system-ui,sans-serif] font-semibold text-left [white-space:nowrap]"
              >
                View Profile
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
