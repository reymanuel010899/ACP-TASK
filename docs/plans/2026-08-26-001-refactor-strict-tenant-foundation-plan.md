---
title: Strict Tenant Foundation and Public Registry Separation
type: refactor
status: completed
date: 2026-08-26
origin: docs/plans/2026-08-25-001-refactor-core-architecture-consolidation-plan.md
---

# Strict Tenant Foundation and Public Registry Separation

## Summary

Establish one fail-closed tenant contract across PostgreSQL while preserving global discovery of public Agent Cards and capabilities. The work uses a forward-only migration, separates private agent ownership from public registry data, quarantines unowned legacy rows, and proves isolation using non-owner, non-`BYPASSRLS` database roles.

---

## Problem Frame

The database currently mixes `app.current_org_id` and `app.tenant_id`, contains policies that intentionally expose rows whose organization is `NULL`, and derives agent ownership indirectly from identity records. This makes isolation behavior inconsistent and allows missing tenant context to behave differently across schemas.

---

## Requirements

- R1. `app.current_org_id` is the only PostgreSQL session setting used for organization isolation; no active policy depends on `app.tenant_id`.
- R2. Tenant-owned reads and mutations fail closed when tenant context is missing, empty, malformed, or belongs to a different organization.
- R3. Existing migration files remain immutable; all policy correction and safe backfill happen in a new forward migration.
- R4. Public Agent Cards and capability discovery remain globally readable without tenant context.
- R5. Private agent ownership and administration metadata are represented explicitly and isolated by organization instead of inferred from public registry rows.
- R6. Legacy rows with an unambiguous organization are backfilled; rows with no defensible owner are preserved in administrative quarantine and remain invisible to tenant roles.
- R7. Repository code has an explicit tenant contract, including a typed missing-context failure before tenant-owned writes.
- R8. Automated tests exercise reads, inserts, updates, deletes, reassignment attempts, and missing-context behavior through non-owner, non-superuser, non-`BYPASSRLS` roles.

---

## Scope Boundaries

- Do not migrate SQLite-backed services to PostgreSQL in this unit; that is U3 of the parent architecture plan.
- Do not redesign organization membership, invitations, billing, or authentication flows.
- Do not make private agent configuration, credentials, endpoints, or ownership metadata part of public discovery.
- Do not assign ambiguous legacy rows to a synthetic tenant or delete them.
- Do not introduce a general policy engine; PostgreSQL RLS and narrow repository guards are sufficient for this foundation.
- Do not change the public A2A compatibility contract or Agent Card wire format.

### Deferred to Follow-Up Work

- Storage convergence for campaigns, voice, orchestration, and other SQLite repositories: parent plan U3.
- Capability catalog normalization and workflow protocol work: parent plan U4 and U5.
- Administrative UI for reviewing and claiming quarantined records: later control-plane work; this plan supplies deterministic reporting and assignment mechanics only.

---

## Context & Research

### Relevant Code and Patterns

- `libs/db.py` already binds `app.current_org_id` per connection and transaction. Tenant-required repositories need to validate the binding without making global/public repositories require a tenant.
- `migrations/0009_rls_policies.sql` contains the legacy `organization_id IS NULL` visibility behavior that must be superseded, not edited.
- `migrations/0025_campaigns.sql` and `migrations/0026_voice_routing.sql` use the incorrect `app.tenant_id` setting.
- `registry/repository.py` currently combines public registration data with ownership inferred through `identity.principals.created_by` and `home_organization_id`.
- `tests/lib/test_multi_tenancy.py` characterizes the old NULL-visible behavior and must be replaced with strict isolation expectations.
- `infra/roles.sql` defines service roles but does not make `NOBYPASSRLS` and service trust boundaries sufficiently explicit.

### Institutional Learnings

- No applicable entries currently exist under `docs/solutions/`; the architecture contract documents are the controlling local references.

### External References

- PostgreSQL row security defaults to deny when RLS is enabled and no applicable policy exists; owners bypass RLS unless `FORCE ROW LEVEL SECURITY` is used: https://www.postgresql.org/docs/16/ddl-rowsecurity.html
- `USING` controls visibility/existing rows while `WITH CHECK` validates proposed rows for inserts and updates: https://www.postgresql.org/docs/16/sql-createpolicy.html
- Transaction-local settings can be set through `set_config`, matching the current connection wrapper: https://www.postgresql.org/docs/16/functions-admin.html#FUNCTIONS-ADMIN-SET

---

## Key Technical Decisions

