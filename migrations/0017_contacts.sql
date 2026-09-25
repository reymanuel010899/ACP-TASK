-- The canonical contact record and the account-owned tree it lives in.
-- Expand-only.
--
-- Everything else in this system stores work: runs, revisions, effects,
-- receipts. This stores people -- their names, their phone numbers, the
-- language they read in. A forgotten predicate anywhere else returns somebody
-- else's workflow id. A forgotten predicate here returns somebody else's
-- personal data to a stranger, and no later gate catches it.
--
-- So isolation is not an application concern that the database happens to
-- mirror. It is the database's job, enforced three ways that all have to fail
-- together before anything leaks:
--
--   1. Forced row-level security on every table, keyed on
--      `app.current_org_id`. FORCE is not optional -- a table owner bypasses
--      its own policies without it, and the migration runner's role owns
--      these tables.
--   2. Tenant-carrying composite foreign keys. Every child names its parent
--      as `(parent_id, tenant_id)`, never as `parent_id` alone, so a row
--      whose parent belongs to another account cannot be written at all.
--      This holds even for a superuser session with RLS switched off.
--   3. Uniqueness scoped to the tenant, never global. Two accounts holding
--      the same phone number is the normal case, not a conflict, and each
--      keeps its own canonical record of that person.
--
-- Consent is deliberately absent. It attaches to an address, not to a person
-- -- one person can hold a work mobile they have opted into and a personal
-- one they have not -- and it is three independent axes rather than one enum,
-- which U6 models. What this migration owes U6 is the anchor: every table
-- below carries `(id, tenant_id)` as a unique key so U6's consent, exclusion,
-- activity, and suppression rows can point at an address or a contact with
-- the tenant travelling inside the foreign key.

create schema if not exists contacts;

-- The tree. One shape holds all three levels because "freely nested
-- subfolders" (R8) means depth is not knowable in advance, and three tables
-- with three move paths would give a cycle three places to hide.
--
-- `path` is the materialised slug path -- '/acme/sales/emea'. It is what
-- makes navigation by path a single indexed lookup instead of a recursive
-- descent per segment, and what makes "everything under this branch" a
-- prefix scan, which is how a search bounded to authorised branches (R8, U7)
-- stays one query.
create table contacts.branches (
    branch_id        text not null,
    tenant_id        text not null references identity.organizations(organization_id),
    parent_branch_id text,
    -- Carried as a column, not derived, so the parent's kind can be enforced
    -- by the foreign key below rather than by a trigger that a bulk load can
    -- be talked out of running.
    parent_kind      text,
    kind             text not null check (kind in ('organization', 'department', 'folder')),
    name             text not null,
    slug             text not null,
    path             text not null,
    depth            integer not null check (depth >= 0),
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now(),
    primary key (branch_id),
    -- The tenant-carrying keys. Everything that points at a branch points at
    -- one of these, so the tenant travels inside the reference.
    unique (branch_id, tenant_id),
    unique (branch_id, tenant_id, kind),
    -- A child's parent must be in the same tenant. Not "should be" -- the
    -- reference does not resolve otherwise.
    foreign key (parent_branch_id, tenant_id, parent_kind)
        references contacts.branches(branch_id, tenant_id, kind),
    -- Path navigation must be unambiguous, or '/acme/sales' names two places.
    unique (tenant_id, path),
    -- A branch is its own trivial cycle. The trigger below catches the
    -- longer ones; this catches the one-hop case without a query.
    check (parent_branch_id is null or parent_branch_id <> branch_id),
    check ((parent_branch_id is null) = (parent_kind is null)),
    -- An organization is a root, a department hangs off an organization, and
    -- a folder nests inside anything at all. Enforced structurally because
    -- the layout is what a branch permission (U7) is granted over.
    check (kind <> 'organization' or parent_branch_id is null),
    check (kind <> 'department' or parent_kind = 'organization'),
    check (kind <> 'folder' or parent_kind is not null),
    -- A root sits at depth zero and nothing else does.
    check ((parent_branch_id is null) = (depth = 0)),
    -- The path always ends in this branch's own slug, so a move that
    -- rewrites parents but forgets to rewrite paths cannot commit.
    check (path like '/%'),
    check (right(path, length(slug) + 1) = '/' || slug)
);

-- Siblings cannot share a slug, or the path above would not be unique. Split
-- in two because a null parent does not conflict with another null parent
-- under a plain unique constraint, which would let two roots share a slug.
create unique index branches_sibling_slug
    on contacts.branches(tenant_id, parent_branch_id, slug)
    where parent_branch_id is not null;
create unique index branches_root_slug
    on contacts.branches(tenant_id, slug)
    where parent_branch_id is null;

create index branches_children
    on contacts.branches(tenant_id, parent_branch_id);
create index branches_subtree
    on contacts.branches(tenant_id, path text_pattern_ops);

-- The cycle guard. A move that reparents a branch under its own descendant
-- detaches that whole subtree from every root: it stays readable by id and
-- becomes unreachable by path, which is the worst of both -- the data is
-- still there and no navigation finds it.
--
-- Walked iteratively rather than with a recursive CTE because a recursive CTE
-- over an already-cyclic graph is the thing that hangs; the depth guard exits
-- on corruption instead of spinning.
create function contacts.reject_cyclic_branch_move()
returns trigger language plpgsql as $$
declare
    ancestor_id text := new.parent_branch_id;
    steps integer := 0;
