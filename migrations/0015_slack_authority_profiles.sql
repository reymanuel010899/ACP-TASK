-- Separate bot, user, and Enterprise-admin authority for one Slack
-- installation. This migration is expand-only.
--
-- A workspace connection is not a single authority. The bot acts for the
-- tenant; a user token acts for one person and must not become a tenant-wide
-- capability just because it lives on the same connection. Keeping the grants
-- in distinct rows, each with its own subject and consent owner, is what makes
-- "who is this acting as" answerable at dispatch time instead of inferred.

create table orchestrator.slack_authority_profiles (
    authority_profile_id text not null,
    tenant_id text not null,
    connection_id text not null,
    profile_kind text not null check (profile_kind in (
        'bot', 'user', 'enterprise_admin'
    )),
    -- The Slack identity the token acts as. Null for bot profiles, which act
    -- as the installation rather than as a person.
    slack_subject_id text,
    -- The ACP principal who consented. For a user profile this is the only
    -- principal allowed to use it without an explicit delegation.
    consent_owner_principal_id text not null,
    credential_id text not null,
    credential_version bigint not null check (credential_version > 0),
    granted_scopes jsonb not null default '[]',
    status text not null check (status in ('active', 'revoked', 'expired')),
    -- Profiles land disabled. Enabling one is a deliberate act after its
    -- custody, subject binding, and negative authorization tests pass.
    enabled boolean not null default false,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    revoked_at timestamptz,
    primary key (authority_profile_id, tenant_id),
    unique (
        tenant_id, connection_id, profile_kind, consent_owner_principal_id
    ),
    check (profile_kind = 'bot' or slack_subject_id is not null)
);

create index slack_authority_profiles_lookup
    on orchestrator.slack_authority_profiles(
        tenant_id, connection_id, profile_kind
    ) where status = 'active';

-- Lending personal authority to someone else is a separate, narrower grant:
-- one audience, one operation family, one stated purpose, and an expiry.
-- Without a matching row, personal authority is requester-equals-subject.
create table orchestrator.slack_authority_delegations (
    delegation_id text not null,
    tenant_id text not null,
    authority_profile_id text not null,
    audience_principal_id text not null,
    operation_family text not null,
    purpose text not null,
    granted_by_principal_id text not null,
    expires_at timestamptz not null,
    created_at timestamptz not null default now(),
    revoked_at timestamptz,
    primary key (delegation_id, tenant_id),
    unique (
        tenant_id, authority_profile_id, audience_principal_id,
        operation_family
    ),
    foreign key (authority_profile_id, tenant_id)
        references orchestrator.slack_authority_profiles(
            authority_profile_id, tenant_id
        )
);

create index slack_authority_delegations_live
    on orchestrator.slack_authority_delegations(
        tenant_id, audience_principal_id, operation_family, expires_at
    ) where revoked_at is null;

do $$
declare table_name text;
begin
    foreach table_name in array array[
        'slack_authority_profiles', 'slack_authority_delegations'
    ] loop
        execute format('alter table orchestrator.%I enable row level security', table_name);
        execute format('alter table orchestrator.%I force row level security', table_name);
        execute format(
            'create policy %I on orchestrator.%I using '
            '(tenant_id = current_setting(''app.current_org_id'', true)) '
            'with check (tenant_id = current_setting(''app.current_org_id'', true))',
            table_name || '_tenant_isolation', table_name
        );
    end loop;
end $$;