- **One session key:** Keep `app.current_org_id` because it is already the shared `libs/db.py` contract and is used by the majority of existing policies.
- **Forward-only correction:** Add `migrations/0029_strict_tenant_foundation.sql`; do not rewrite migrations `0009`, `0025`, or `0026` after they may have been applied elsewhere.
- **Public catalog, private control plane:** Keep `registry.agents` and capability projections globally readable. Introduce a tenant-owned ownership relation keyed by agent principal for administrative authorization and future private metadata.
- **No guessed ownership:** Backfill ownership only from a single, non-conflicting organization supported by existing principal/home-organization data. Ambiguous or missing ownership produces no ownership row.
- **In-place quarantine:** Preserve nullable legacy rows in their source tables. Strict equality policies make unowned rows invisible to tenant roles; an admin-only report and explicit assignment operation make them recoverable without inventing a tenant.
- **Repository-level guard plus RLS:** Repository guards provide clear application errors; RLS remains the final security boundary if a caller bypasses a code path.
- **Direct tenant columns for operational tables:** Prefer direct `tenant_id`/`organization_id` comparisons in policies. Avoid policy subqueries except where the normalized private ownership relation is the actual authorization source.
- **Trusted registry service boundary:** Public registry tables are mutated only through the Registry service's authenticated API. Direct tenant DB roles receive no general write grant to the public catalog.

---

## Open Questions

### Resolved During Planning

- **Should every registry row be tenant-private?** No. Agent Cards and capabilities are public protocol discovery data; only ownership and administrative metadata are tenant-private.
- **What happens to legacy rows without an owner?** They remain stored but invisible to tenant roles until an administrator assigns them.
- **Should historical migrations be edited?** No. A checksum-safe forward migration replaces faulty policies.
- **Should missing context disable filtering?** No. Missing context returns no tenant-owned rows and rejects writes.

### Deferred to Implementation

- **Exact count of quarantine rows in the developer database:** Measure before applying backfill and record it in the migration verification output; it is environment-specific and must not change the policy design.

---

## High-Level Technical Design

```text
anonymous / cross-tenant discovery
        |
        v
registry.agents + capabilities  --------> public Agent Card response
        |
        | agent principal id
        v
registry.agent_ownership  --RLS current_org_id--> owner administration

tenant request
  -> bind organization in libs/db.py
  -> repository requires tenant context
  -> SQL executes as runtime role
  -> RLS USING / WITH CHECK enforces the same organization

legacy row with NULL organization
  -> deterministic backfill when exactly one owner is inferable
  -> otherwise remains in place, invisible to tenant roles
  -> admin-only report/assignment can resolve it later
```

---

## Implementation Units

### U1. Characterize the Tenant Contract and Migration Surface

**Goal:** Lock down migration immutability, the canonical session key, and the complete set of tenant/public tables before changing policies.

**Requirements:** R1, R3, R4

**Dependencies:** None

**Files:**
- Modify: `tests/architecture/test_architecture_contracts.py`
- Create: `tests/migrations/test_strict_tenant_foundation.py`
- Modify: `docs/architecture/target-architecture.md`
- Modify: `docs/architecture/compatibility-contract.md`

**Approach:**
- Add static contract tests that classify public registry surfaces separately from tenant-owned relations.
- Assert new/effective migrations use `app.current_org_id` and prevent future introduction of `app.tenant_id`.
- Document that historical migrations are append-only and that strict behavior is supplied by migration `0029`.

**Execution note:** Characterization-first. These tests should fail before U2 and pass once the forward migration exists.

**Patterns to follow:**
- Existing architecture assertions in `tests/architecture/test_architecture_contracts.py`.

**Test scenarios:**
- Static contract: migration corpus after the compatibility boundary contains no active `app.tenant_id` policy.
- Static contract: public Agent Card discovery is explicitly exempt from tenant-required repository guards.
- Static contract: tenant-owned schemas are listed with their tenant key and expected policy posture.

**Verification:**
- Architecture tests clearly distinguish public discovery from tenant administration and identify every policy replaced by `0029`.

---

### U2. Apply the Forward RLS and Quarantine Migration

**Goal:** Correct active policies, establish private agent ownership, and safely isolate/backfill legacy rows without changing historical migrations.

**Requirements:** R1, R2, R3, R4, R5, R6

**Dependencies:** U1

**Files:**
- Create: `migrations/0029_strict_tenant_foundation.sql`
- Modify: `infra/roles.sql`
- Create: `docs/runbooks/tenant-quarantine.md`

