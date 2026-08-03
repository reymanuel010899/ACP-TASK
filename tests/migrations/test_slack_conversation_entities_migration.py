from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "0014_slack_conversation_entities.sql"
)


def test_slack_conversation_entities_are_versioned_and_tenant_guarded():
    sql = MIGRATION.read_text()

    assert "add column state_version bigint not null default 1" in sql
    for table in (
        "concierge_turns",
        "slack_conversation_entities",
        "slack_resolver_runs",
        "concierge_outcome_events",
    ):
        assert "create table orchestrator.%s" % table in sql
        assert "'%s'" % table in sql[sql.index("foreach table_name") :]

    assert "unique (conversation_id, tenant_id, principal_id, turn_version)" in sql
    assert "concierge_turns_one_active_base" in sql
    assert "where status = 'started'" in sql
    assert "provider_entity_id text not null" in sql
    assert (
        "conversation_id, entity_kind, connection_id, provider_entity_id, "
        "entity_version"
    ) in " ".join(sql.split())
    assert "primary key (conversation_id, tenant_id, principal_id, client_turn_id)" in sql
    assert sql.count(
        "references orchestrator.concierge_conversations("
    ) >= 4
    assert "force row level security" in sql
    assert "drop table" not in sql.casefold()


def test_outcome_events_are_append_only_and_resolvers_are_resumable():
    sql = MIGRATION.read_text()

    assert "concierge_outcome_events_append_only" in sql
    assert "slack_resolver_runs_append_only" not in sql
    assert "cursor_json jsonb not null default '{}'" in sql
    assert "budget_json jsonb not null default '{}'" in sql
    assert "check (status in (" in sql
    assert "'pending', 'running', 'waiting_retry', 'completed', 'failed', 'cancelled'" in sql
