-- Bulk import, held in staging until a human decides. Expand-only.
--
-- R12 says contacts may be added manually or imported, and that a change to
-- identity, destination, consent or permissions needs an authorized human
-- decision before it becomes usable. An import is the one path where those two
-- sentences pull hardest against each other: a file of ten thousand rows is
-- exactly the moment somebody wants to skip the decision, and exactly the
-- moment skipping it does the most damage.
--
-- So a file never lands in the directory. It lands here.
--
-- **Staging is a real table, not a request body.** The classification of a row
-- -- new, duplicate, or a collision with somebody who already exists -- is
-- computed once, written down, and reviewed against what was written. If the
-- classification lived only in the response of the upload call, the reviewer
-- would be approving a summary of a file nobody can produce again, and a
-- second upload of the same file would silently reclassify.
--
-- **A row that asserts consent without evidence cannot be stored at all.**
-- This is the check constraint at the bottom of `contact_import_rows`, and it
-- is the mechanism that stops a purchased list becoming an authorized
-- audience. Enforcing it only in Python would mean the guarantee lasts until
-- somebody adds a second write path -- a backfill script, an admin tool, a
-- later unit -- and the row that gets in that way is indistinguishable from a
-- lawfully captured one afterwards. `asserts_consent` is a claim; the evidence
-- columns are what make it defensible; the constraint is what keeps them
-- travelling together.
--
-- Note what the constraint does *not* do: it never lets a staged row grant
-- anything. Applying a batch writes through `contacts.consent_records` and
-- `contacts.address_usability_decisions` (0018) like every other decision, so
-- there is exactly one place consent is granted and exactly one place an
-- address becomes usable. This table only carries the evidence to that place.
--
-- **Both tables are tenant-bound and forced.** R7 names import as a surface
-- that must not leak, and staging is the worst of the three to leak: it holds
-- destinations in the form they were written, before anybody has decided they
-- may be held at all. Every reference below is a composite key carrying the
-- tenant, so a batch cannot target another account's branch and a row cannot
-- match against another account's contact -- dedupe stops at the account
-- boundary by construction rather than by predicate.

-- One upload: who staged it, where it is going, and what came out of the scan.
--
-- The counts are stored rather than derived because they are what a reviewer
-- authorizes. A count recomputed at review time is a count of whatever the
-- table says now, which is not necessarily the file anybody looked at.
create table contacts.contact_import_batches (
    batch_id                text not null,
    tenant_id               text not null references identity.organizations(organization_id),
    -- Every row in this batch is destined for one branch, and the importer's
    -- edit authority is resolved against it before anything is staged. A batch
    -- that could scatter rows across the tree would need an authority check
    -- per row, which is the check that gets dropped.
    target_branch_id        text not null,
    source_name             text,
    -- The calling code a national number is read against, fixed per batch.
    -- Kept because '8095550100' is not a destination on its own: the same nine
    -- digits are a different person under a different code, so how the batch
    -- was interpreted has to survive the batch.
    default_calling_code    text,
    state                   text not null
                                check (state in ('staged', 'applied', 'rejected')),
    row_count               integer not null default 0,
    new_count               integer not null default 0,
    duplicate_count         integer not null default 0,
    collision_count         integer not null default 0,
    staged_by_principal_id  text not null,
    staged_by_actor_kind    text not null
                                check (staged_by_actor_kind in (
                                    'human', 'agent', 'system', 'provider',
                                    'contact'
                                )),
    -- Null while staged. Once a batch is decided these name the human who
    -- decided it -- one act covering many rows is still one recorded act, and
    -- an unattributable batch decision is the shape a thousand-row mistake
    -- takes when nobody can say who authorized it.
    decided_by_principal_id text,
    decided_by_authority    text,
    decided_by_actor_kind   text
                                check (decided_by_actor_kind in (
                                    'human', 'agent', 'system', 'provider',
                                    'contact'
                                )),
    decided_at              timestamptz,
    reason                  text,
    created_at              timestamptz not null default now(),
    updated_at              timestamptz not null default now(),
    primary key (batch_id),
    unique (batch_id, tenant_id),
    foreign key (target_branch_id, tenant_id)
        references contacts.branches(branch_id, tenant_id),
    -- An agent may prepare an import; it may never be the one who decides it.
    check (decided_by_actor_kind is null or decided_by_actor_kind = 'human'),
    -- A decided batch names its decider. Nothing leaves 'staged' anonymously.
    check (
        state = 'staged' or (
            decided_by_principal_id is not null
            and decided_by_actor_kind is not null
            and decided_at is not null
        )
    )
);

create index contact_import_batches_by_branch
    on contacts.contact_import_batches(tenant_id, target_branch_id);

