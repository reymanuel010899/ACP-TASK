-- migrations/0002_catalog.sql (unit U2)
--
-- Capability catalog: one real home for the capability_id string repeated
-- across today's five different in-memory stores. Verbatim from
-- docs/architecture/database-design.md Section 4. Depends on identity only
-- insofar as it must run after 0001 (KTD7's flat sequential numbering
-- encodes the dependency order) -- no direct FK back into identity here.

create schema catalog;

create table catalog.capabilities (
    capability_id  text primary key,
    version        text not null,
    description    text not null,
    input_schema   jsonb,
    output_schema  jsonb,
    extensions     jsonb not null default '{}',
    created_at     timestamptz not null default now()
);
