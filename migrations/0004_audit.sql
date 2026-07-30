-- migrations/0004_audit.sql (unit U4)
--
-- Central Audit & Compliance trail: one durable, partitioned, append-only
-- table replacing both audit/audit_store.py's in-memory List[dict] and the
-- Vault's separate local audit_log.py (KTD3, R5). Verbatim from
-- docs/architecture/database-design.md Section 9, adjusted only to hardcode
-- the current + next month's partitions (a static migration file can't call
-- now()) -- audit/repository.py's insert path defensively creates whatever
-- partition a given write actually needs, so this file's partitions going
-- stale never blocks a write (see that module's _ensure_partition).
--
-- Append-only is enforced at the DATABASE level, not just the HTTP layer's
-- 405: UPDATE/DELETE are revoked from PUBLIC and a no-op rule additionally
-- absorbs any UPDATE/DELETE statement that somehow reaches the table (e.g.
-- issued by a role that still has the privilege, such as the table owner).
--
-- organization_id is included per the design doc, ahead of RLS actually
-- being enforced here -- that's U9's job (see this unit's report for the
-- open question it leaves for U9: unlike vault, audit_log declares the
-- column already, so U9 only has to add the policy, not a schema change).

create schema audit;

create table audit.audit_log (
    entry_id         text not null,
    created_at       timestamptz not null default now(),
    principal_id     text not null,
    activity_type    text not null,
    status           text not null,
    resource_type    text,
    resource_id      text,
    organization_id  text,
    details          jsonb not null default '{}',
    prev_hash        text,
    entry_hash       text,
    primary key (entry_id, created_at)
) partition by range (created_at);

-- At least the current month's partition, plus one ahead of it, so a
-- fresh migration run never has to race audit/repository.py's own
-- self-healing partition creation on the very first write.
create table audit.audit_log_2026_07 partition of audit.audit_log
    for values from ('2026-07-01') to ('2026-08-01');
create table audit.audit_log_2026_08 partition of audit.audit_log
    for values from ('2026-08-01') to ('2026-09-01');

create index audit_log_principal_idx on audit.audit_log (principal_id, created_at desc);
create index audit_log_activity_type_idx on audit.audit_log (activity_type, created_at desc);
create index audit_log_resource_idx on audit.audit_log (resource_type, resource_id, created_at desc);

create table audit.activity_types (
    activity_type text primary key,
    description    text not null
);
insert into audit.activity_types (activity_type, description) values
    ('credential.access', 'A credential grant was used to decrypt/use a secret'),
    ('credential.grant', 'A user granted an agent access to a credential'),
    ('credential.revoke', 'A credential grant was revoked'),
    ('keyring.rotate', 'A user rotated their keyring'),
    ('principal.register', 'A new principal was registered'),
    ('agent.register', 'A new agent was registered'),
    ('reputation.update', 'A reputation record changed'),
    ('permission.check', 'An authorization check was evaluated'),
    ('work.bid', 'An agent bid on a task'),
    ('work.submit', 'Work was submitted for a task'),
    ('work.complete', 'A task was marked complete'),
    ('agent.hire', 'A hiring grant was created'),
    ('agent.rate', 'A rating was submitted'),
    ('agent.revoke', 'A hiring grant was revoked'),
    ('app.register', 'An app registered with the federation'),
    ('service.register', 'A service endpoint was registered');

revoke update, delete on audit.audit_log from public;
create rule audit_log_no_delete as on delete to audit.audit_log do instead nothing;
create rule audit_log_no_update as on update to audit.audit_log do instead nothing;
