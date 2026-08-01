from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "0013_general_slack_foundations.sql"
)


def test_general_slack_foundations_are_expand_only_and_tenant_guarded():
    sql = MIGRATION.read_text()

    for table in (
        "operation_instances",
        "effect_instances",
        "policy_decisions",
        "workflow_outbox",
        "projection_watermarks",
    ):
        assert "create table orchestrator.%s" % table in sql
        assert "'%s'" % table in sql[sql.index("foreach table_name") :]

    assert "unique (tenant_id, dedupe_key)" in sql
    assert "unique (tenant_id, aggregate_type, aggregate_id, aggregate_version)" in sql
    assert "foreign key (operation_instance_id, tenant_id)" in sql
    assert "foreign key (effect_instance_id, tenant_id)" in sql
    assert "force row level security" in sql
    assert "drop table" not in sql.lower()
    assert "alter table orchestrator.workflow_" not in sql.lower()


def test_domain_records_are_append_only_but_delivery_state_can_advance():
    sql = MIGRATION.read_text()

    for trigger in (
        "operation_instances_append_only",
        "effect_instances_append_only",
        "policy_decisions_append_only",
    ):
        assert "create trigger %s" % trigger in sql
    assert "workflow_outbox_append_only" not in sql
    assert "projection_watermarks_append_only" not in sql
