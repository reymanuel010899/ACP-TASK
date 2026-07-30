-- migrations/0008_hiring.sql (unit U8)
--
-- Agent Marketplace hiring grants + ratings, verbatim from
-- docs/architecture/database-design.md Section 7 -- the same `marketplace`
-- schema U6/U7 already created (marketplace.tasks/offers/counter_offers/
-- bids/negotiation_messages/work_results), consolidating
-- agent_marketplace/hiring.py's in-memory dicts alongside those tables (R3).
--
-- Two behavior changes this file exists to enable (see
-- agent_marketplace/repository.py for the full reasoning):
--
--   1. `status = 'expired'` is a QUERY PREDICATE
--      (`status = 'active' and (expires_at is null or expires_at > now())`),
--      never a value the application writes -- closing the gap in today's
--      HiringStore._view(), which only ever wrote 'revoked' on an explicit
--      revoke and computed "expired" lazily, in Python, on every read.
--
--   2. Ratings become append-only history (KTD8): re-rating the same
--      (agent, user) pair INSERTS a new `marketplace.ratings` row rather
--      than replacing the previous one -- a deliberate change from today's
--      HiringStore.set_rating, which overwrote the prior rating in place
--      and discarded it. `marketplace.rating_summary` is kept current via
--      an AFTER INSERT trigger (below) that performs an O(1) incremental
--      running-average update rather than a full re-scan of every rating
--      on every read.
--
-- `grant_credential_scopes.credential_id` is a cross-schema LOGICAL FK into
-- `vault.credentials` (U3) -- per the design doc (Section 8's closing note),
-- this is the one place accepted without a hard Postgres FK constraint,
-- since marketplace and vault may become physically separate databases
-- later (Section 1). It is intentionally NOT enforced here; the existing
-- application-layer check already lives in agent_marketplace/app.py, which
-- orchestrates a REAL Vault grant (`VaultClient.grant_access`, an HTTP call
-- that 404s on an unknown credential_id) before ever calling
-- HiringRepository.create_grant -- see that repository's module docstring.
--
-- `grant_id` keeps the pre-existing `uuid.uuid4()` string format
-- HiringStore.create_grant already minted (no design-doc comment overrides
-- it to a ULID, unlike e.g. migrations/0007_marketplace.sql's `task_id) --
-- mirroring the identical precedent already established for
-- apps/marketplace/server/repository.py's `bid_id` and
-- vault/repository.py's `credential_id` (KTD4: only NEW surrogate keys are
-- ULIDs; a pre-existing app-generated format callers might depend on is
-- left alone absent a stated reason to change it).

create type marketplace.grant_status as enum ('active', 'revoked', 'expired');

create table marketplace.hiring_grants (
    grant_id              text primary key,
    agent_principal_id    text not null references identity.principals(principal_id),
    user_principal_id     text not null references identity.principals(principal_id),
    expires_at            timestamptz,
    status                marketplace.grant_status not null default 'active',
    created_at              timestamptz not null default now(),
    revoked_at              timestamptz
);
-- expired-ness is a query predicate, not a background job or a lazily
-- written value:
--   status = 'active' and (expires_at is null or expires_at > now())

create table marketplace.grant_capabilities (
    grant_id       text not null references marketplace.hiring_grants(grant_id) on delete cascade,
    capability_id  text not null references catalog.capabilities(capability_id),
    primary key (grant_id, capability_id)
);

create table marketplace.grant_credential_scopes (
    grant_id       text not null references marketplace.hiring_grants(grant_id) on delete cascade,
    credential_id  text not null,
    scope          text not null,
    primary key (grant_id, credential_id)
);

create table marketplace.ratings (
    rating_id             bigserial primary key,
    agent_principal_id    text not null references identity.principals(principal_id),
    user_principal_id     text not null references identity.principals(principal_id),
    rating                 smallint not null check (rating between 1 and 5),
    review_text             text,
    created_at                timestamptz not null default now()
);
create index ratings_agent_idx on marketplace.ratings(agent_principal_id, created_at desc);

create table marketplace.rating_summary (
    agent_principal_id  text primary key references identity.principals(principal_id),
    avg_rating           numeric(3,2) not null default 0,
    review_count          integer not null default 0,
    updated_at              timestamptz not null default now()
);

-- Refreshes marketplace.rating_summary after every marketplace.ratings
-- insert with an O(1) incremental running-average update (KTD8): BOTH the
-- brand-new rating and every prior one for this agent count toward the
-- average forever -- re-rating is additive history, never a replacement.
create or replace function marketplace.update_rating_summary() returns trigger as $$
begin
    insert into marketplace.rating_summary as rs
        (agent_principal_id, avg_rating, review_count, updated_at)
    values (new.agent_principal_id, new.rating, 1, now())
    on conflict (agent_principal_id) do update
        set avg_rating = round(
                ((rs.avg_rating * rs.review_count) + new.rating)
                / (rs.review_count + 1),
                2
            ),
            review_count = rs.review_count + 1,
            updated_at = now();
    return new;
end;
$$ language plpgsql;

create trigger ratings_after_insert
    after insert on marketplace.ratings
    for each row execute function marketplace.update_rating_summary();
