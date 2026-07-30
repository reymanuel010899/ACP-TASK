-- migrations/0006_trust.sql (unit U5)
--
-- Trust: evidence, verification results, and the ONE canonical reputation
-- table shared by Registry and Verification Service (R2). Verbatim from
-- docs/architecture/database-design.md Section 6.
--
-- This unit wires trust.reputation_records and trust.reputation_portfolio
-- fully into Postgres (libs/reputation_repository.py) -- the canonical
-- consolidation this unit exists for. trust.evidence and
-- trust.verification_results are created here per the design doc's schema
-- (trust.reputation_portfolio.evidence_id is a real, enforced foreign key
-- into trust.evidence, so the table must exist), but this unit deliberately
-- does NOT wire the full Evidence/VerificationResult submission pipeline
-- into them -- see libs/reputation_repository.py's docstring for why, and
-- U5's final report for the explicit scope call-out.

create schema trust;

create type trust.verdict as enum ('verified', 'rejected');

create table trust.evidence (
    evidence_id             text primary key,
    session_id              text not null,           -- session assertions stay stateless (RFC-0001) -- this is a reference string, not a FK to a stored session row
    capability_id           text not null references catalog.capabilities(capability_id),
    submitter_principal_id  text references identity.principals(principal_id),
    schema_valid            boolean not null,
    tests_passed            boolean not null,
    artifact_hashes         jsonb not null default '{}',
    created_at              timestamptz not null default now()
);

create table trust.verification_results (
    result_id              text primary key,
    evidence_id            text not null unique references trust.evidence(evidence_id),
    verifier_principal_id  text not null references identity.principals(principal_id),
    verdict                trust.verdict not null,
    reasoning               text not null,
    verified_at              timestamptz not null default now()
);

-- Canonical reputation. verification_rate is derived, never stored-then-drifted.
create table trust.reputation_records (
    principal_id       text not null references identity.principals(principal_id),
    capability_id      text not null references catalog.capabilities(capability_id),
    tasks_verified     integer not null default 0,
    tasks_rejected     integer not null default 0,
    verification_rate  numeric generated always as (
        case when tasks_verified + tasks_rejected = 0 then null
             else round(tasks_verified::numeric / (tasks_verified + tasks_rejected), 4)
        end
    ) stored,                                    -- null = neutral, never 0.0 (RFC-0001 rule, preserved)
    updated_at         timestamptz not null default now(),
    primary key (principal_id, capability_id)
);

-- Append-only portfolio ledger: "only verified work is ever appended" (existing
-- code comment/invariant) -- enforced here at the DB level, not just by convention.
create table trust.reputation_portfolio (
    seq                    bigserial primary key,      -- replaces the hand-rolled _seq tie-breaker
    subject_principal_id   text not null references identity.principals(principal_id),
    capability_id          text not null references catalog.capabilities(capability_id),
    evidence_id            text not null unique references trust.evidence(evidence_id),
    verdict                trust.verdict not null default 'verified' check (verdict = 'verified'),
    verified_at            timestamptz not null default now()
);
create index portfolio_subject_idx on trust.reputation_portfolio(subject_principal_id, capability_id, seq desc);

revoke update, delete on trust.reputation_portfolio from public;
create rule reputation_portfolio_no_delete as on delete to trust.reputation_portfolio do instead nothing;
create rule reputation_portfolio_no_update as on update to trust.reputation_portfolio do instead nothing;
