from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SQL = (ROOT / "migrations/0030_operational_state_core.sql").read_text(
    encoding="utf-8"
).lower()


def test_core_operational_tables_cover_sqlite_gaps():
    for table in (
        "identity.web_sessions",
        "identity.consumed_identity_proofs",
        "integrations.oauth_transactions",
        "orchestrator.action_proposals",
        "orchestrator.capability_leases",
        "orchestrator.dispatch_records",
        "operational_migration.store_authority",
        "operational_migration.import_runs",
        "operational_migration.import_checkpoints",
        "operational_migration.import_quarantine",
    ):
        assert f"create table {table}" in SQL


def test_tenant_tables_use_strict_request_binding_and_force_rls():
    assert "app.tenant_id" not in SQL
    assert "app.current_org_id" in SQL
    assert "nullif(current_setting" in SQL
    assert "force row level security" in SQL


def test_global_authentication_replay_tables_are_explicitly_not_tenant_owned():
    web_sessions = SQL.split("create table identity.web_sessions", 1)[1].split(
        ");", 1
    )[0]
    consumed = SQL.split(
        "create table identity.consumed_identity_proofs", 1
    )[1].split(");", 1)[0]

    assert "tenant_id" not in web_sessions
    assert "tenant_id" not in consumed
    assert "proof_hash text primary key" in consumed


def test_concurrency_and_idempotency_constraints_are_present():
    assert "unique (tenant_id, idempotency_key)" in SQL
    assert "capability_one_active_workflow_lease" in SQL
    assert "primary key (tenant_id, dispatch_key)" in SQL
    assert "unique (tenant_id, effect_id)" in SQL
    assert "unique (tenant_id, domain_family, import_generation)" in SQL


def test_authority_lifecycle_is_one_way_capable():
    for state in (
        "sqlite_authoritative",
        "importing",
        "ready",
        "postgres_authoritative",
    ):
        assert state in SQL

