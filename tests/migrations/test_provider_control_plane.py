from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "0016_provider_control_plane.sql"
)

TABLES = (
    "provider_accounts",
    "provider_account_families",
    "provider_senders",
    "provider_templates",
    "provider_derived_scopes",
    "tenant_control_plane",
)


def _sql():
    return MIGRATION.read_text()


def _flat():
    return " ".join(_sql().split())


def test_an_account_holds_authority_only_while_it_is_verified():
    sql = _sql()
    flat = _flat()

    assert "create table integrations.provider_accounts" in sql
    assert "provider_account_id text not null" in sql
    assert "'verified'" in sql and "'unverified'" in sql
    # Fail-closed: an account that could not be checked is unavailable, not
    # assumed to still hold what it last held.
    assert "'suspended'" in sql and "'unavailable'" in sql
    assert "default 'unavailable'" in sql
    assert "check (status <> 'verified' or verified_at is not null)" in flat
    # Two connections onto one provider account would let one tenant's disable
    # leave the other tenant's dispatch untouched.
    assert "unique (provider, provider_account_id)" in flat


def test_the_secret_never_lands_in_the_control_plane():
    sql = _sql().casefold()

    for column in ("auth_token", "credential_version", "access_token"):
        assert column not in sql


def test_families_and_senders_are_independently_disableable():
    sql = _sql()
    flat = _flat()

    assert "create table integrations.provider_account_families" in sql
    assert "create table integrations.provider_senders" in sql
    # Both land off. Turning either on is a deliberate act.
    assert flat.count("enabled boolean not null default false") == 2
    assert "disabled_at timestamptz," in flat
    assert "disabled_by_principal_id text" in flat


def test_the_emergency_stop_is_account_wide_and_not_per_connection():
    sql = _sql()

    assert "create table integrations.tenant_control_plane" in sql
    # Keyed by the tenant alone. Hanging a stop off one provider's connection
    # would leave every other provider running through a halt the operator
    # believed was total.
    assert "tenant_id                text primary key" in sql
    assert "connection_id" not in sql[sql.index("tenant_control_plane"):]


def test_a_stop_must_name_who_ordered_it():
    flat = _flat()

    assert (
        "check (not stopped or stopped_by_principal_id is not null)" in flat
    )


def test_the_stop_record_outlives_the_stop():
    sql = _sql()

    # An operator asks "when was this account stopped, by whom, and why"
    # after the fact, so the resume writes alongside the stop rather than
    # erasing it.
    for column in (
        "stop_reason", "stopped_at", "stopped_by_principal_id",
        "resumed_at", "resumed_by_principal_id",
    ):
        assert column in sql


def test_derived_scopes_record_what_they_were_derived_from():
    sql = _sql()
    flat = _flat()

    assert "create table integrations.provider_derived_scopes" in sql
    assert "dimension      text not null" in sql
    assert "source_id      text not null" in sql
    assert (
        "check (dimension in ('family', 'sender', 'geo', 'template'))" in flat
    )


def test_every_child_row_carries_its_tenant_into_its_foreign_key():
    flat = _flat()

    # The connection key gains the tenant so every composite key below can
    # carry it, rather than joining back through an untenanted primary key.
    assert (
        "add constraint integration_connections_tenant_key "
        "unique (connection_id, tenant_id)"
    ) in flat
    assert flat.count(
        "foreign key (connection_id, tenant_id) references "
        "integrations.provider_accounts(connection_id, tenant_id)"
    ) == 4
    # A sender's family must exist on the same connection and tenant.
    assert (
        "foreign key (connection_id, tenant_id, family) references "
        "integrations.provider_account_families( connection_id, tenant_id, "
        "family )"
    ) in flat


def test_every_table_is_tenant_isolated_under_forced_row_level_security():
    sql = _sql()
    block = sql[sql.index("foreach table_name"):]

    for table in TABLES:
        assert "'%s'" % table in block
    assert "enable row level security" in sql
    assert "force row level security" in sql
    assert "app.current_org_id" in sql


def test_the_migration_is_expand_only():
    sql = _sql().casefold()

    for statement in ("drop table", "drop column", "drop schema", "truncate"):
        assert statement not in sql
