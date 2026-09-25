"""What the permissions migration has to say in SQL rather than in Python.

Text assertions, matching the other migration tests here -- the schema is the
artefact under test, not a live database. The two claims worth holding at this
level are the ones that survive the repository being rewritten: an authority
change is a human administrator's decision, and a membership row has nothing
in it that can drift from the canonical record.
"""

from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "migrations" / "0019_contact_permissions.sql"
)

TABLES = (
    "branch_permissions",
    "contact_lists",
    "contact_list_members",
    "contact_tags",
    "contact_tag_assignments",
    "contact_segments",
)


def _sql():
    return MIGRATION.read_text()


def _flat():
    return " ".join(_sql().split())


def test_every_permission_table_is_isolated_under_forced_row_level_security():
    sql = _sql()
    block = sql[sql.index("foreach table_name"):]

    for table in TABLES:
        assert "'%s'" % table in block
    assert "force row level security" in sql
    assert "app.current_org_id" in sql
    assert "_tenant_isolation" in sql


def test_the_isolation_policy_binds_reads_and_writes_alike():
    flat = _flat()

    assert "create policy %I on contacts.%I using" in flat
    assert "'with check (tenant_id = current_setting(" in flat


def test_the_four_dimensions_are_a_column_and_never_a_role():
    flat = _flat()

    assert (
        "dimension text not null check (dimension in ( 'view', 'edit', "
        "'administer', 'campaign_use' ))"
    ) in flat
    assert "effect text not null check (effect in ('grant', 'restrict'))" in flat
    # The collapse this unit exists to prevent, asserted as an absence: no
    # single field anywhere that would have to mean all four at once.
    lowered = flat.casefold()
    for collapsed in ("role text", "access_level", "permission_level"):
        assert collapsed not in lowered


def test_one_decision_per_principal_per_branch_per_dimension():
    flat = _flat()

    assert (
        "unique (tenant_id, branch_id, principal_id, dimension)" in flat
    )


def test_an_authority_change_names_a_human_administrator():
    flat = _flat()

    # R12 in a constraint: an agent may propose, a human decides.
    assert "check (decided_by_actor_kind = 'human')" in flat
    # R11's explicit restriction, and the same word 0018 requires to lift a
    # suppression. If either moves, the two systems stop agreeing about what
    # an administrator is.
    assert "check (decided_by_authority = 'administer')" in flat
    assert "decided_by_principal_id text not null" in flat


def test_permissions_and_groupings_reference_branches_through_the_tenant():
    flat = _flat()

    for table in ("branch_permissions", "contact_lists"):
        assert flat.index("create table contacts.%s" % table) > 0
    assert flat.count(
        "foreign key (branch_id, tenant_id) references "
        "contacts.branches(branch_id, tenant_id)"
    ) >= 2
    assert (
        "foreign key (scope_branch_id, tenant_id) references "
        "contacts.branches(branch_id, tenant_id)"
    ) in flat


def test_membership_rows_carry_identifiers_and_nothing_that_can_go_stale():
    sql = _sql()
    for table in ("contact_list_members", "contact_tag_assignments"):
        start = sql.index("create table contacts.%s" % table)
        body = sql[start:sql.index(");", start)]
        for copied in (
            "display_name", "given_name", "address", "locale", "timezone",
            "company_name",
        ):
            assert copied not in body
        assert "contact_id" in body
        # The tenant travels inside both references, so a membership cannot
        # join a list in one account to a person in another.
        assert (
            "foreign key (contact_id, tenant_id)\n        references "
            "contacts.contacts(contact_id, tenant_id)"
        ) in body


def test_a_segment_stores_its_rule_and_its_hash_together():
    flat = _flat()

    assert "definition jsonb not null default '{}'" in flat
    assert "rule_hash text not null" in flat
    # Never the result. A materialised cohort here would make "expansion
    # invalidates authorization" unfalsifiable.
    lowered = flat.casefold()
    assert "create table contacts.contact_segment_members" not in lowered


def test_the_masked_preview_gets_a_last_contacted_column_to_read():
    flat = _flat()

    assert (
        "alter table contacts.contact_addresses add column last_contacted_at "
        "timestamptz"
    ) in flat
