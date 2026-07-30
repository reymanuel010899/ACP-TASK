-- migrations/0005_registry.sql (unit U5)
--
-- Registry: agent cards, indexed capability search, app federation.
-- Verbatim from docs/architecture/database-design.md Section 5, with ONE
-- deliberate addition called out below.
--
-- Replaces registry/agent_index.py, registry/index_store.py, and
-- registry/app_registry.py's in-memory state (registry/repository.py is the
-- new repository layer backing all three; see that module's docstring for
-- how the two pre-existing, independent registration paths -- the legacy
-- POST /register (skills[].id convention) and POST /agents/register (a
-- first-class Agent Principal, agent_card.capabilities[] convention) -- both
-- land in the ONE registry.agents / registry.agent_capabilities pair below).

create schema registry;

create table registry.agents (
    principal_id   text primary key references identity.principals(principal_id),
    agent_card     jsonb not null,
    status         identity.principal_status not null default 'active',
    registered_at  timestamptz not null default now(),
    updated_at     timestamptz not null default now()
);

create table registry.agent_capabilities (
    principal_id   text not null references registry.agents(principal_id) on delete cascade,
    capability_id  text not null references catalog.capabilities(capability_id),
    declared_at    timestamptz not null default now(),
    primary key (principal_id, capability_id)
);
-- the query that used to be O(n) over every agent_card:
create index agent_capabilities_lookup on registry.agent_capabilities(capability_id);

create table registry.apps (
    app_id          text primary key,
    app_endpoint    text not null,
    p2p_endpoint    text,
    -- Deviation from the design doc's literal DDL: the design doc's
    -- registry.apps has no column for an app's OWN capability list, but the
    -- pre-existing, must-preserve (R10) contract of
    -- registry/app_registry.py's AppRegistry -- GET /apps?capability=<id>
    -- filtering and POST /p2p/permissions/check's "does the target app
    -- declare this capability" check -- requires persisting one. There is
    -- nowhere else in the given schema to put it (it is not a join against
    -- catalog.capabilities anywhere in the existing code, just a free-text
    -- list on the app record), so this column is added here rather than
    -- left unsolved. See registry/repository.py's docstring.
    capabilities    text[] not null default '{}',
    services        text[] not null default '{}',   -- subset of ('agent_marketplace','credential_vault','verification_service')
    registered_at   timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);

-- API keys stored HASHED, never plaintext. The current in-memory _api_keys
-- Set[str] holds the raw 'atk_<token>' value -- a memory dump or log line leak
-- discloses a live credential. This is a correctness gap this design fixes,
-- not just a scalability one.
create table registry.api_keys (
    key_id      text primary key,             -- ULID
    key_hash    text not null unique,          -- sha256(raw_token), raw token shown once at mint time
    app_id      text references registry.apps(app_id),
    created_at  timestamptz not null default now(),
    revoked_at  timestamptz,
    last_used_at timestamptz
);
