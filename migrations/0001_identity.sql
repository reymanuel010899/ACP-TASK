-- migrations/0001_identity.sql (unit U2)
--
-- Shared identity schema: principals, key rotation history, organizations,
-- teams. Verbatim from docs/architecture/database-design.md Section 3, with
-- one addition flagged in-line: FORCE ROW LEVEL SECURITY alongside ENABLE
-- (a security-review finding on the plan -- Postgres exempts the
-- table-owning/migration role from RLS by default unless FORCE is also set,
-- so without it the policy below would only ever bind ordinary callers, not
-- the owner role tools/migrate.py itself connects as).

create schema identity;

create type identity.principal_type as enum ('user', 'agent', 'verifier', 'service');
create type identity.principal_status as enum ('active', 'suspended', 'revoked');
create type identity.org_role as enum ('owner', 'admin', 'manager', 'member');
create type identity.org_plan as enum ('free', 'pro', 'enterprise');

create table identity.organizations (
    organization_id     text primary key,
    name                text not null,
    plan                identity.org_plan not null default 'free',
    industry            text,
    website             text,
    location            text,
    created_at          timestamptz not null default now()
);

create table identity.principals (
    principal_id         text primary key,
    principal_type        identity.principal_type not null,
    display_name          text,
    status                identity.principal_status not null default 'active',
    home_organization_id  text references identity.organizations(organization_id),
    created_at            timestamptz not null default now(),
    last_active_at        timestamptz,
    created_by             text references identity.principals(principal_id),
    extensions              jsonb not null default '{}'
);
create index principals_org_idx on identity.principals(home_organization_id);
create index principals_type_idx on identity.principals(principal_type) where status = 'active';

create table identity.principal_keys (
    key_id        text primary key,
    principal_id  text not null references identity.principals(principal_id),
    public_key    varchar(44) not null,
    key_algorithm text not null default 'ed25519',
    status        identity.principal_status not null default 'active',
    created_at    timestamptz not null default now(),
    revoked_at    timestamptz,
    unique (principal_id, public_key)
);
create unique index principal_keys_one_active on identity.principal_keys(principal_id)
    where status = 'active';

create table identity.organization_members (
    organization_id text not null references identity.organizations(organization_id) on delete cascade,
    principal_id    text not null references identity.principals(principal_id) on delete cascade,
    role            identity.org_role not null default 'member',
    joined_at       timestamptz not null default now(),
    primary key (organization_id, principal_id)
);
create index org_members_principal_idx on identity.organization_members(principal_id);

create table identity.teams (
    team_id         text primary key,
    organization_id text not null references identity.organizations(organization_id) on delete cascade,
    name            text not null,
    description     text,
    created_at      timestamptz not null default now()
);

create table identity.team_members (
    team_id      text not null references identity.teams(team_id) on delete cascade,
    principal_id text not null references identity.principals(principal_id) on delete cascade,
    added_at     timestamptz not null default now(),
    primary key (team_id, principal_id)
);

-- RLS: paired with FORCE so it also binds the table-owning/migration role
-- (a security-review finding on this plan -- Postgres exempts owners from
-- RLS by default unless FORCE ROW LEVEL SECURITY is also set).
alter table identity.organization_members enable row level security;
alter table identity.organization_members force row level security;
create policy org_members_isolation on identity.organization_members
    using (organization_id = current_setting('app.current_org_id', true));
