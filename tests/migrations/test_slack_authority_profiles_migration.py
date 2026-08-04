from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "0015_slack_authority_profiles.sql"
)


def test_authority_profiles_separate_bot_user_and_admin_grants():
    sql = MIGRATION.read_text()
    flat = " ".join(sql.split())

    assert "create table orchestrator.slack_authority_profiles" in sql
    assert "'bot', 'user', 'enterprise_admin'" in sql
    # A personal profile without a subject cannot say who it acts as.
    assert "check (profile_kind = 'bot' or slack_subject_id is not null)" in flat
    assert "consent_owner_principal_id text not null" in sql
    # One grant per owner per kind, so a second consent replaces rather than
    # quietly accumulating parallel authority.
    assert (
        "unique ( tenant_id, connection_id, profile_kind, "
        "consent_owner_principal_id )"
    ) in flat
    assert "enabled boolean not null default false" in sql
    assert "drop table" not in sql.casefold()


def test_delegations_are_bound_to_audience_family_and_expiry():
    sql = MIGRATION.read_text()
    flat = " ".join(sql.split())

    assert "create table orchestrator.slack_authority_delegations" in sql
    for column in (
        "audience_principal_id text not null",
        "operation_family text not null",
        "purpose text not null",
        "expires_at timestamptz not null",
    ):
        assert column in sql
    assert "references orchestrator.slack_authority_profiles" in sql
    assert (
        "unique ( tenant_id, authority_profile_id, audience_principal_id, "
        "operation_family )"
    ) in flat


def test_both_tables_are_tenant_isolated():
    sql = MIGRATION.read_text()

    for table in ("slack_authority_profiles", "slack_authority_delegations"):
        assert "'%s'" % table in sql[sql.index("foreach table_name"):]
    assert "force row level security" in sql
    assert "app.current_org_id" in sql
