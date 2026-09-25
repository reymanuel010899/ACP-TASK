-- Durable control plane for providers whose credential is an account
-- identifier plus a long-lived auth token. This migration is expand-only.
--
-- An OAuth provider hands back its authority in a consent callback, so the
-- connection row is the whole story. A provider authenticated by an account
-- has no callback and no scopes: its authority is whatever the account has
-- been verified to hold, and that state changes without anyone visiting a
-- browser. These tables are that verified state, and the synthetic scopes on
-- the connection are derived from them at connection time and on every
-- re-verification.
--
-- Credential version is deliberately absent from every table here. It counts
-- custody generations of the sealed secret and nothing else, so disabling a
-- sender or losing a family narrows authority by removing derived scope rows,
-- never by bumping a version that would fail every queued effect on the whole
-- connection with a tampering-shaped reason.

-- Tenant-carrying composite keys need the tenant beside the connection.
alter table integrations.connections
    add constraint integration_connections_tenant_key
    unique (connection_id, tenant_id);

create type integrations.provider_account_status as enum (
    -- Authority-bearing.
    'verified',
    -- Known but not yet proven; holds no authority.
    'unverified',
    -- The provider suspended it; holds no authority.
    'suspended',
    -- The account could not be checked at all. Fail closed: this is the
    -- state a provider outage lands in, and it must not read as "unchanged".
    'unavailable'
);

create table integrations.provider_accounts (
    connection_id       text not null,
    tenant_id           text not null,
    provider            text not null,
    -- The identity half of the credential. The secret half never lands here;
    -- it stays sealed in the vault under credential_id on the connection.
    provider_account_id text not null,
    status              integrations.provider_account_status not null
                            default 'unavailable',
    -- Why the account is not verified, in the provider's own words, so an
    -- operator is not left guessing at a status enum.
    status_detail       text,
    verified_at         timestamptz,
    reverified_at       timestamptz,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),
    primary key (connection_id, tenant_id),
    foreign key (connection_id, tenant_id)
        references integrations.connections(connection_id, tenant_id)
        on delete cascade,
    -- One account per connection, and one connection per account: two
    -- connections pointing at the same provider account would give one
    -- tenant's disable no effect on the other's dispatch.
    unique (provider, provider_account_id),
    check (status <> 'verified' or verified_at is not null)
);

create index provider_accounts_live
    on integrations.provider_accounts(tenant_id, provider, status);

-- Capability families the account may use, held per connection so a family
-- can be enabled and disabled independently of every other family.
create table integrations.provider_account_families (
    connection_id  text not null,
    tenant_id      text not null,
    family         text not null,
    -- Families land disabled. Enabling one is a deliberate act.
    enabled        boolean not null default false,
    -- Set when the provider itself withdrew the family, as distinct from an
    -- operator turning it off here.
    provider_state text not null default 'unknown',
    created_at     timestamptz not null default now(),
    updated_at     timestamptz not null default now(),
    primary key (connection_id, tenant_id, family),
    foreign key (connection_id, tenant_id)
        references integrations.provider_accounts(connection_id, tenant_id)
        on delete cascade
);

-- Sending identities the provider has verified for this account, with where
-- each may reach. Disabling one is the narrowest lawful authority change the
-- system supports, so it gets its own row and its own flag.
create table integrations.provider_senders (
    connection_id  text not null,
    tenant_id      text not null,
    sender_id      text not null,
    family         text not null,
    -- ISO 3166-1 alpha-2 destinations this sender is cleared to reach.
    countries      jsonb not null default '[]',
    enabled        boolean not null default false,
    disabled_at    timestamptz,
    disabled_by_principal_id text,
    created_at     timestamptz not null default now(),
    updated_at     timestamptz not null default now(),
    primary key (connection_id, tenant_id, sender_id),
    foreign key (connection_id, tenant_id)
        references integrations.provider_accounts(connection_id, tenant_id)
        on delete cascade,
    foreign key (connection_id, tenant_id, family)
        references integrations.provider_account_families(
            connection_id, tenant_id, family
        ),
    check (enabled or disabled_at is not null)
);

create index provider_senders_enabled
    on integrations.provider_senders(tenant_id, connection_id, family)
    where enabled;

-- Provider-approved message templates, which are authority in their own
-- right: a template send is only permitted against an approved template.
create table integrations.provider_templates (
    connection_id  text not null,
    tenant_id      text not null,
    template_id    text not null,
    family         text not null,
    category       text not null,
    language       text not null,
    approved       boolean not null default false,
    created_at     timestamptz not null default now(),
    updated_at     timestamptz not null default now(),
    primary key (connection_id, tenant_id, template_id),
    foreign key (connection_id, tenant_id)
        references integrations.provider_accounts(connection_id, tenant_id)
        on delete cascade
);

-- The materialised synthetic scopes, one row per scope, each naming what it
-- was derived from. Keeping the derivation visible is what makes "this effect
-- stopped dispatching because that sender was disabled" answerable from data
-- rather than from a reconstruction.
create table integrations.provider_derived_scopes (
    connection_id  text not null,
    tenant_id      text not null,
    scope          text not null,
    -- 'family', 'sender', 'geo' or 'template'.
    dimension      text not null,
    source_id      text not null,
    derived_at     timestamptz not null default now(),
    primary key (connection_id, tenant_id, scope),
    foreign key (connection_id, tenant_id)
        references integrations.provider_accounts(connection_id, tenant_id)
        on delete cascade,
    check (dimension in ('family', 'sender', 'geo', 'template'))
);

create index provider_derived_scopes_source
    on integrations.provider_derived_scopes(
        tenant_id, connection_id, dimension, source_id
    );

-- The account-wide emergency stop, and the only switch here that is not
-- scoped to a connection: R28 makes a stop an account-wide fact covering
-- inbound handling as well as outbound dispatch, so it cannot hang off one
-- provider's connection row.
--
-- The row survives a resume rather than being deleted. "This account was
-- stopped for two hours last Tuesday, by whom, and why" is exactly the
-- question an operator asks afterwards, and a deleted row cannot answer it.
--
-- Nothing here gates reconciliation or provider-event ingestion. A stop that
-- blocked those would strand every in-flight effect at the moment an operator
-- most needs a truthful dispatched-versus-prevented count, and no campaign
-- could ever drain. The stop blocks new dispatch; verdicts still arrive.
create table integrations.tenant_control_plane (
    tenant_id                text primary key,
    stopped                  boolean not null default false,
    stop_reason              text,
    stopped_at               timestamptz,
    stopped_by_principal_id  text,
    resumed_at               timestamptz,
    resumed_by_principal_id  text,
    updated_at               timestamptz not null default now(),
    -- A stop must name who ordered it. An anonymous account-wide halt is not
    -- an operational control, it is an outage with no owner.
    check (not stopped or stopped_by_principal_id is not null)
);

create index tenant_control_plane_stopped
    on integrations.tenant_control_plane(tenant_id)
    where stopped;

do $$
declare table_name text;
begin
    foreach table_name in array array[
        'provider_accounts', 'provider_account_families', 'provider_senders',
        'provider_templates', 'provider_derived_scopes',
        'tenant_control_plane'
    ] loop
        execute format('alter table integrations.%I enable row level security', table_name);
        execute format('alter table integrations.%I force row level security', table_name);
        execute format(
            'create policy %I on integrations.%I using '
            '(tenant_id = current_setting(''app.current_org_id'', true)) '
            'with check (tenant_id = current_setting(''app.current_org_id'', true))',
            table_name || '_tenant_isolation', table_name
        );
    end loop;
end $$;
