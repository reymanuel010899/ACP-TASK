-- infra/roles.sql
--
-- One least-privilege Postgres role per service (KTD5), applied BEFORE any
-- migration runs. The role that creates tables (whatever admin/owner DSN
-- `tools/migrate.py` connects with -- e.g. the `postgres` superuser in
-- infra/docker-compose.yml, or a dedicated non-superuser owner in a real
-- deployment) is never one of the roles below, and no service is meant to
-- ever connect at runtime with that owner's credentials.
--
-- Apply (idempotent, safe to re-run at any point, before or after the
-- target schemas exist):
--
--   psql "$DATABASE_URL" -f infra/roles.sql
--
-- Why this looks the way it does: at U1 time none of the seven schemas
-- (identity, catalog, registry, trust, marketplace, vault, audit) exist yet
-- -- they land in later units (U2-U8). `GRANT ... ON SCHEMA x` and
-- `ALTER DEFAULT PRIVILEGES IN SCHEMA x` both hard-error if schema `x`
-- doesn't exist, so every grant below is wrapped in a check against
-- pg_namespace and only runs for schemas that are already present. Re-run
-- this script (e.g. once more after U2 lands `identity`/`catalog`, again
-- after U3/U4/U5/U6 land the rest) and each service role picks up access to
-- the newly-created schemas with no other change needed -- including
-- `ALTER DEFAULT PRIVILEGES`, so tables created by later migrations are
-- covered automatically too, without a third grants-only migration file.

-- 1. Roles ------------------------------------------------------------
-- LOGIN, no superuser/createdb/createrole, NOINHERIT (each role only ever
-- has the privileges granted directly to it below -- no surprise privilege
-- escalation through group-role membership). Passwords here are
-- local/CI-only development defaults, not a secrets-management story
-- (out of scope for this plan, see Scope Boundaries) -- override them with
-- real credentials (e.g. `ALTER ROLE ... WITH PASSWORD ...`) in any shared
-- or long-lived environment.

do $$
declare
  role_name text;
begin
  foreach role_name in array array[
    'registry_svc',
    'vault_svc',
    'audit_svc',
    'trust_svc',
    'marketplace_svc'
  ]
  loop
    if not exists (select 1 from pg_catalog.pg_roles where rolname = role_name) then
      execute format(
        'create role %I with login password %L noinherit nosuperuser nocreatedb nocreaterole',
        role_name, role_name || '_dev_password'
      );
    end if;
  end loop;
end
$$;

-- 2. Schema-scoped grants ----------------------------------------------
-- (schema, role, access_level) triples. access_level:
--   'full'        select/insert/update/delete -- the service's own schema.
--   'read'        select only -- a schema another service's domain
--                 legitimately needs to look up (e.g. registry reading
--                 identity.principals, catalog.capabilities).
--   'append_only' select/insert, no update/delete -- audit_svc's own
--                 schema; defense in depth on top of the append-only
--                 enforcement (REVOKE + rule) that migrations/0004_audit.sql
--                 adds at the table level in U4.
--
-- Every future table/sequence in a schema below is covered too via
-- ALTER DEFAULT PRIVILEGES, so a later migration that adds a table to an
-- already-granted schema does not need its own grants statement.

do $$
declare
  grant_row record;
  schema_exists boolean;
