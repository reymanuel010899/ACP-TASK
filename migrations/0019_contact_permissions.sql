-- Authority over branches, and the three ways a contact gets grouped without
-- being copied. Expand-only.
--
-- Two claims live in this file, and both are the kind that quietly stop being
-- true if they are left to application code.
--
-- **Authority is four things, not one.** R11 asks for viewing, editing,
-- administering, and using contacts in campaigns to be *independently*
-- grantable. A single `role` column cannot express "may run a campaign to
-- this branch, may not read the names in it", which is precisely the split
-- that lets a campaign operator work without holding the directory. So the
-- dimension is a column, one row per (branch, principal, dimension), and the
-- four dimensions never share a row.
--
-- Inheritance is not stored. A grant on '/acme/sales' is one row and reaches
-- every descendant by ancestry at read time, because materialising the
-- closure would mean a branch move has to rewrite it -- and a permission set
-- that is stale for the length of one migration window is a permission set
-- that is wrong. `contacts.branches.path` already moves with the subtree
-- (0017), so re-derivation after a move is free and cannot be skipped.
--
-- An explicit restriction is the same shape as a grant with `effect =
-- 'restrict'`, so the deepest decision on the ancestry wins by construction
-- and there is no second table to keep consistent with the first.
--
-- **A grouping references the canonical record; it never holds a copy.** R9
-- is unambiguous that one person is one record, and the way that requirement
-- dies is a membership row that carries `display_name` and `phone` "for
-- convenience" -- after which a rename updates the directory, the campaign
-- sends to the old name, and nobody can say which of the two is the person.
-- Every membership table below holds identifiers and provenance and nothing
-- else. There is no name column here to go stale.
--
-- A dynamic segment is the stored rule, not its result. Materialising it
-- would make "expansion invalidates authorization" (R15, KTD7) unfalsifiable,
-- because the stored rows and the rule would already have drifted apart.

-- Who last reached this address, so a masked destination in an approval
-- preview (R14) can be told apart from another masked destination without
-- disclosing either one. Nullable: never contacted is the ordinary starting
-- state and is a different fact from contacted long ago.
alter table contacts.contact_addresses
    add column last_contacted_at timestamptz;

-- The four dimensions.
--
-- `decided_by_authority` is pinned to 'administer' -- the same string 0018
-- requires to lift a suppression. Delegating authority and resuming sending
-- to somebody who was blocked are the two moves that must not be available to
-- a contact manager, and they agree on the word for it, so a future
-- authority-model change cannot loosen one while tightening the other and
-- leave both looking correct.
create table contacts.branch_permissions (
    permission_id           text not null,
    tenant_id               text not null references identity.organizations(organization_id),
    branch_id               text not null,
    -- The principal the authority is about. Not the actor who granted it --
    -- that is `decided_by_principal_id` below, and conflating the two is how
    -- a self-grant becomes indistinguishable from a delegation.
    principal_id            text not null,
    dimension               text not null
                                check (dimension in (
                                    'view', 'edit', 'administer', 'campaign_use'
                                )),
    -- 'grant' opens the subtree. 'restrict' closes it, and beats any grant
    -- above it because it sits deeper on the same ancestry. Absence is
    -- neither: it inherits, and at the root it means no.
    effect                  text not null check (effect in ('grant', 'restrict')),
    -- R12: a permission change is a human decision, recorded with the
    -- authority it was taken under.
    decided_by_principal_id text not null,
    decided_by_authority    text not null,
    decided_by_actor_kind   text not null
                                check (decided_by_actor_kind in (
                                    'human', 'agent', 'system', 'provider',
                                    'contact'
                                )),
    reason                  text,
    recorded_at             timestamptz not null default now(),
    updated_at              timestamptz not null default now(),
    primary key (permission_id),
    unique (permission_id, tenant_id),
    -- The tenant travels inside the reference, so a permission over another
    -- account's branch does not resolve and cannot be written.
    foreign key (branch_id, tenant_id)
        references contacts.branches(branch_id, tenant_id)
        on delete cascade,
    -- One decision per principal, per branch, per dimension. Two rows
    -- disagreeing at the same node would make the resolution order
    -- load-bearing, and the resolution order is not something an operator can
    -- see.
    unique (tenant_id, branch_id, principal_id, dimension),
    -- An agent may propose a permission change; it may never be the decider.
    check (decided_by_actor_kind = 'human'),
    -- Granting authority and restricting it are both administrator moves.
    -- Not enforced only in Python: this is the constraint that holds when the
    -- repository is replaced.
    check (decided_by_authority = 'administer')
);

-- The read this table exists to serve: "what does this principal hold over
-- this ancestry", answered by identifier set rather than by scan.
create index branch_permissions_by_principal
    on contacts.branch_permissions(tenant_id, principal_id, dimension);
create index branch_permissions_by_branch
    on contacts.branch_permissions(tenant_id, branch_id);

