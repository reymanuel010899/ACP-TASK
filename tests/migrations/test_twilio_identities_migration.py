from pathlib import Path


SQL = Path("migrations/0021_twilio_identities.sql").read_text()


def test_identity_ownership_is_global_current_and_time_versioned():
    assert "unique index twilio_one_current_identity_owner" in SQL.lower()
    assert "where valid_until is null" in SQL.lower()
    assert "valid_from" in SQL and "valid_until" in SQL


def test_identity_rows_are_forced_rls_and_tenant_carried():
    lowered = SQL.lower()
    assert "force row level security" in lowered
    assert "current_setting('app.current_org_id', true)" in lowered
    assert "foreign key (connection_id, tenant_id)" in lowered