begin
    if new.parent_branch_id is null then
        return new;
    end if;
    if new.parent_branch_id = new.branch_id then
        raise exception 'a branch cannot be its own parent';
    end if;
    while ancestor_id is not null loop
        steps := steps + 1;
        if steps > 128 then
            raise exception 'branch ancestry exceeds the supported depth';
        end if;
        select parent_branch_id into ancestor_id
          from contacts.branches
         where branch_id = ancestor_id
           and tenant_id = new.tenant_id;
        if ancestor_id = new.branch_id then
            raise exception 'move would create cyclic branch ancestry';
        end if;
    end loop;
    return new;
end;
$$;

create trigger branches_reject_cyclic_ancestry
before insert or update of parent_branch_id on contacts.branches
for each row execute function contacts.reject_cyclic_branch_move();

-- One row per person, per account (R9). Not one row per person per list, per
-- import, or per channel -- those all produce a directory where "have we
-- already messaged them" has several answers.
--
-- `primary_branch_id` is a single not-null column on purpose. "Exactly one
-- primary tree location" is a cardinality claim, and a join table with a
-- boolean flag makes it a claim the schema cannot keep. Additional
-- placements, if U7 needs them, are a separate secondary relation; the
-- primary stays here where it cannot be duplicated.
--
-- The R10 fields are the ones a send decision reads: how to address someone,
-- what language to write in, what hour it is where they are, and whether this
-- record is still the live one.
create table contacts.contacts (
    contact_id             text not null,
    tenant_id              text not null references identity.organizations(organization_id),
    primary_branch_id      text not null,
    display_name           text not null,
    given_name             text,
    family_name            text,
    -- BCP 47 where known. Null means unknown, which is a different fact from
    -- "English", and a template picker must be able to tell them apart.
    locale                 text,
    -- IANA zone where known. Quiet hours (R25) are meaningless without it,
    -- and guessing from a dialling code is how a campaign calls someone at
    -- four in the morning.
    timezone               text,
    -- Where they work and what they do. Read by a human reviewing a proposed
    -- send, not by the dispatcher.
    company_name           text,
    job_title              text,
    -- 'active', or a record that must never be picked as a send target.
    -- 'merged' points at whichever record won the merge, so an identifier
    -- captured before the merge still resolves to the survivor rather than
    -- to a dead end.
    status                 text not null default 'active'
                               check (status in ('active', 'archived', 'merged')),
    merged_into_contact_id text,
    -- The id this record carried in whatever system it was imported from,
    -- so a re-import updates the person rather than duplicating them.
    external_reference     text,
    source                 text not null default 'manual',
    created_at             timestamptz not null default now(),
    updated_at             timestamptz not null default now(),
    primary key (contact_id),
    unique (contact_id, tenant_id),
    foreign key (primary_branch_id, tenant_id)
        references contacts.branches(branch_id, tenant_id),
    foreign key (merged_into_contact_id, tenant_id)
        references contacts.contacts(contact_id, tenant_id),
    check (status <> 'merged' or merged_into_contact_id is not null),
    check (merged_into_contact_id is null
           or merged_into_contact_id <> contact_id)
);

create index contacts_by_branch
    on contacts.contacts(tenant_id, primary_branch_id);
create index contacts_active
    on contacts.contacts(tenant_id, display_name)
    where status = 'active';
create unique index contacts_external_reference
    on contacts.contacts(tenant_id, source, external_reference)
    where external_reference is not null;

-- Addresses are rows, not columns.
--
-- Columns would mean one phone number and one email per person, and would
-- put consent on the person: opting out of marketing on a personal mobile
-- would silently opt out the work line too, or fail to. A person holds
-- several addresses, each with its own consent state, its own delivery
-- history, and its own reason to be unusable. U6 hangs all three off
-- `(address_id, tenant_id)`.
create table contacts.contact_addresses (
    address_id         text not null,
    tenant_id          text not null references identity.organizations(organization_id),
    contact_id         text not null,
    channel            text not null
                           check (channel in ('sms', 'whatsapp', 'voice', 'email')),
    -- As the account entered it, kept for display and for evidence.
    address            text not null,
    -- E.164 for telephony, lowercased for email. Uniqueness and lookup run
    -- on this, so '+1 809 555 0100' and '+18095550100' are one address.
    address_normalized text not null,
    label              text,
    is_primary         boolean not null default false,
    -- When the account last proved this address reaches this person.
    -- Distinct from consent: a verified address may still be opted out.
    verified_at        timestamptz,
    created_at         timestamptz not null default now(),
    updated_at         timestamptz not null default now(),
    primary key (address_id),
    unique (address_id, tenant_id),
    foreign key (contact_id, tenant_id)
        references contacts.contacts(contact_id, tenant_id)
        on delete cascade,
    -- Scoped to the tenant, and only to the tenant. Two accounts each holding
    -- +18095550100 is the ordinary case; making this globally unique would
    -- merge two accounts' customers into one record. Within one account it
    -- does hold: a number resolves to exactly one canonical person (R9).
    unique (tenant_id, channel, address_normalized)
);

-- One address per channel may be the one we reach for by default.
create unique index contact_addresses_one_primary_per_channel
    on contacts.contact_addresses(tenant_id, contact_id, channel)
    where is_primary;
create index contact_addresses_by_contact
    on contacts.contact_addresses(tenant_id, contact_id);
create index contact_addresses_lookup
    on contacts.contact_addresses(tenant_id, channel, address_normalized);

-- Forced row-level security, the same block every table in this system uses.
--
-- FORCE is the load-bearing word. `enable` alone exempts the table owner, and
-- the role that ran this migration owns these tables, so a pooled connection
-- checked out by a service that shares that role would read every account's
-- contacts with the policies sitting there looking correct.
do $$
declare table_name text;
begin
    foreach table_name in array array[
        'branches', 'contacts', 'contact_addresses'
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