**Approach:**
- Drop and recreate Campaign and Voice policies against `app.current_org_id` with both `USING` and `WITH CHECK`.
- Replace NULL-permissive policies on tenant-owned Marketplace and Audit tables with strict equality policies.
- Backfill nullable organization keys only when the referenced principal supports one unambiguous organization; leave all other rows unchanged and hidden.
- Create `registry.agent_ownership` with an organization key, provenance fields, timestamps, strict RLS, indexes, and foreign keys appropriate to existing identity/registry identifiers.
- Backfill ownership only for unambiguous existing Agent Principals. A legacy discovery-only agent may legitimately have no ownership row.
- Make runtime roles explicitly `NOSUPERUSER NOBYPASSRLS`; keep schema/table grants minimal and separate public read access from trusted registry mutation access.
- Provide admin-only inventory and assignment SQL in a runbook, with before/after count checks and no bulk guessed assignment.

**Execution note:** Run the migration in a transaction against an isolated test database before any developer database. Capture pre-migration orphan counts and verify the same rows still exist afterward.

**Patterns to follow:**
- Existing `ENABLE ROW LEVEL SECURITY` plus `FORCE ROW LEVEL SECURITY` policy pattern in tenant-scoped migrations.
- Existing organization foreign keys in `migrations/0001_identity.sql`.

**Test scenarios:**
- Happy path: tenant A sees and mutates only tenant A Campaign, Voice, Task, Audit, and ownership rows.
- Error path: missing or empty `app.current_org_id` returns no rows and rejects inserts/updates.
- Security: tenant A cannot read, update, delete, or reassign tenant B rows.
- Quarantine: a NULL legacy row survives the migration but is invisible to tenant A and tenant B.
- Backfill: a row with exactly one defensible home organization becomes visible only to that organization.
- Public path: Agent Cards and capabilities remain discoverable without tenant context; private ownership does not.
- Migration: applying the complete migration sequence from an empty database succeeds; applying `0029` through the migration runner is safe on an already migrated database.

**Verification:**
- PostgreSQL catalogs show no active policy using `app.tenant_id` or `organization_id IS NULL` as a tenant visibility escape.
- Quarantine counts are reconciled before and after migration, with zero deleted source rows.

---

### U3. Enforce the Repository Tenant Contract

**Goal:** Produce clear application-level failures for tenant-required operations and write explicit agent ownership atomically during registration.

**Requirements:** R2, R4, R5, R7

**Dependencies:** U2

**Files:**
- Create: `libs/repository_contract.py`
- Modify: `libs/db.py`
- Modify: `registry/repository.py`
- Modify: `tests/lib/test_db.py`
- Modify: `tests/registry/test_agent_registration.py`

**Approach:**
- Add a small shared guard that normalizes blank context and raises a typed `TenantContextRequired` error for tenant-owned repository entry points.
- Keep `Database.connection()` usable for public/global reads; tenant enforcement is opt-in and mandatory at tenant repository boundaries rather than global middleware.
- During first-class Agent Principal registration, persist the public registry row and private ownership row within the same transaction.
- Keep legacy `/register` agents discovery-only when no authenticated owner exists; do not synthesize ownership.
- Replace authorization joins that infer control from `created_by` with the explicit ownership relation, while retaining identity provenance for audit purposes.

**Execution note:** Preserve current public registration/discovery compatibility while changing only administrative authorization semantics.

**Patterns to follow:**
- Thread-local organization binding and transaction wrappers in `libs/db.py`.
- Existing transactional agent/capability writes in `registry/repository.py`.

**Test scenarios:**
- Happy path: first-class registration creates Agent Card, capabilities, and ownership atomically.
- Compatibility: legacy registration remains publicly discoverable but has no tenant administration authority.
- Error path: a tenant-owned repository operation without context raises `TenantContextRequired` before executing its mutation.
- Security: changing `created_by` provenance alone does not transfer ownership.
- Atomicity: failure writing ownership rolls back public registration rather than leaving a partially owned agent.

**Verification:**
- Registry unit tests demonstrate separate public discovery and private administrative control.
- DB unit tests demonstrate normalization of `None`, empty, and whitespace-only tenant context.

---

### U4. Prove Isolation Through Runtime Roles

**Goal:** Verify the real PostgreSQL enforcement boundary using roles that cannot bypass RLS, and replace tests that expected NULL-global visibility.

**Requirements:** R2, R6, R8

**Dependencies:** U2, U3

**Files:**
- Modify: `tests/lib/test_multi_tenancy.py`
- Create: `tests/integration/test_strict_tenant_isolation.py`
- Modify: `README.md`