-- One staged row: the person as the file wrote them, the canonical form the
-- dedupe ran on, what the scan concluded, and the consent evidence if any.
--
-- `address` and `address_canonical` are both kept for the reason 0017 keeps
-- both: the canonical form is what uniqueness and matching run on, and the
-- written form is what a human checks when deciding whether this is really the
-- person in front of them. A reviewer shown only '+18095550100' cannot tell
-- that the file said '809-555-0100 ext 4'.
create table contacts.contact_import_rows (
    import_row_id           text not null,
    tenant_id               text not null references identity.organizations(organization_id),
    batch_id                text not null,
    row_number              integer not null,
    display_name            text not null,
    given_name              text,
    family_name             text,
    company_name            text,
    job_title               text,
    locale                  text,
    timezone                text,
    external_reference      text,
    channel                 text not null
                                check (channel in (
                                    'sms', 'whatsapp', 'voice', 'email'
                                )),
    address                 text not null,
    address_canonical       text not null,
    -- 'new'       -- nobody in this account holds this destination.
    -- 'duplicate' -- the same person, already here or written twice in the
    --                file. One canonical record, per R9; this row adds none.
    -- 'collision' -- the destination is held by somebody the importer did not
    --                mean to touch. A human decides; nothing merges on its own.
    classification          text not null
                                check (classification in (
                                    'new', 'duplicate', 'collision'
                                )),
    matched_contact_id      text,
    matched_branch_id       text,
    duplicate_of_row_id     text,
    -- The claim, and the evidence that makes it defensible. Separated because
    -- a row may carry a person without carrying permission to contact them:
    -- that row still imports, and its address stays unusable.
    asserts_consent         boolean not null default false,
    consent_purposes        text[],
    capture_method          text,
    captured_at             timestamptz,
    captured_at_local       text,
    capture_timezone        text,
    jurisdiction            text,
    disclosure_text         text,
    disclosure_hash         text,
    default_unchecked       boolean,
    legal_basis             text,
    consent_source          text,
    consent_expires_at      timestamptz,
    state                   text not null
                                check (state in ('staged', 'applied', 'rejected')),
    applied_contact_id      text,
    applied_address_id      text,
    decided_by_principal_id text,
    decided_by_authority    text,
    decided_by_actor_kind   text
                                check (decided_by_actor_kind in (
                                    'human', 'agent', 'system', 'provider',
                                    'contact'
                                )),
    decided_at              timestamptz,
    reason                  text,
    created_at              timestamptz not null default now(),
    updated_at              timestamptz not null default now(),
    primary key (import_row_id),
    unique (import_row_id, tenant_id),
    foreign key (batch_id, tenant_id)
        references contacts.contact_import_batches(batch_id, tenant_id)
        on delete cascade,
    -- The tenant travels inside every match. A staged row cannot name another
    -- account's contact, so an import cannot dedupe across the boundary and
    -- cannot learn that a destination is known somewhere else.
    foreign key (matched_contact_id, tenant_id)
        references contacts.contacts(contact_id, tenant_id),
    foreign key (matched_branch_id, tenant_id)
        references contacts.branches(branch_id, tenant_id),
    foreign key (applied_contact_id, tenant_id)
        references contacts.contacts(contact_id, tenant_id),
    foreign key (applied_address_id, tenant_id)
        references contacts.contact_addresses(address_id, tenant_id),
    unique (tenant_id, batch_id, row_number),
    -- Consent asserted without the evidence that defends it is not storable.
    -- Every field here is one 0018 requires of a grant, checked at the door so
    -- an unevidenced claim can never reach the ledger that would make it look
    -- like permission. `default_unchecked` is refused when explicitly false --
    -- a pre-ticked box is not consent -- and permitted as null only for
    -- captures that had no box at all.
    check (
        not asserts_consent or (
            capture_method is not null
            and captured_at is not null
            and captured_at_local is not null
            and jurisdiction is not null
            and disclosure_text is not null
            and legal_basis is not null
            and default_unchecked is not false
        )
    ),
    -- A form capture with no proof the box started empty is the exact shape a
    -- purchased list arrives in.
    check (
        not asserts_consent
        or capture_method not in ('web_form', 'embedded_form', 'import_form')
        or default_unchecked is true
    ),
    check (decided_by_actor_kind is null or decided_by_actor_kind = 'human'),
    check (
        state = 'staged' or (
            decided_by_principal_id is not null
            and decided_by_actor_kind is not null
        )
    ),
    -- A row that produced a live record says which one. Without this an
    -- applied batch cannot be reconciled against the directory it created.
    check (
        state <> 'applied'
        or classification = 'duplicate'
        or applied_contact_id is not null
    )
);

create index contact_import_rows_by_batch
    on contacts.contact_import_rows(tenant_id, batch_id, row_number);
-- The dedupe read: "is this destination already staged or already known", by
-- canonical form, inside one account.
create index contact_import_rows_by_canonical
    on contacts.contact_import_rows(tenant_id, channel, address_canonical);

-- Forced row-level security, the same block every table in this system uses.
--
-- FORCE and not merely ENABLE, for the reason 0017 gives: the migration
-- runner's role owns these tables, and an owner is exempt from a policy that
-- is only enabled. Staging is the table an attacker would want most -- it
-- holds destinations in the written form, before any decision has been taken
-- about whether they may be held.
do $$
declare table_name text;
begin
    foreach table_name in array array[
        'contact_import_batches', 'contact_import_rows'
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
