"""What the consent migration has to say in SQL rather than in Python.

The repository can be replaced; these constraints are the floor that holds
when it is. Text assertions, matching the other migration tests in this
directory -- the schema is the artefact under test, not a live database.
"""

from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "migrations" / "0018_contact_consent.sql"
)

TABLES = (
    "consent_records",
    "address_suppressions",
    "address_usability_decisions",
    "provider_reachability_events",
)


def _sql():
    return MIGRATION.read_text()


def _flat():
    return " ".join(_sql().split())


def test_every_consent_table_is_isolated_under_forced_row_level_security():
    sql = _sql()
    block = sql[sql.index("foreach table_name"):]

    for table in TABLES:
        assert "'%s'" % table in block
    # FORCE, not merely enable: the migration runner's role owns these tables
    # and would otherwise read every account's opt-outs.
    assert "force row level security" in sql
    assert "app.current_org_id" in sql
    assert "_tenant_isolation" in sql


def test_the_isolation_policy_binds_reads_and_writes_alike():
    flat = _flat()

    assert "create policy %I on contacts.%I using" in flat
    assert "'with check (tenant_id = current_setting(" in flat


def test_the_three_axes_are_three_tables_and_never_one_column():
    flat = _flat()

    for table in TABLES:
        assert "create table contacts.%s" % table in flat
    # The collapse this unit exists to prevent, asserted as an absence: no
    # combined field anywhere in the schema.
    lowered = flat.casefold()
    for collapsed in (
        "consent_state ", "contactable", "is_opted_in", "consent_status ",
    ):
        assert collapsed not in lowered


def test_consent_is_scoped_per_address_channel_and_purpose():
    flat = _flat()

    assert (
        "purpose text not null check (purpose in ( 'marketing', 'utility', "
        "'authentication', 'transactional', 'service' ))"
    ) in flat
    assert (
        "state text not null check (state in ( 'unknown', 'pending_evidence', "
        "'granted', 'expired', 'withdrawn' ))"
    ) in flat
    # Address, tenant, and owning contact travel together, so a consent
    # record cannot be filed against a person who does not hold the address.
    assert (
        "foreign key (address_id, tenant_id, contact_id) references "
        "contacts.contact_addresses(address_id, tenant_id, contact_id)"
    ) in flat
    assert (
        "alter table contacts.contact_addresses add constraint "
        "contact_addresses_contact_key unique (address_id, tenant_id, "
        "contact_id)"
    ) in flat


def test_suppression_is_not_scoped_by_purpose():
    sql = _sql()
    suppressions = sql[
        sql.index("create table contacts.address_suppressions"):
        sql.index("create index address_suppressions_current")
    ]

    # The line between the two axes: a marketing unsubscribe is about one
    # purpose, a hard bounce is about the address. Purpose scoping here would
    # let an unsubscribe swallow a password reset.
    assert "purpose" not in suppressions
    assert "sender_id" in suppressions
    for state in (
        "suppressed_by_optout", "suppressed_by_bounce", "suppressed_by_admin",
        "suppressed_by_provider",
    ):
        assert state in suppressions


def test_a_permissive_transition_cannot_be_written_without_a_human_decider():
    flat = _flat()

    # KTD13 as a check constraint rather than as a code path somebody can
    # route around. Once per axis that has a permissive direction: consent,
    # suppression, and address usability.
    assert flat.count(
        "check ( transition_kind <> 'permissive' or ( "
        "decided_by_principal_id is not null"
    ) == 3
    assert (
        "check ( (state = 'granted' and transition_kind = 'permissive') or "
        "(state in ('withdrawn', 'expired') and transition_kind = "
        "'restrictive') or (state in ('unknown', 'pending_evidence') and "
        "transition_kind = 'proposed') )"
    ) in flat
    # Un-suppressing is the narrower gate: administrator, and only human.
    assert "decided_by_authority = 'administer'" in flat
    assert "check ((state = 'none') = (transition_kind = 'permissive'))" in flat


def test_a_grant_carries_the_evidence_it_would_be_defended_with():
    flat = _flat()

    for field in (
        "capture_method", "captured_at", "captured_at_local",
        "capture_timezone", "jurisdiction", "disclosure_text",
        "disclosure_hash", "default_unchecked", "legal_basis", "source",
        "actor_principal_id", "expires_at",
    ):
        assert field in flat
    assert (
        "check ( state <> 'granted' or ( capture_method is not null and "
        "captured_at is not null and captured_at_local is not null and "
        "jurisdiction is not null and disclosure_text is not null and "
        "legal_basis is not null ) )"
    ) in flat
    # A pre-ticked box is not consent, and where there was a form the proof
    # is mandatory rather than optional.
    assert (
        "check (state <> 'granted' or default_unchecked is distinct from false)"
    ) in flat
    assert (
        "check ( state <> 'granted' or capture_method not in ('web_form', "
        "'embedded_form', 'import_form') or default_unchecked is true )"
    ) in flat


