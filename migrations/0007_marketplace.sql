-- migrations/0007_marketplace.sql (unit U6)
--
-- Marketplace: tasks, competitive-negotiation Offers/CounterOffers (RFC-0002,
-- schemas/offer.schema.json / schemas/counter-offer.schema.json), bids,
-- negotiation messages, and work-result delivery history. Verbatim from
-- docs/architecture/database-design.md Section 7, with two narrow,
-- explicitly-documented additions -- both required to satisfy R10 (preserve
-- apps/marketplace/server/app.py's PRE-EXISTING external HTTP contract)
-- against a schema that has no slot for either field:
--
--   1. No new column on marketplace.tasks. The pre-existing
--      `POST /api/negotiations/{task_id}/complete` free-text "outcome" is
--      persisted as a `marketplace.work_results` row instead (submitted_by =
--      the completing author, evidence_id = NULL) -- see
--      apps/marketplace/server/repository.py's module docstring for the
--      full reasoning.
--
--   2. marketplace.work_results gains one column NOT in the design doc:
--      `evidence jsonb not null default '{}'`. The pre-existing P2P
--      `submit.work_result` contract accepts an arbitrary, opaque JSON
--      `evidence` blob (e.g. `{"word_count": 4200}`) that is NOT a reference
--      into `trust.evidence` -- `evidence_id` (the design doc's column, kept
--      exactly as specified) stays a nullable FK into `trust.evidence` and
--      is left NULL per this unit's wrinkle #3 (no fake evidence rows); the
--      opaque blob needs its own column to round-trip through R10
--      unmodified. `work_results_task_idx` (task_id, submitted_at desc) is
--      likewise an addition, not in the design doc, added purely to make
--      "the latest row per task" (R10's single-object work_result view)
--      an indexed lookup rather than a sequential scan (R7's spirit).

create schema marketplace;

create type marketplace.task_status as enum ('open', 'accepted', 'delivered', 'completed', 'cancelled');
create type marketplace.bid_status as enum ('pending', 'accepted', 'rejected');

create table marketplace.tasks (
    task_id             text primary key,
    organization_id     text references identity.organizations(organization_id),
    author_principal_id text not null references identity.principals(principal_id),
    worker_principal_id text references identity.principals(principal_id),
    capability_id       text references catalog.capabilities(capability_id),
    description         text not null,
    status              marketplace.task_status not null default 'open',
    created_at            timestamptz not null default now(),
    updated_at            timestamptz not null default now()
);
create index tasks_org_idx on marketplace.tasks(organization_id);
create index tasks_status_idx on marketplace.tasks(status) where status in ('open', 'accepted');
create index tasks_capability_idx on marketplace.tasks(capability_id);

create table marketplace.offers (
    offer_id                text primary key,
    task_id                  text not null references marketplace.tasks(task_id) on delete cascade,
    provider_principal_id    text not null references identity.principals(principal_id),
    price                    numeric(12,2) not null check (price >= 0),
    currency                 char(3) not null default 'USD',
    delivery                 text,
    terms                    jsonb not null default '{}',
    created_at                timestamptz not null default now()
);

create table marketplace.counter_offers (
    counter_id      text primary key,
    task_id          text not null references marketplace.tasks(task_id) on delete cascade,
    proposed_price   numeric(12,2) not null check (proposed_price >= 0),
    currency         char(3) not null default 'USD',
    created_at        timestamptz not null default now()
);

create table marketplace.bids (
    bid_id                  text primary key,
    task_id                  text not null references marketplace.tasks(task_id) on delete cascade,
    agent_principal_id       text not null references identity.principals(principal_id),
    proposed_terms           text not null,
    agent_reputation_note    text,
    status                   marketplace.bid_status not null default 'pending',
    created_at                timestamptz not null default now()
);
create index bids_task_idx on marketplace.bids(task_id);

create table marketplace.negotiation_messages (
    message_id         bigserial primary key,
    task_id             text not null references marketplace.tasks(task_id) on delete cascade,
    from_principal_id   text not null references identity.principals(principal_id),
    message             text not null,
    created_at            timestamptz not null default now()
);
create index negotiation_task_idx on marketplace.negotiation_messages(task_id, created_at);

create table marketplace.work_results (
    work_result_id   text primary key,
    task_id           text not null references marketplace.tasks(task_id) on delete cascade,
    result_summary    text not null,
    evidence          jsonb not null default '{}',
    evidence_id       text references trust.evidence(evidence_id),
    submitted_by      text not null references identity.principals(principal_id),
    submitted_at       timestamptz not null default now()
);
create index work_results_task_idx on marketplace.work_results(task_id, submitted_at desc);
