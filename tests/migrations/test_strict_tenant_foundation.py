"""Static contract tests for the forward-only tenant isolation correction."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "migrations" / "0029_strict_tenant_foundation.sql"


def _sql() -> str:
    return MIGRATION.read_text(encoding="utf-8").lower()


def test_forward_migration_replaces_every_legacy_tenant_policy():
    sql = _sql()

    assert "app.tenant_id" not in sql
    assert "app.current_org_id" in sql
    for table in (
        "marketplace.tasks",
        "audit.audit_log",
        "campaign.campaigns",
        "campaign.campaign_cohort",
        "campaign.campaign_effects",
        "campaign.campaign_audit",
        "campaign.throughput_limits",
        "voice.transfer_routes",
        "voice.unfiled_activity",
        "voice.transfer_work_items",
    ):
        assert f"drop policy" in sql and f"on {table}" in sql


def test_private_agent_ownership_is_tenant_scoped_but_cards_remain_public():
    sql = _sql()

    assert "create table registry.agent_ownership" in sql
    assert "organization_id text not null" in sql
    assert "alter table registry.agent_ownership enable row level security" in sql
    assert "alter table registry.agent_ownership force row level security" in sql
    assert "drop policy if exists agents_org_isolation on registry.agents" in sql
    assert "disable row level security" in sql


def test_quarantined_rows_are_not_deleted_or_made_globally_visible():
    sql = _sql()

    assert "or organization_id is null" not in sql
    assert "delete from marketplace.tasks" not in sql
    assert "delete from audit.audit_log" not in sql


def test_audit_backfill_temporarily_lifts_and_restores_append_only_rule():
    sql = _sql()

    drop_at = sql.index("drop rule audit_log_no_update")
    update_at = sql.index("update audit.audit_log")
    restore_at = sql.index("create rule audit_log_no_update")
    assert drop_at < update_at < restore_at


def test_backfill_temporarily_lifts_and_restores_force_rls():
    sql = _sql()

    for table, update_statement in (
        ("marketplace.tasks", "update marketplace.tasks"),
        ("audit.audit_log", "update audit.audit_log"),
    ):
        lift_at = sql.index(f"alter table {table} no force row level security")
        update_at = sql.index(update_statement)
        restore_at = sql.index(f"alter table {table} force row level security")
        assert lift_at < update_at < restore_at
