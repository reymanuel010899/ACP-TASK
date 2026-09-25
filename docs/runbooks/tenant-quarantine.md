# Tenant Quarantine Runbook

Use this runbook after applying `migrations/0029_strict_tenant_foundation.sql` when legacy Marketplace tasks, Audit entries, or registered agents have no defensible organization owner.

Run every query with the administrative migration DSN. Tenant runtime roles cannot and should not see quarantined records. Never assign a record based only on a request parameter or a display name.

## 1. Inventory before and after migration

```sql
select count(*) as unowned_tasks
from marketplace.tasks
where organization_id is null;

select count(*) as unowned_audit_entries
from audit.audit_log
where organization_id is null;

select count(*) as agents_without_ownership
from registry.agents agent
left join registry.agent_ownership ownership
  on ownership.principal_id = agent.principal_id
where ownership.principal_id is null;
```

The migration does not delete these source rows. A remaining count means the row is quarantined and invisible to ordinary tenant roles.

## 2. Establish ownership evidence

Acceptable evidence is an existing organization membership, an explicit `home_organization_id`, or an independently verified administrative record. Conflicting memberships or creator metadata require manual investigation.

```sql
select principal_id, home_organization_id, created_by
from identity.principals
where principal_id = :'principal_id';

select organization_id, principal_id, role, joined_at
from identity.organization_members
where principal_id = :'principal_id'
order by joined_at;
```

## 3. Assign one record explicitly

Perform assignment in a transaction and record the operator and evidence reference in the central audit trail used by the environment.

```sql
begin;

update marketplace.tasks
set organization_id = :'organization_id'
where task_id = :'task_id'
  and organization_id is null;

-- For an agent, use an insert so an existing owner cannot be overwritten.
insert into registry.agent_ownership (
  principal_id, organization_id, created_by_principal_id
) values (
  :'agent_principal_id', :'organization_id', :'operator_principal_id'
);

commit;
```

Audit entries are append-only. Do not rewrite an old entry casually; use the approved compliance repair procedure for that environment and append a separate repair event.

## 4. Verify through a runtime role

Set the organization transaction-locally and confirm only that organization's rows become visible:

```sql
begin;
select set_config('app.current_org_id', :'organization_id', true);
select task_id, organization_id from marketplace.tasks where task_id = :'task_id';
select principal_id, organization_id
from registry.agent_ownership
where principal_id = :'agent_principal_id';
rollback;
```

Repeat with a different organization and with an empty setting; both queries must return no assigned row.
