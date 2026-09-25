-- Time-versioned, globally unique ownership of Twilio communication identities.
create schema if not exists twilio;

create table twilio.identities (
    identity_version_id text not null,
    identity_address text not null,
    tenant_id text not null,
    connection_id text not null,
    provider_identity_sid text not null,
    identity_kind text not null check (identity_kind in ('phone_number', 'whatsapp_sender')),
    possession_verified_at timestamptz not null,
    valid_from timestamptz not null,
    valid_until timestamptz,
    callback_health text not null default 'unknown'
        check (callback_health in ('healthy', 'drifted', 'unknown')),
    created_at timestamptz not null default now(),
    primary key (identity_version_id, tenant_id),
    foreign key (connection_id, tenant_id)
        references integrations.connections(connection_id, tenant_id),
    check (valid_until is null or valid_until > valid_from)
);

create unique index twilio_one_current_identity_owner
    on twilio.identities(identity_address) where valid_until is null;
create index twilio_identity_owner_at_time
    on twilio.identities(identity_address, valid_from, valid_until);

create table twilio.dispatch_ledger (
    tenant_id text not null, dispatch_key text not null, effect_id text not null,
    payload_hash text not null, callback_token_hash text not null,
    status text not null, provider_id text, provider_status text,
    attempt_count integer not null default 0,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key(tenant_id,dispatch_key), unique(tenant_id,effect_id),
    check(status in ('intent_recorded','dispatching','retryable','accepted','ambiguous','rejected'))
);

create table twilio.provider_events (
    tenant_id text not null,event_key text not null,effect_id text,
    provider_id text,identity_address text not null,event_type text not null,
    status text,payload jsonb not null,authenticated boolean not null,
    received_at timestamptz not null default now(),
    primary key(tenant_id,event_key)
);

create table twilio.effect_verdicts (
    tenant_id text not null,effect_id text not null,provider_id text,
    status text not null,rank integer not null,terminal boolean not null,
    updated_at timestamptz not null default now(),
    primary key(tenant_id,effect_id)
);

alter table twilio.identities enable row level security;
alter table twilio.identities force row level security;
alter table twilio.dispatch_ledger enable row level security;
alter table twilio.dispatch_ledger force row level security;
alter table twilio.provider_events enable row level security;
alter table twilio.provider_events force row level security;
alter table twilio.effect_verdicts enable row level security;
alter table twilio.effect_verdicts force row level security;
create policy twilio_identities_tenant on twilio.identities
    using (tenant_id = current_setting('app.current_org_id', true))
    with check (tenant_id = current_setting('app.current_org_id', true));
create policy twilio_dispatch_tenant on twilio.dispatch_ledger using (tenant_id=current_setting('app.current_org_id',true)) with check (tenant_id=current_setting('app.current_org_id',true));
create policy twilio_events_tenant on twilio.provider_events using (tenant_id=current_setting('app.current_org_id',true)) with check (tenant_id=current_setting('app.current_org_id',true));
create policy twilio_verdicts_tenant on twilio.effect_verdicts using (tenant_id=current_setting('app.current_org_id',true)) with check (tenant_id=current_setting('app.current_org_id',true));

grant usage on schema twilio to agenttrust_app;
grant select, insert, update on twilio.identities,twilio.dispatch_ledger,twilio.provider_events,twilio.effect_verdicts to agenttrust_app;
