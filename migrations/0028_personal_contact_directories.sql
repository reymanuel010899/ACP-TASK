-- Contact trees are personal inside a tenant.  Tenant identity still owns the
-- integration and billing boundary, while this immutable owner identifies
-- which principal owns each root.  Visible names and paths are not ownership.
alter table contacts.branches
    add column owner_principal_id text;

-- Preserve roots created before this invariant existed.  Their initial grant
-- is the only durable ownership evidence written by the old application.
update contacts.branches as branch
   set owner_principal_id = (
      select permission.principal_id
        from contacts.branch_permissions as permission
       where permission.tenant_id = branch.tenant_id
         and permission.branch_id = branch.branch_id
         and permission.dimension = 'administer'
         and permission.reason = 'initial directory owner'
       order by permission.updated_at
       limit 1
   )
 where branch.parent_branch_id is null
   and branch.owner_principal_id is null;

-- The database, rather than a request-time check, prevents concurrent requests
-- from giving one principal two personal roots.
create unique index branches_one_personal_root_per_principal
    on contacts.branches(tenant_id, owner_principal_id)
    where parent_branch_id is null and owner_principal_id is not null;

create index branches_by_personal_owner
    on contacts.branches(tenant_id, owner_principal_id)
    where owner_principal_id is not null;
