/**
 * Capability catalog — the mock "database" of agent capabilities the Create
 * Agent wizard offers. Each entry has a dot-namespaced `id` (the value stored
 * on the agent card's `skills[].id`, mirroring schemas/capability.schema.json)
 * and a human-friendly `label` shown in the UI. Grouped by `category` so the
 * picker can render <optgroup>s. Inline mock data, consistent with the rest of
 * the app; a real registry-backed catalog is deferred.
 */

export type Capability = { id: string; label: string; category: string };

type Group = { category: string; items: [id: string, label: string][] };

const GROUPS: Group[] = [
  {
    category: "Cloud & DevOps",
    items: [
      ["terraform.generate", "Terraform Engineer"],
      ["kubernetes.manage", "Kubernetes Engineer"],
      ["aws.architect", "AWS Cloud Architect"],
      ["gcp.architect", "GCP Cloud Architect"],
      ["azure.architect", "Azure Cloud Architect"],
      ["cicd.pipeline", "CI/CD Engineer"],
      ["docker.containerize", "Docker / Container Engineer"],
      ["ansible.automate", "Ansible Automation Engineer"],
      ["observability.monitoring", "Observability Engineer"],
      ["sre.reliability", "Site Reliability Engineer"],
      ["linux.administration", "Linux Systems Administrator"],
      ["networking.configure", "Network Engineer"],
      ["helm.packaging", "Helm / K8s Packaging Engineer"],
      ["serverless.deploy", "Serverless Engineer"],
    ],
  },
  {
    category: "Software Engineering",
    items: [
      ["backend.api", "Backend API Engineer"],
      ["frontend.web", "Frontend Web Engineer"],
      ["fullstack.web", "Full-Stack Engineer"],
      ["mobile.ios", "iOS Engineer"],
      ["mobile.android", "Android Engineer"],
      ["mobile.crossplatform", "Cross-Platform Mobile Engineer"],
      ["game.development", "Game Developer"],
      ["embedded.firmware", "Embedded / Firmware Engineer"],
      ["desktop.apps", "Desktop App Engineer"],
      ["graphql.api", "GraphQL Engineer"],
      ["microservices.design", "Microservices Architect"],
      ["code.review", "Code Reviewer"],
      ["refactoring.legacy", "Legacy Refactoring Specialist"],
      ["performance.optimization", "Performance Engineer"],
    ],
  },
  {
    category: "Data & AI",
    items: [
      ["data.analysis", "Data Analyst"],
      ["data.engineering", "Data Engineer"],
      ["data.science", "Data Scientist"],
      ["ml.engineering", "Machine Learning Engineer"],
      ["ml.ops", "MLOps Engineer"],
      ["ai.prompt", "Prompt Engineer"],
      ["nlp.processing", "NLP Engineer"],
      ["vision.computer", "Computer Vision Engineer"],
      ["bi.dashboards", "BI / Dashboard Analyst"],
      ["etl.pipelines", "ETL Engineer"],
      ["data.visualization", "Data Visualization Specialist"],
      ["statistics.modeling", "Statistical Modeler"],
      ["deep.learning", "Deep Learning Engineer"],
      ["recommendation.systems", "Recommender Systems Engineer"],
    ],
  },
  {
    category: "Security",
    items: [
      ["security.pentest", "Penetration Tester"],
      ["security.appsec", "Application Security Engineer"],
      ["security.cloud", "Cloud Security Engineer"],
      ["security.compliance", "Security Compliance Analyst"],
      ["security.incident", "Incident Response Analyst"],
      ["security.iam", "IAM Engineer"],
      ["security.forensics", "Digital Forensics Analyst"],
      ["security.threat", "Threat Intelligence Analyst"],
      ["cryptography.engineering", "Cryptography Engineer"],
      ["security.audit", "Security Auditor"],
    ],
  },
  {
    category: "Design",
    items: [
      ["design.ui", "UI Designer"],
      ["design.ux", "UX Designer"],
      ["design.product", "Product Designer"],
      ["design.brand", "Brand Designer"],
      ["design.graphic", "Graphic Designer"],
      ["design.motion", "Motion Designer"],
      ["design.illustration", "Illustrator"],
      ["design.threed", "3D Designer"],
      ["design.interaction", "Interaction Designer"],
      ["design.research", "UX Researcher"],
      ["design.systems", "Design Systems Specialist"],
    ],
  },
  {
    category: "Product & Project",
    items: [
      ["product.management", "Product Manager"],
      ["product.strategy", "Product Strategist"],
      ["product.analytics", "Product Analyst"],
      ["project.management", "Project Manager"],
      ["scrum.master", "Scrum Master"],
      ["program.management", "Program Manager"],
      ["roadmap.planning", "Roadmap Planner"],
      ["requirements.analysis", "Business Analyst"],
    ],
  },
  {
    category: "Marketing",
    items: [
      ["marketing.seo", "SEO Specialist"],
      ["marketing.content", "Content Marketer"],
      ["marketing.social", "Social Media Manager"],
      ["marketing.email", "Email Marketing Specialist"],
      ["marketing.ppc", "PPC / Paid Ads Specialist"],
      ["marketing.growth", "Growth Marketer"],
      ["marketing.brand", "Brand Strategist"],
      ["marketing.pr", "PR Specialist"],
      ["marketing.influencer", "Influencer Marketing Manager"],
      ["marketing.analytics", "Marketing Analyst"],
      ["marketing.copywriting", "Marketing Copywriter"],
      ["marketing.events", "Event Marketing Manager"],
    ],
  },
  {
    category: "Sales",
    items: [
      ["sales.development", "Sales Development Rep"],
      ["sales.account", "Account Executive"],
      ["sales.engineering", "Sales Engineer"],
      ["sales.success", "Customer Success Manager"],
      ["sales.operations", "Sales Operations Analyst"],
      ["sales.enablement", "Sales Enablement Specialist"],
      ["sales.partnerships", "Partnerships Manager"],
    ],
  },
  {
    category: "Finance & Accounting",
    items: [
      ["finance.accounting", "Accountant"],
      ["finance.bookkeeping", "Bookkeeper"],
      ["finance.tax", "Tax Specialist"],
      ["finance.audit", "Auditor"],
      ["finance.fpa", "FP&A Analyst"],
      ["finance.payroll", "Payroll Specialist"],
      ["finance.controller", "Financial Controller"],
      ["finance.treasury", "Treasury Analyst"],
      ["finance.investment", "Investment Analyst"],
      ["finance.risk", "Risk Analyst"],
      ["finance.credit", "Credit Analyst"],
      ["finance.forecasting", "Financial Forecaster"],
    ],
  },
  {
    category: "Legal",
    items: [
      ["legal.contracts", "Contract Attorney"],
      ["legal.ip", "IP / Trademark Attorney"],
      ["legal.compliance", "Compliance Officer"],
      ["legal.corporate", "Corporate Counsel"],
      ["legal.litigation", "Litigation Specialist"],
      ["legal.immigration", "Immigration Specialist"],
      ["legal.privacy", "Privacy / Data Protection Counsel"],
      ["legal.employment", "Employment Law Specialist"],
      ["legal.realestate", "Real Estate Attorney"],
      ["legal.research", "Legal Researcher"],
      ["legal.paralegal", "Paralegal"],
    ],
  },
  {
    category: "Healthcare",
    items: [
      ["health.patientcare", "Patient Care Coordinator"],
      ["health.clinical", "Clinical Documentation Specialist"],
      ["health.telehealth", "Telehealth Triage Specialist"],
      ["health.billing", "Medical Billing Specialist"],
      ["health.coding", "Medical Coder"],
      ["health.nursing", "Nursing Assistant"],
      ["health.pharmacy", "Pharmacy Technician"],
      ["health.mentalhealth", "Mental Health Counselor"],
      ["health.nutrition", "Nutritionist"],
      ["health.radiology", "Radiology Analyst"],
      ["health.wellness", "Wellness Coach"],
      ["health.records", "Health Records Manager"],
    ],
  },
  {
    category: "Education",
    items: [
      ["education.tutoring", "Academic Tutor"],
      ["education.curriculum", "Curriculum Designer"],
      ["education.language", "Language Learning Coach"],
      ["education.admissions", "Admissions Advisor"],
      ["education.stem", "STEM Tutor"],
      ["education.special", "Special Education Specialist"],
      ["education.instructional", "Instructional Designer"],
      ["education.assessment", "Assessment Specialist"],
      ["education.earlychildhood", "Early Childhood Educator"],
    ],
  },
  {
    category: "HR & Recruiting",
    items: [
      ["hr.recruiting", "Technical Recruiter"],
      ["hr.talent", "Talent Acquisition Specialist"],
      ["hr.onboarding", "Onboarding Specialist"],
      ["hr.benefits", "Benefits Administrator"],
      ["hr.people", "People Operations Manager"],
      ["hr.compensation", "Compensation Analyst"],
      ["hr.training", "Learning & Development Specialist"],
      ["hr.employee", "Employee Relations Specialist"],
      ["hr.diversity", "DEI Specialist"],
    ],
  },
  {
    category: "Operations & Support",
    items: [
      ["support.customer", "Customer Support Agent"],
      ["support.technical", "Technical Support Engineer"],
      ["support.onboarding", "Customer Onboarding Specialist"],
      ["community.management", "Community Manager"],
      ["qa.testing", "QA Engineer"],
      ["qa.automation", "Test Automation Engineer"],
      ["ops.release", "Release Manager"],
      ["it.support", "IT Support Specialist"],
      ["helpdesk.analyst", "Help Desk Analyst"],
      ["ops.processimprovement", "Process Improvement Analyst"],
    ],
  },
  {
    category: "Writing & Content",
    items: [
      ["content.copywriting", "Copywriter"],
      ["content.technical", "Technical Writer"],
      ["content.editing", "Editor"],
      ["content.blogging", "Blog Writer"],
      ["content.ghostwriting", "Ghostwriter"],
      ["content.scriptwriting", "Scriptwriter"],
      ["content.translation", "Translator"],
      ["content.proofreading", "Proofreader"],
      ["content.grantwriting", "Grant Writer"],
      ["content.uxwriting", "UX Writer"],
    ],
  },
  {
    category: "Research & Science",
    items: [
      ["research.market", "Market Researcher"],
      ["research.scientific", "Research Scientist"],
      ["research.academic", "Academic Researcher"],
      ["research.biotech", "Biotech Researcher"],
      ["research.chemistry", "Chemist"],
      ["research.physics", "Physicist"],
      ["research.environmental", "Environmental Scientist"],
      ["research.clinicaltrials", "Clinical Trials Coordinator"],
      ["research.survey", "Survey Methodologist"],
    ],
  },
  {
    category: "Construction & Trades",
    items: [
      ["construction.project", "Construction Project Manager"],
      ["construction.estimating", "Cost Estimator"],
      ["construction.architecture", "Architect"],
      ["construction.civil", "Civil Engineer"],
      ["construction.electrical", "Electrical Engineer"],
      ["construction.mechanical", "Mechanical Engineer"],
      ["construction.structural", "Structural Engineer"],
      ["construction.hvac", "HVAC Specialist"],
      ["construction.plumbing", "Plumbing Specialist"],
      ["construction.surveying", "Land Surveyor"],
    ],
  },
  {
    category: "Logistics & Supply Chain",
    items: [
      ["logistics.supplychain", "Supply Chain Analyst"],
      ["logistics.procurement", "Procurement Specialist"],
      ["logistics.inventory", "Inventory Manager"],
      ["logistics.warehouse", "Warehouse Operations Manager"],
      ["logistics.transportation", "Transportation Coordinator"],
      ["logistics.fleet", "Fleet Manager"],
      ["logistics.demand", "Demand Planner"],
      ["logistics.customs", "Customs / Trade Compliance Specialist"],
    ],
  },
  {
    category: "Real Estate",
    items: [
      ["realestate.agent", "Real Estate Agent"],
      ["realestate.appraisal", "Property Appraiser"],
      ["realestate.propertymgmt", "Property Manager"],
      ["realestate.mortgage", "Mortgage Advisor"],
      ["realestate.investment", "Real Estate Investment Analyst"],
      ["realestate.leasing", "Leasing Consultant"],
    ],
  },
  {
    category: "Hospitality & Travel",
    items: [
      ["hospitality.event", "Event Planner"],
      ["hospitality.hotel", "Hotel Operations Manager"],
      ["hospitality.restaurant", "Restaurant Manager"],
      ["hospitality.chef", "Chef / Culinary Specialist"],
      ["hospitality.travel", "Travel Agent"],
      ["hospitality.concierge", "Concierge"],
    ],
  },
  {
    category: "Media & Entertainment",
    items: [
      ["media.video", "Video Editor"],
      ["media.audio", "Audio Engineer"],
      ["media.photography", "Photographer"],
      ["media.podcast", "Podcast Producer"],
      ["media.animation", "Animator"],
      ["media.journalism", "Journalist"],
      ["media.socialvideo", "Social Video Creator"],
    ],
  },
  {
    category: "Manufacturing & Engineering",
    items: [
      ["manufacturing.process", "Manufacturing Process Engineer"],
      ["manufacturing.quality", "Quality Control Engineer"],
      ["manufacturing.industrial", "Industrial Engineer"],
      ["manufacturing.robotics", "Robotics Engineer"],
      ["manufacturing.cad", "CAD Designer"],
      ["manufacturing.lean", "Lean Manufacturing Specialist"],
    ],
  },
  {
    category: "Agriculture & Environment",
    items: [
      ["agriculture.agronomy", "Agronomist"],
      ["agriculture.farmmgmt", "Farm Manager"],
      ["agriculture.sustainability", "Sustainability Consultant"],
      ["energy.renewable", "Renewable Energy Analyst"],
      ["climate.analysis", "Climate Analyst"],
    ],
  },
  {
    category: "Government & Public",
    items: [
      ["government.policy", "Policy Analyst"],
      ["government.urban", "Urban Planner"],
      ["government.grants", "Grants Administrator"],
      ["government.administration", "Public Administration Specialist"],
      ["government.social", "Social Worker"],
    ],
  },
];

/** Grouped for rendering <optgroup>s in a picker. */
export const CAPABILITY_GROUPS: { category: string; items: Capability[] }[] = GROUPS.map((g) => ({
  category: g.category,
  items: g.items.map(([id, label]) => ({ id, label, category: g.category })),
}));

/** Flat list of every capability. */
export const CAPABILITIES: Capability[] = CAPABILITY_GROUPS.flatMap((g) => g.items);

/** id -> Capability lookup. */
export const CAPABILITY_BY_ID: Record<string, Capability> = Object.fromEntries(
  CAPABILITIES.map((c) => [c.id, c]),
);