def test_revocation_scope_can_widen_without_a_migration():
    flat = _flat()

    # All three values legal from day one, so the cross-topic duty is a
    # configuration change and never a schema change written under a deadline.
    assert (
        "revocation_scope text not null default 'program' check "
        "(revocation_scope in ( 'program', 'topic', 'cross_topic' ))"
    ) in flat


def test_the_audit_outlives_the_message_body():
    flat = _flat()

    assert "retained_until timestamptz not null" in flat
    assert "content_expires_at timestamptz" in flat
    assert "content_purged_at timestamptz" in flat
    # Not a convention a purge job is trusted to honour: a row whose audit
    # expires before its body cannot be written at all.
    assert (
        "check (content_expires_at is null or retained_until > "
        "content_expires_at)"
    ) in flat
    assert (
        "check (content_purged_at is null or inbound_message_body is null)"
    ) in flat


def test_the_ledgers_are_append_only_with_exactly_one_narrow_exception():
    sql = _sql()
    flat = _flat()

    for table in (
        "address_suppressions", "address_usability_decisions",
        "provider_reachability_events",
    ):
        assert (
            "create trigger %s_append_only before update or delete on "
            "contacts.%s" % (table, table)
        ) in flat
    assert "orchestrator.reject_append_only_mutation()" in sql

    # The consent ledger's one hole, shaped so nothing else fits through it.
    assert "create function contacts.reject_consent_record_mutation" in sql
    assert "raise exception 'contacts.consent_records is append-only'" in flat
    assert (
        "raise exception 'a consent content purge must redact the message body'"
    ) in flat
    guard = sql[sql.index("reject_consent_record_mutation"):]
    for protected in (
        "state", "transition_kind", "disclosure_text", "legal_basis",
        "decided_by_principal_id", "decided_by_authority", "retained_until",
        "recorded_at", "actor_kind", "jurisdiction", "captured_at",
    ):
        assert "new.%s is distinct from old.%s" % (protected, protected) in guard


def test_which_row_is_current_never_depends_on_random_bits():
    sql = _sql()
    flat = _flat()

    # All four ledgers are read as "newest row wins", and `recorded_at` ties
    # routinely -- one inbound STOP writes a withdrawal per purpose under a
    # single `now()`. The tiebreak cannot be the identifier: these keys are
    # ULIDs, ordered only across millisecond boundaries, random inside one.
    assert flat.count(
        "ledger_sequence bigint generated always as identity"
    ) == len(TABLES)
    # `generated always`, not `bigserial`. A caller who could supply the value
    # could change which row reads as current without updating a row, which is
    # exactly what the append-only triggers exist to make impossible.
    assert "ledger_sequence bigserial" not in flat.casefold()

    # The read order, carried into the indexes that serve it.
    for ordering in (
        "tenant_id, address_id, channel, purpose, recorded_at desc, "
        "ledger_sequence desc",
        "tenant_id, address_id, channel, recorded_at desc, ledger_sequence desc",
        "tenant_id, address_id, recorded_at desc, ledger_sequence desc",
    ):
        assert ordering in flat

    # And frozen by the same guard that holds the rest of the consent row: the
    # order of the ledger is part of the decision, not metadata beside it.
    guard = sql[sql.index("reject_consent_record_mutation"):]
    assert "new.ledger_sequence is distinct from old.ledger_sequence" in guard


def test_provider_reachability_holds_no_consent_and_no_suppression():
    sql = _sql()
    table = sql[
        sql.index("create table contacts.provider_reachability_events"):
        sql.index("create index provider_reachability_current")
    ]

    # A START restores carriage and nothing else. If this table could express
    # consent, a subscriber reopening a support thread would resume a campaign.
    assert "consent" not in table
    assert "suppress" not in table
    assert "check (state in ('reachable', 'blocked_by_provider'))" in \
        " ".join(table.split())
    assert "provider_keyword" in table


def test_every_table_anchors_its_tenant_and_carries_a_tenant_scoped_key():
    flat = _flat()

    assert flat.count(
        "references identity.organizations(organization_id)"
    ) == len(TABLES)
    for key in (
        "unique (consent_record_id, tenant_id)",
        "unique (suppression_id, tenant_id)",
        "unique (usability_decision_id, tenant_id)",
        "unique (reachability_event_id, tenant_id)",
    ):
        assert key in flat
    for reference in (
        "references contacts.contact_addresses(address_id, tenant_id)",
        "references contacts.contacts(contact_id, tenant_id)",
    ):
        assert reference in flat


def test_the_migration_is_expand_only():
    sql = _sql().casefold()

    for statement in ("drop table", "drop column", "drop schema", "truncate"):
        assert statement not in sql
