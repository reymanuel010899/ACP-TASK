-- migrations/0009_rls_policies.sql (unit U9)
--
-- Multi-tenancy end to end: RLS policies for every tenant-scoped table that
-- actually HAS a way to determine its owning organization, wiring
-- ``identity.organization_members``'s U2 pattern (ENABLE + FORCE ROW LEVEL
-- SECURITY, paired) out to the rest of the schema. Every policy here is
-- paired with FORCE for the exact same reason U2's is: the migration/owner
-- role that creates these tables (tools/migrate.py's admin DSN) must ALSO
-- be bound by the policy, not just ordinary service-role callers, or the
-- guarantee is only cosmetic (see tests/lib/test_identity_repository.py's
-- RLS section, and this unit's tests/lib/test_multi_tenancy.py, for the
-- superuser-bypass caveat and how both test that anyway).
--
-- ---------------------------------------------------------------------------
-- Reality check (read before extending this file): which tables get a
-- policy here, and which are explicitly left out, per-table, on purpose.
-- ---------------------------------------------------------------------------
--
-- WITH organization_id, direct-column policy:
--   * marketplace.tasks   (nullable organization_id, migrations/0007)
--   * audit.audit_log      (nullable organization_id, migrations/0004)
--
-- WITHOUT organization_id, JOIN-based policy (the one case the plan calls
-- out as achievable without a schema change):
--   * registry.agents -- via identity.principals.home_organization_id,
--     joined on registry.agents.principal_id = identity.principals.principal_id.
--
-- WITHOUT organization_id, EXPLICITLY SKIPPED this unit (not silently
-- ignored -- each has a prior unit's own report already flagging the gap):
--   * vault.keyrings / vault.credentials / vault.credential_grants -- U3's
--     report already flagged this: a credential's tenant is really its
--     owning principal's home_organization_id (one join away, same shape as
--     registry.agents below), but vault currently has no dedicated service
--     role distinct from identity/registry in a way that changes this
--     decision, and -- more importantly -- extending RLS here changes
--     nothing about *this* unit's own scope discipline: adding it now would
--     be indistinguishable from "and also do vault while I'm here", exactly
--     what this unit's instructions say not to smuggle in. Left for a
--     future unit to pick up deliberately, with its own test plan.
--   * marketplace.hiring_grants / marketplace.ratings /
--     marketplace.rating_summary -- U8's tables, same reasoning: no
--     organization_id column and no join target more specific than the same
--     identity.principals.home_organization_id path (via
--     agent_principal_id/user_principal_id), which is a real design
--     decision (whose org -- the agent's or the hiring user's? -- governs
--     visibility) deliberately deferred rather than guessed at here.
--
-- ---------------------------------------------------------------------------
-- The ONE NULL-handling decision this unit makes, applied consistently to
-- every direct-column AND join-based policy below:
-- ---------------------------------------------------------------------------
--
-- Nothing in this codebase populates organization_id/home_organization_id
-- for the overwhelming majority of rows yet (see this unit's report -- no
-- caller passes one; marketplace.tasks and audit.audit_log both default to
-- NULL, and most identity.principals rows have no home_organization_id
-- either). A STRICT policy (`organization_id = current_setting(...)`, no
-- NULL branch) would make almost every existing row invisible the moment
-- ANY session sets an org context, and -- just as importantly -- would make
-- them invisible to a session that never sets one either, since
-- `current_setting('app.current_org_id', true)` then returns '' (this
-- migration's own request-context plumbing, libs/db.py's
-- ``bind_organization_id``, always calls ``set_config`` with '' rather than
-- leaving the GUC literally unset -- see that module), and `NULL = ''` is
-- never true. That would silently break every existing, must-still-pass
-- test and demo flow that lists tasks / audit entries without ever having
-- threaded an organization through (i.e. today's entire test suite).
--
-- So every policy below is PERMISSIVE on NULL: a row with no
-- organization_id (or, for the join-based policy, an agent principal with
-- no home_organization_id) is visible to EVERY session, tenant-scoped or
-- not -- ``organization_id = current_setting('app.current_org_id', true) OR
-- organization_id IS NULL``. This keeps today's overwhelmingly-NULL reality
-- fully functional while still delivering the design doc's actual intent
-- for the rows that DO carry a real organization_id: a session scoped to
-- org A can never read an EXPLICITLY org-B-scoped row, proven in this
-- unit's tests by hand-inserting a row with a real (non-null)
-- organization_id for "org B" and confirming an org-A-scoped session still
-- can't see it, even though it also sees every NULL row. This is a
-- deliberate, documented choice for what's useful TODAY (nothing populated
-- yet) rather than the eventual fully-populated future -- once every write
-- path is updated to actually populate organization_id (a later unit's
-- job), this same policy shape keeps working unchanged; only the row data
-- changes, not the policy.
--
-- identity.organization_members (U2) is NOT touched here: its
-- organization_id column is NOT NULL (it's a join-table primary-key column,
-- always populated), so it never needed an IS NULL branch and keeps its
-- original, unmodified U2 policy.

-- ---------------------------------------------------------------------------
-- 1. marketplace.tasks -- direct column, nullable.
-- ---------------------------------------------------------------------------

alter table marketplace.tasks enable row level security;
alter table marketplace.tasks force row level security;
create policy tasks_org_isolation on marketplace.tasks
    using (
        organization_id = current_setting('app.current_org_id', true)
        or organization_id is null
    );

-- ---------------------------------------------------------------------------
-- 2. audit.audit_log -- direct column, nullable. Partitioned by created_at
--    (migrations/0004_audit.sql): enabling + forcing RLS on the partitioned
--    PARENT applies uniformly to every partition queried through the parent
--    name (audit.audit_log), which is the only name any caller ever uses.
-- ---------------------------------------------------------------------------

alter table audit.audit_log enable row level security;
alter table audit.audit_log force row level security;
create policy audit_log_org_isolation on audit.audit_log
    using (
        organization_id = current_setting('app.current_org_id', true)
        or organization_id is null
    );

-- ---------------------------------------------------------------------------
-- 3. registry.agents -- JOIN-based, via identity.principals.home_organization_id
--    (registry.agents itself has no organization_id column -- U5's own
--    report already flagged this as the expected route for U9).
-- ---------------------------------------------------------------------------

alter table registry.agents enable row level security;
alter table registry.agents force row level security;
create policy agents_org_isolation on registry.agents
    using (
        exists (
            select 1
            from identity.principals p
            where p.principal_id = registry.agents.principal_id
              and (
                p.home_organization_id = current_setting('app.current_org_id', true)
                or p.home_organization_id is null
              )
        )
    );
