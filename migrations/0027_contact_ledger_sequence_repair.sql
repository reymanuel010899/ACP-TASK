-- Repair databases that applied the first version of 0018 before its contact
-- ledgers gained a deterministic insertion-order tiebreaker. Migration files
-- are immutable once recorded, so the correction belongs in a new migration.

alter table contacts.consent_records
    add column if not exists ledger_sequence
    bigint generated always as identity;
alter table contacts.address_suppressions
    add column if not exists ledger_sequence
    bigint generated always as identity;
alter table contacts.address_usability_decisions
    add column if not exists ledger_sequence
    bigint generated always as identity;
alter table contacts.provider_reachability_events
    add column if not exists ledger_sequence
    bigint generated always as identity;

-- The repositories order by recorded_at and ledger_sequence. Rebuild the
-- supporting indexes so that tie resolution remains index-backed.
drop index if exists contacts.consent_records_current;
create index consent_records_current
    on contacts.consent_records(
        tenant_id, address_id, channel, purpose,
        recorded_at desc, ledger_sequence desc
    );

drop index if exists contacts.address_suppressions_current;
create index address_suppressions_current
    on contacts.address_suppressions(
        tenant_id, address_id, channel,
        recorded_at desc, ledger_sequence desc
    );

drop index if exists contacts.address_usability_current;
create index address_usability_current
    on contacts.address_usability_decisions(
        tenant_id, address_id,
        recorded_at desc, ledger_sequence desc
    );

drop index if exists contacts.provider_reachability_current;
create index provider_reachability_current
    on contacts.provider_reachability_events(
        tenant_id, address_id, channel,
        recorded_at desc, ledger_sequence desc
    );