begin
  for grant_row in
    select * from (values
      ('registry',    'registry_svc',    'full'),
      -- U5: upgraded from 'read' to 'full'. registry/repository.py and
      -- libs/reputation_repository.py's "ensure principal exists"/"ensure
      -- capability exists" FK-satisfying helpers (the same pattern
      -- vault/repository.py established in U3) INSERT into
      -- identity.principals/identity.principal_keys and
      -- catalog.capabilities directly, and RegistryService writes
      -- reputation straight into trust.reputation_records (R2) -- a
      -- read-only grant on any of the three would reject those writes
      -- outright under a real least-privilege connection. (Tests exercise
      -- this code through the default superuser DATABASE_URL, not through
      -- registry_svc, so this gap was latent rather than test-visible.)
      ('identity',    'registry_svc',    'full'),
      ('catalog',     'registry_svc',    'full'),
      ('trust',       'registry_svc',    'full'),

      ('vault',       'vault_svc',       'full'),
      ('identity',    'vault_svc',       'read'),

      ('audit',       'audit_svc',       'append_only'),
      ('identity',    'audit_svc',       'read'),

      ('trust',       'trust_svc',       'full'),
      -- U5: upgraded from 'read' to 'full' for the same reason as
      -- registry_svc above -- ReputationRepository's ensure-principal/
      -- ensure-capability helpers write to both schemas.
      ('identity',    'trust_svc',       'full'),
      ('catalog',     'trust_svc',       'full'),

      ('marketplace', 'marketplace_svc', 'full'),
      -- U6: upgraded identity/catalog from 'read' to 'full' for the same
      -- reason registry_svc/trust_svc were upgraded in U5:
      -- apps/marketplace/server/repository.py's _ensure_principal/
      -- _ensure_capability FK-satisfying helpers (the same pattern
      -- established in U3/U5) INSERT into identity.principals and
      -- catalog.capabilities directly. trust stays 'read' -- this unit
      -- never writes trust.evidence (see migrations/0007_marketplace.sql's
      -- header note on evidence_id staying NULL).
      --
      -- U8: migrations/0008_hiring.sql's new tables (hiring_grants,
      -- grant_capabilities, grant_credential_scopes, ratings,
      -- rating_summary) all live in this SAME 'marketplace' schema, and
      -- agent_marketplace/repository.py's _ensure_principal/
      -- _ensure_capability helpers write to identity/catalog exactly like
      -- U6/U7's did -- no new (schema, role) row needed here, this
      -- migration's tables are covered by the three grants already above.
      ('identity',    'marketplace_svc', 'full'),
      ('catalog',     'marketplace_svc', 'full'),
      ('trust',       'marketplace_svc', 'read')
    ) as t(schema_name, role_name, access_level)
  loop
    select exists (
      select 1 from pg_catalog.pg_namespace where nspname = grant_row.schema_name
    ) into schema_exists;

    if not schema_exists then
      continue;
    end if;

    execute format('grant usage on schema %I to %I', grant_row.schema_name, grant_row.role_name);

    if grant_row.access_level = 'full' then
      execute format(
        'grant select, insert, update, delete on all tables in schema %I to %I',
        grant_row.schema_name, grant_row.role_name
      );
      execute format(
        'grant usage, select on all sequences in schema %I to %I',
        grant_row.schema_name, grant_row.role_name
      );
      execute format(
        'alter default privileges in schema %I grant select, insert, update, delete on tables to %I',
        grant_row.schema_name, grant_row.role_name
      );
      execute format(
        'alter default privileges in schema %I grant usage, select on sequences to %I',
        grant_row.schema_name, grant_row.role_name
      );

    elsif grant_row.access_level = 'append_only' then
      execute format(
        'grant select, insert on all tables in schema %I to %I',
        grant_row.schema_name, grant_row.role_name
      );
      execute format(
        'grant usage, select on all sequences in schema %I to %I',
        grant_row.schema_name, grant_row.role_name
      );
      execute format(
        'alter default privileges in schema %I grant select, insert on tables to %I',
        grant_row.schema_name, grant_row.role_name
      );
      execute format(
        'alter default privileges in schema %I grant usage, select on sequences to %I',
        grant_row.schema_name, grant_row.role_name
      );

    elsif grant_row.access_level = 'read' then
      execute format(
        'grant select on all tables in schema %I to %I',
        grant_row.schema_name, grant_row.role_name
      );
      execute format(
        'alter default privileges in schema %I grant select on tables to %I',
        grant_row.schema_name, grant_row.role_name
      );
    end if;
  end loop;
end
$$;
