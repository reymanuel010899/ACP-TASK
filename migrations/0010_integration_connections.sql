-- Durable, tenant-bound provider installations (U1).

create schema integrations;

create type integrations.connection_status as enum (
    'connected', 'degraded', 'refreshing', 'rotation_uncertain',
    'pending_revocation', 'disconnect_pending', 'blocked_connection',
    'disconnected', 'migration_blocked'
);

create table integrations.connections (
    connection_id       text primary key,
    tenant_id           text not null references identity.organizations(organization_id),
    owner_principal_id  text not null references identity.principals(principal_id),
    provider            text not null,
    app_id              text not null,
    team_id             text,
    team_name           text,
    enterprise_id       text,
    bot_user_id         text,
    credential_id       text references vault.credentials(credential_id) on delete restrict,
    credential_version  bigint not null default 1 check (credential_version > 0),
    effective_scopes    jsonb not null default '[]',
    enabled_capabilities jsonb not null default '[]',
    status              integrations.connection_status not null default 'connected',
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),
    disconnected_at     timestamptz,
    foreign key (tenant_id, owner_principal_id)
        references identity.organization_members(organization_id, principal_id),
    check (provider <> 'slack' or team_id is not null),
    check (status <> 'connected' or credential_id is not null)
);

create unique index integration_slack_installation_uq
    on integrations.connections(provider, app_id, team_id)
    where provider = 'slack' and team_id is not null;
create unique index integration_google_owner_uq
    on integrations.connections(tenant_id, owner_principal_id, provider, app_id)
    where provider = 'google';
create index integration_connection_owner_idx
    on integrations.connections(tenant_id, owner_principal_id, provider, status);

create table integrations.legacy_connection_map (
    legacy_key       text primary key,
    connection_id    text unique references integrations.connections(connection_id),
    migration_status integrations.connection_status not null,
    source_checksum  text not null,
    error_code       text,
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now()
);

alter table integrations.connections enable row level security;
alter table integrations.connections force row level security;
create policy integration_connections_tenant_isolation
    on integrations.connections
    using (tenant_id = current_setting('app.current_org_id', true))
    with check (
        tenant_id = current_setting('app.current_org_id', true)
        and exists (
            select 1 from identity.organization_members membership
            where membership.organization_id = tenant_id
              and membership.principal_id = owner_principal_id
        )
    );

alter table integrations.legacy_connection_map enable row level security;
alter table integrations.legacy_connection_map force row level security;
create policy legacy_connection_map_tenant_isolation
    on integrations.legacy_connection_map
    using (
        connection_id is null
        or exists (
            select 1 from integrations.connections connection
            where connection.connection_id = legacy_connection_map.connection_id
        )
    );
