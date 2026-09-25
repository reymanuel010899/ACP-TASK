"""What the import migration has to say in SQL rather than in Python.

Text assertions, matching the other migration tests here -- the schema is the
artefact under test, not a live database.

Only claims that survive the repository being rewritten are asserted at this
level, and for import there are three: a staged row that asserts consent
without evidence cannot be stored at all, a batch decision names the human who
took it, and neither table can be read across an account boundary. Everything
else about import is application behaviour and is tested against the code.
"""

from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "migrations" / "0020_contact_import.sql"
)

TABLES = ("contact_import_batches", "contact_import_rows")


def _sql():
    return MIGRATION.read_text()


def _flat():
    return " ".join(_sql().split())


def test_both_staging_tables_are_isolated_under_forced_row_level_security():
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


def test_a_row_asserting_consent_without_evidence_cannot_be_stored():
    flat = _flat()

    assert (
        "check ( not asserts_consent or ( capture_method is not null "
        "and captured_at is not null and captured_at_local is not null "
        "and jurisdiction is not null and disclosure_text is not null "
        "and legal_basis is not null and default_unchecked is not false ) )"
    ) in flat


def test_a_form_capture_needs_the_box_to_have_started_empty():
    flat = _flat()

    assert (
        "check ( not asserts_consent or capture_method not in "
        "('web_form', 'embedded_form', 'import_form') "
        "or default_unchecked is true )"
    ) in flat


def test_the_evidence_columns_are_the_ones_a_grant_requires():
    flat = _flat()

    # The same set `libs/contacts_consent.py` refuses a grant without. Named
    # here so the two cannot drift apart silently: an evidence field added to
    # the grant and forgotten here would let an import assert it and lose it.
    for column in (
        "capture_method text",
        "captured_at timestamptz",
        "captured_at_local text",
        "capture_timezone text",
        "jurisdiction text",
        "disclosure_text text",
        "disclosure_hash text",
        "default_unchecked boolean",
        "legal_basis text",
    ):
        assert column in flat


def test_only_a_human_can_be_recorded_as_deciding_an_import():
    flat = _flat()

    assert flat.count(
        "check (decided_by_actor_kind is null or decided_by_actor_kind = 'human')"
    ) == 2


def test_a_batch_that_left_staging_names_who_decided_it():
    flat = _flat()

    assert (
        "check ( state = 'staged' or ( decided_by_principal_id is not null "
        "and decided_by_actor_kind is not null and decided_at is not null ) )"
    ) in flat
    assert (
        "check ( state = 'staged' or ( decided_by_principal_id is not null "
        "and decided_by_actor_kind is not null ) )"
    ) in flat


def test_every_reference_carries_the_tenant_so_matching_stops_at_the_account():
    flat = _flat()

    # The dedupe reads: a staged row names the contact it matched and the
    # record it produced. Each is a composite key, so neither can point at
    # another account -- which is what makes "an import cannot dedupe against
    # another account's contacts" structural rather than a predicate somebody
    # has to remember.
    for reference in (
        "foreign key (target_branch_id, tenant_id) "
        "references contacts.branches(branch_id, tenant_id)",
        "foreign key (batch_id, tenant_id) "
        "references contacts.contact_import_batches(batch_id, tenant_id)",
        "foreign key (matched_contact_id, tenant_id) "
        "references contacts.contacts(contact_id, tenant_id)",
        "foreign key (matched_branch_id, tenant_id) "
        "references contacts.branches(branch_id, tenant_id)",
        "foreign key (applied_contact_id, tenant_id) "
        "references contacts.contacts(contact_id, tenant_id)",
        "foreign key (applied_address_id, tenant_id) "
        "references contacts.contact_addresses(address_id, tenant_id)",
    ):
        assert reference in flat


def test_a_staged_row_is_classified_and_the_three_answers_are_fixed():
    flat = _flat()

    assert (
        "classification text not null check (classification in ( 'new', "
        "'duplicate', 'collision' ))"
    ) in flat


def test_an_applied_row_says_which_record_it_produced():
    flat = _flat()

    assert (
        "check ( state <> 'applied' or classification = 'duplicate' "
        "or applied_contact_id is not null )"
    ) in flat


def test_the_batch_records_how_a_national_number_was_read():
    flat = _flat()

    # Without it, '8095550100' in an applied batch is unattributable: the same
    # digits are a different person under a different calling code.
    assert "default_calling_code text" in flat


def test_a_row_keeps_both_the_written_form_and_the_canonical_one():
    flat = _flat()

    assert "address text not null, address_canonical text not null" in flat


def test_the_dedupe_read_is_indexed_by_canonical_form_within_one_account():
    flat = _flat()

    assert (
        "create index contact_import_rows_by_canonical on "
        "contacts.contact_import_rows(tenant_id, channel, address_canonical)"
    ) in flat