**Approach:**
- Execute cross-tenant scenarios through dedicated non-owner roles with `rolsuper = false` and `rolbypassrls = false` asserted as test preconditions.
- Cover all CRUD directions and tenant-key reassignment, not only SELECT filtering.
- Replace old NULL-visible assertions with quarantine invisibility assertions.
- Make integration tests skip with a precise setup message only when the PostgreSQL test DSN/roles are unavailable; static and unit contract tests must still run everywhere.
- Document the local command and DSN prerequisite for the real-RLS suite.

**Execution note:** The real database test is the release gate for U2. Passing only mocked repository tests is insufficient.

**Patterns to follow:**
- Existing PostgreSQL fixture and organization binding patterns in `tests/lib/test_multi_tenancy.py`.

**Test scenarios:**
- Read: tenant A cannot observe tenant B or quarantined rows.
- Insert: missing context and mismatched tenant key are rejected.
- Update: tenant A cannot modify tenant B payload or change its row to tenant B.
- Delete: tenant A cannot delete tenant B rows.
- Reassignment: direct tenant-key reassignment across organizations is rejected; documented admin assignment remains possible.
- Role integrity: tests fail if executed through a superuser, table owner, or `BYPASSRLS` role.

**Verification:**
- Full migration suite, architecture tests, repository tests, Registry tests, and real PostgreSQL isolation tests pass.

---

## System-Wide Impact

- **Interaction graph:** Authentication/membership binds an organization, `libs/db.py` applies it transaction-locally, repositories enforce required context, and PostgreSQL RLS independently filters/checks rows. Public registry discovery bypasses the tenant-required guard but not authenticated mutation checks.
- **Error propagation:** Missing application context becomes `TenantContextRequired`; RLS violations remain database authorization errors and are translated at existing API boundaries without revealing foreign-row existence.
- **State lifecycle risks:** Agent registration must not create a public row without its required ownership row. Quarantine backfill must be deterministic, count-preserving, and restart-safe through the migration runner.
- **API surface parity:** REST and A2A discovery remain unchanged. Administrative agent operations switch from inferred creator authority to explicit ownership.
- **Integration coverage:** Only a real PostgreSQL role test proves `FORCE ROW LEVEL SECURITY`, missing-context behavior, and cross-tenant writes; unit tests cover guard behavior and transaction atomicity.
- **Unchanged invariants:** Public Agent Cards, capability search, A2A endpoints, and legacy discovery remain available. No credentials or private endpoint secrets are moved into the public catalog.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| A forward migration accidentally hides legitimate legacy data | Preflight counts, deterministic principal-based backfill, preserved in-place quarantine, and an admin assignment runbook |
| Tests pass because they run as owner/superuser | Assert role flags and table ownership before executing isolation scenarios |
| Public catalog visibility leaks private metadata | Store ownership separately and test public responses do not include it |
| Registration leaves partial public/private state | Write registry, capabilities, and ownership in one transaction and test rollback |
| Policy correction breaks Campaign/Voice due to session-key mismatch | Correct both schemas in the same migration and exercise them with `app.current_org_id` |
| Cross-table ownership policy creates performance or race issues | Keep tenant-owned operational policies on direct columns; index ownership keys and limit ownership joins to administrative registry paths |
| Local PostgreSQL role/DSN is unavailable | Keep static/unit tests runnable, document exact setup, and require the real-RLS suite in CI before merge |

---

## Documentation / Operational Notes

- Before applying `0029`, record counts for nullable `marketplace.tasks.organization_id`, `audit.audit_log.organization_id`, and agents without an unambiguous organization.
- After applying it, verify source row counts are unchanged, inferred rows are assigned once, remaining quarantined rows are invisible to runtime roles, and public agent discovery still returns the same cards.
- Administrative reassignment must be explicit, audited, and executed through an owner/admin connection—not a tenant runtime role.
- A rollback should restore prior policies only if necessary; it must not delete newly recorded ownership or erase quarantine evidence.

---

## Sources & References

- **Parent plan:** [docs/plans/2026-08-25-001-refactor-core-architecture-consolidation-plan.md](2026-08-25-001-refactor-core-architecture-consolidation-plan.md)
- Architecture target: [docs/architecture/target-architecture.md](../architecture/target-architecture.md)
- Compatibility contract: [docs/architecture/compatibility-contract.md](../architecture/compatibility-contract.md)
- Database wrapper: [libs/db.py](../../libs/db.py)
- Registry repository: [registry/repository.py](../../registry/repository.py)
- Runtime roles: [infra/roles.sql](../../infra/roles.sql)
- PostgreSQL Row Security Policies: https://www.postgresql.org/docs/16/ddl-rowsecurity.html
- PostgreSQL `CREATE POLICY`: https://www.postgresql.org/docs/16/sql-createpolicy.html
