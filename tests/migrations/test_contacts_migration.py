from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[2] / "migrations" / "0017_contacts.sql"
)

TABLES = ("branches", "contacts", "contact_addresses")


def _sql():
    return MIGRATION.read_text()


def _flat():
    return " ".join(_sql().split())


def test_every_contacts_table_is_isolated_under_forced_row_level_security():
    sql = _sql()
    block = sql[sql.index("foreach table_name"):]

    for table in TABLES:
        assert "'%s'" % table in block
    assert "enable row level security" in sql
    # FORCE is the whole point: `enable` alone exempts the table owner, and
    # the migration runner's role owns these tables.
    assert "force row level security" in sql
    assert "app.current_org_id" in sql
    assert sql.count("force row level security") == 1
    assert "_tenant_isolation" in sql


def test_the_isolation_policy_binds_reads_and_writes_alike():
    flat = _flat()

    # A policy with only USING lets a tenant insert rows it can never read
    # back -- which is how one account's import lands in another's directory.
    assert "create policy %I on contacts.%I using" in flat
    assert flat.count(
        "(tenant_id = current_setting(''app.current_org_id'', true))"
    ) == 2
    assert "'with check (tenant_id = current_setting(" in flat


def test_a_branch_cannot_have_a_parent_in_another_account():
    flat = _flat()

    assert "create table contacts.branches" in flat
    assert "unique (branch_id, tenant_id, kind)" in flat
    # The parent reference carries the tenant, so a cross-tenant child does
    # not resolve -- with row-level security on or off.
    assert (
        "foreign key (parent_branch_id, tenant_id, parent_kind) references "
        "contacts.branches(branch_id, tenant_id, kind)"
    ) in flat


def test_the_hierarchy_holds_organizations_departments_and_nested_folders():
    flat = _flat()

    assert (
        "kind text not null check (kind in ('organization', 'department', "
        "'folder'))"
    ) in flat
    assert "check (kind <> 'organization' or parent_branch_id is null)" in flat
    assert "check (kind <> 'department' or parent_kind = 'organization')" in flat
    assert "check (kind <> 'folder' or parent_kind is not null)" in flat


def test_a_path_names_exactly_one_branch_and_ends_in_its_own_slug():
    flat = _flat()

    assert "unique (tenant_id, path)" in flat
    assert "check (path like '/%')" in flat
    # A move that reparents branches but forgets to rewrite their paths
    # cannot commit.
    assert "check (right(path, length(slug) + 1) = '/' || slug)" in flat
    assert "create unique index branches_sibling_slug" in flat
    # Two roots sharing a slug would slip past a plain unique constraint,
    # because null never conflicts with null.
    assert "create unique index branches_root_slug" in flat


def test_cyclic_ancestry_is_rejected_by_the_database_not_only_the_caller():
    sql = _sql()
    flat = _flat()

    assert "create function contacts.reject_cyclic_branch_move" in sql
    assert "raise exception 'move would create cyclic branch ancestry'" in flat
    assert "raise exception 'a branch cannot be its own parent'" in flat
    # A recursive walk over an already-cyclic graph is the thing that hangs.
    assert "raise exception 'branch ancestry exceeds the supported depth'" in flat
    assert (
        "create trigger branches_reject_cyclic_ancestry before insert or "
        "update of parent_branch_id on contacts.branches"
    ) in flat
    assert "check (parent_branch_id is null or parent_branch_id <> branch_id)" in flat


def test_a_contact_has_exactly_one_primary_tree_location():
    flat = _flat()

    assert "create table contacts.contacts" in flat
    # One not-null column, not a join table with a boolean, because the
    # cardinality is the claim.
    assert "primary_branch_id      text not null" in _sql()
    assert (
        "foreign key (primary_branch_id, tenant_id) references "
        "contacts.branches(branch_id, tenant_id)"
    ) in flat


def test_a_merged_contact_still_resolves_to_the_record_that_survived():
    flat = _flat()

    assert "check (status <> 'merged' or merged_into_contact_id is not null)" in flat
    assert (
        "check (merged_into_contact_id is null or merged_into_contact_id <> "
        "contact_id)"
    ) in flat
    assert (
        "foreign key (merged_into_contact_id, tenant_id) references "
        "contacts.contacts(contact_id, tenant_id)"
    ) in flat


def test_a_contact_carries_what_a_send_decision_needs_to_read():
    sql = _sql()

    # R10: how to address them, what language, what hour it is there, and
    # whether this record is still live.
    for column in (
        "display_name", "given_name", "family_name", "locale", "timezone",
        "company_name", "job_title", "status", "external_reference", "source",
    ):
        assert column in sql


def test_addresses_are_rows_so_consent_can_attach_to_one_of_them():
    sql = _sql()
    flat = _flat()

    assert "create table contacts.contact_addresses" in flat
    assert (
        "channel text not null check (channel in ('sms', 'whatsapp', "
        "'voice', 'email'))"
    ) in flat
    assert (
        "foreign key (contact_id, tenant_id) references "
        "contacts.contacts(contact_id, tenant_id)"
    ) in flat
    assert "create unique index contact_addresses_one_primary_per_channel" in flat
    # Verification is not consent. An address can be provably reachable and
    # still opted out, so the two never share a column.
    assert "verified_at        timestamptz" in sql


def test_two_accounts_may_each_hold_the_same_phone_number():
    flat = _flat()

    # Tenant-scoped, never global. A global unique key here would merge two
    # accounts' customers into one row.
    assert "unique (tenant_id, channel, address_normalized)" in flat
    assert "unique (channel, address_normalized)" not in flat
    # Within one account it still holds: one number, one canonical person.
    assert "address_normalized text not null" in flat


def test_every_table_exposes_a_tenant_carrying_key_for_the_next_unit():
    flat = _flat()

    # U6's consent, exclusion, activity, and suppression rows reference these,
    # so the tenant travels inside the foreign key rather than beside it.
    for key in (
        "unique (branch_id, tenant_id)",
        "unique (contact_id, tenant_id)",
        "unique (address_id, tenant_id)",
    ):
        assert key in flat


def test_every_table_anchors_its_tenant_to_a_real_organization():
    flat = _flat()

    # One per table. A tenant id that referenced nothing would let a typo
    # create a private account nobody administers.
    assert _flat().count(
        "references identity.organizations(organization_id)"
    ) == len(TABLES)


def test_the_migration_is_expand_only():
    sql = _sql().casefold()

    for statement in ("drop table", "drop column", "drop schema", "truncate"):
        assert statement not in sql
