-- Strict tenant foundation.
--
-- This forward migration supersedes the policies created by 0009, 0025,
-- and 0026 without rewriting migration history. Public Agent Cards and
-- capabilities remain globally discoverable; private ownership is stored in
-- registry.agent_ownership and is protected by the canonical
-- app.current_org_id request setting.

begin;

-- The existing policies are FORCEd and NULL-permissive. A dedicated
-- non-superuser migration owner would still be subject to their UPDATE
-- checks, so lift FORCE and remove those policies inside this transaction
-- before repairing rows. No weaker state becomes visible before commit.
drop policy if exists tasks_org_isolation on marketplace.tasks;
alter table marketplace.tasks no force row level security;
drop policy if exists audit_log_org_isolation on audit.audit_log;
alter table audit.audit_log no force row level security;

-- Deterministic legacy backfill. A principal's explicit home organization is
-- the only evidence strong enough to assign automatically. Rows that cannot
-- be proven remain NULL, preserved in place, and become tenant-invisible
-- under the strict policies below.
update marketplace.tasks task
set organization_id = author.home_organization_id
from identity.principals author
where task.organization_id is null
  and author.principal_id = task.author_principal_id
  and author.home_organization_id is not null;

-- Audit is append-only through a rewrite rule. Temporarily remove that rule
-- for this one deterministic administrative repair, then restore it before
-- any policy or privilege changes become visible.
drop rule audit_log_no_update on audit.audit_log;
update audit.audit_log entry
set organization_id = principal.home_organization_id
from identity.principals principal
where entry.organization_id is null
  and principal.principal_id = entry.principal_id
  and principal.home_organization_id is not null;
create rule audit_log_no_update as
    on update to audit.audit_log do instead nothing;

-- Tenant-owned task and audit rows fail closed. NULL rows remain available
-- only to explicitly privileged administrative connections that bypass RLS.
create policy tasks_org_isolation on marketplace.tasks
    using (
        organization_id = nullif(
            current_setting('app.current_org_id', true), ''
        )
    )
    with check (
        organization_id = nullif(
            current_setting('app.current_org_id', true), ''
        )
    );
alter table marketplace.tasks force row level security;

create policy audit_log_org_isolation on audit.audit_log
    using (
        organization_id = nullif(
            current_setting('app.current_org_id', true), ''
        )
    )
    with check (
        organization_id = nullif(
            current_setting('app.current_org_id', true), ''
        )
    );
alter table audit.audit_log force row level security;

-- registry.agents and registry.agent_capabilities are the public discovery
-- catalog. The old policy made cards tenant-dependent, so remove it and make
-- the public nature explicit. Direct writes remain limited by role grants and
-- Registry API authorization.
drop policy if exists agents_org_isolation on registry.agents;
alter table registry.agents no force row level security;
alter table registry.agents disable row level security;

create table registry.agent_ownership (
    principal_id text primary key
        references registry.agents(principal_id) on delete cascade,
    organization_id text not null
        references identity.organizations(organization_id) on delete restrict,
    created_by_principal_id text
        references identity.principals(principal_id) on delete set null,
    assigned_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
create index agent_ownership_org_idx
    on registry.agent_ownership(organization_id, principal_id);

-- An existing first-class agent can be assigned automatically only when its
-- own and its creator's explicit home organizations do not conflict. A legacy
-- discovery-only registration (created_by IS NULL) intentionally receives no
-- ownership row.
insert into registry.agent_ownership (
    principal_id,
    organization_id,
    created_by_principal_id
)
select
    agent.principal_id,
    coalesce(principal.home_organization_id, creator.home_organization_id),
    principal.created_by
from registry.agents agent
join identity.principals principal
  on principal.principal_id = agent.principal_id
left join identity.principals creator
  on creator.principal_id = principal.created_by
where principal.created_by is not null
  and coalesce(
        principal.home_organization_id,
        creator.home_organization_id
      ) is not null
  and (
        principal.home_organization_id is null
        or creator.home_organization_id is null
        or principal.home_organization_id = creator.home_organization_id
      )
on conflict (principal_id) do nothing;

alter table registry.agent_ownership enable row level security;
alter table registry.agent_ownership force row level security;
create policy agent_ownership_org_isolation on registry.agent_ownership
    using (
        organization_id = nullif(
            current_setting('app.current_org_id', true), ''
        )
    )
    with check (
        organization_id = nullif(
            current_setting('app.current_org_id', true), ''
        )
    );

-- Replace the Campaign and Voice policies with the one canonical request
-- key used by libs/db.py.
drop policy if exists tenant_isolation on campaign.campaigns;
create policy tenant_isolation on campaign.campaigns
    using (tenant_id = nullif(current_setting('app.current_org_id', true), ''))
    with check (tenant_id = nullif(current_setting('app.current_org_id', true), ''));

drop policy if exists tenant_isolation on campaign.campaign_cohort;
create policy tenant_isolation on campaign.campaign_cohort
    using (tenant_id = nullif(current_setting('app.current_org_id', true), ''))
    with check (tenant_id = nullif(current_setting('app.current_org_id', true), ''));

drop policy if exists tenant_isolation on campaign.campaign_effects;
create policy tenant_isolation on campaign.campaign_effects
    using (tenant_id = nullif(current_setting('app.current_org_id', true), ''))
    with check (tenant_id = nullif(current_setting('app.current_org_id', true), ''));

drop policy if exists tenant_isolation on campaign.campaign_audit;
create policy tenant_isolation on campaign.campaign_audit
    using (tenant_id = nullif(current_setting('app.current_org_id', true), ''))
    with check (tenant_id = nullif(current_setting('app.current_org_id', true), ''));

drop policy if exists tenant_isolation on campaign.throughput_limits;
create policy tenant_isolation on campaign.throughput_limits
    using (tenant_id = nullif(current_setting('app.current_org_id', true), ''))
    with check (tenant_id = nullif(current_setting('app.current_org_id', true), ''));

drop policy if exists tenant_isolation on voice.transfer_routes;
create policy tenant_isolation on voice.transfer_routes
    using (tenant_id = nullif(current_setting('app.current_org_id', true), ''))
    with check (tenant_id = nullif(current_setting('app.current_org_id', true), ''));

drop policy if exists tenant_isolation on voice.unfiled_activity;
create policy tenant_isolation on voice.unfiled_activity
    using (tenant_id = nullif(current_setting('app.current_org_id', true), ''))
    with check (tenant_id = nullif(current_setting('app.current_org_id', true), ''));

drop policy if exists tenant_isolation on voice.transfer_work_items;
create policy tenant_isolation on voice.transfer_work_items
    using (tenant_id = nullif(current_setting('app.current_org_id', true), ''))
    with check (tenant_id = nullif(current_setting('app.current_org_id', true), ''));

-- roles.sql normally supplies these grants. This conditional grant also
-- covers databases where roles.sql was applied before this table existed.
do $$
begin
    if exists (select 1 from pg_roles where rolname = 'registry_svc') then
        grant select, insert, update, delete
            on registry.agent_ownership to registry_svc;
    end if;
end
$$;

commit;