-- A list: explicit membership, curated by hand.
--
-- `branch_id` is where the list itself lives, which is what a permission is
-- resolved against when somebody asks to open it. A list is not a way around
-- the tree.
create table contacts.contact_lists (
    list_id                 text not null,
    tenant_id               text not null references identity.organizations(organization_id),
    branch_id               text not null,
    name                    text not null,
    slug                    text not null,
    description             text,
    created_by_principal_id text,
    created_at              timestamptz not null default now(),
    updated_at              timestamptz not null default now(),
    primary key (list_id),
    unique (list_id, tenant_id),
    foreign key (branch_id, tenant_id)
        references contacts.branches(branch_id, tenant_id),
    unique (tenant_id, slug)
);

-- Membership. Identifiers and provenance, and deliberately nothing else.
--
-- No name, no address, no locale. A contact in two lists is two rows here and
-- one row in `contacts.contacts` (R9) -- which is only true as long as this
-- table has nothing worth reading on its own.
create table contacts.contact_list_members (
    tenant_id             text not null references identity.organizations(organization_id),
    list_id               text not null,
    contact_id            text not null,
    added_by_principal_id text,
    added_at              timestamptz not null default now(),
    primary key (list_id, contact_id),
    foreign key (list_id, tenant_id)
        references contacts.contact_lists(list_id, tenant_id)
        on delete cascade,
    foreign key (contact_id, tenant_id)
        references contacts.contacts(contact_id, tenant_id)
        on delete cascade,
    unique (tenant_id, list_id, contact_id)
);

create index contact_list_members_by_contact
    on contacts.contact_list_members(tenant_id, contact_id);

-- A tag: a label, account-wide, applied to canonical records.
create table contacts.contact_tags (
    tag_id                  text not null,
    tenant_id               text not null references identity.organizations(organization_id),
    name                    text not null,
    slug                    text not null,
    created_by_principal_id text,
    created_at              timestamptz not null default now(),
    primary key (tag_id),
    unique (tag_id, tenant_id),
    unique (tenant_id, slug)
);

create table contacts.contact_tag_assignments (
    tenant_id                text not null references identity.organizations(organization_id),
    tag_id                   text not null,
    contact_id               text not null,
    assigned_by_principal_id text,
    assigned_at              timestamptz not null default now(),
    primary key (tag_id, contact_id),
    foreign key (tag_id, tenant_id)
        references contacts.contact_tags(tag_id, tenant_id)
        on delete cascade,
    foreign key (contact_id, tenant_id)
        references contacts.contacts(contact_id, tenant_id)
        on delete cascade,
    unique (tenant_id, tag_id, contact_id)
);

create index contact_tag_assignments_by_contact
    on contacts.contact_tag_assignments(tenant_id, contact_id);

-- A dynamic segment: the rule, and a hash of the rule.
--
-- The hash is not decoration. A campaign envelope binds a rule hash alongside
-- its cohort snapshot (KTD7), so "the audience rule changed after you
-- authorised it" is a comparison rather than an argument. It is stored beside
-- the definition so the two cannot be written apart.
--
-- `scope_branch_id` bounds the rule before it is ever evaluated. A segment
-- that could reach the whole account would let anyone who may create a
-- segment read past their own branch permissions, which is the leak this
-- whole file exists to prevent.
create table contacts.contact_segments (
    segment_id              text not null,
    tenant_id               text not null references identity.organizations(organization_id),
    scope_branch_id         text not null,
    name                    text not null,
    slug                    text not null,
    definition              jsonb not null default '{}',
    rule_hash               text not null,
    created_by_principal_id text,
    created_at              timestamptz not null default now(),
    updated_at              timestamptz not null default now(),
    primary key (segment_id),
    unique (segment_id, tenant_id),
    foreign key (scope_branch_id, tenant_id)
        references contacts.branches(branch_id, tenant_id),
    unique (tenant_id, slug)
);

-- Forced row-level security, the same block every table in this system uses.
--
-- These tables answer "who may see whom" and "who is in this campaign", which
-- is the pair an attacker would want before the directory itself. FORCE, and
-- not merely enable, for the same reason 0017 gives: the migration runner's
-- role owns them.
do $$
declare table_name text;
begin
    foreach table_name in array array[
        'branch_permissions', 'contact_lists', 'contact_list_members',
        'contact_tags', 'contact_tag_assignments', 'contact_segments'
    ] loop
        execute format('alter table contacts.%I enable row level security', table_name);
        execute format('alter table contacts.%I force row level security', table_name);
        execute format(
            'create policy %I on contacts.%I using '
            '(tenant_id = current_setting(''app.current_org_id'', true)) '
            'with check (tenant_id = current_setting(''app.current_org_id'', true))',
            table_name || '_tenant_isolation', table_name
        );
    end loop;
end $$;
