create schema if not exists compliance;
create table compliance.jurisdiction_rules (
    rule_id text not null,
    tenant_id text not null,
    jurisdiction text not null,
    channel text not null,
    purpose text not null,
    priority integer not null default 0,
    contact_hour_start smallint not null check(contact_hour_start between 0 and 23),
    contact_hour_end smallint not null check(contact_hour_end between 1 and 24),
    registry_max_age_seconds integer,
    disclosure_mode text,
    enabled boolean not null default false,
    verified_at timestamptz,
    verified_by_principal_id text,
    source_uri text,
    effective_from timestamptz,
    effective_until timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key(rule_id, tenant_id),
    check(not enabled or (verified_at is not null and source_uri is not null)),
    check(effective_until is null or effective_until > effective_from)
);
alter table compliance.jurisdiction_rules enable row level security;
alter table compliance.jurisdiction_rules force row level security;
create policy jurisdiction_rules_tenant on compliance.jurisdiction_rules
    using(tenant_id=current_setting('app.current_org_id', true))
    with check(tenant_id=current_setting('app.current_org_id', true));
grant usage on schema compliance to agenttrust_app;
grant select,insert,update on compliance.jurisdiction_rules to agenttrust_app;
