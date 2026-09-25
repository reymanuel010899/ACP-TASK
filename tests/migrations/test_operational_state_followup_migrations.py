from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _migration(name):
    return (ROOT / "migrations" / name).read_text().lower()


def test_dispatch_callback_is_preserved_before_provider_boundary():
    sql = _migration("0032_dispatch_callback_correlation.sql")
    assert "alter table orchestrator.dispatch_records" in sql
    assert "add column callback_token text" in sql


def test_task_conversations_are_tenant_bound_and_forced_through_rls():
    sql = _migration("0033_task_conversation_state.sql")
    assert "primary key (tenant_id, task_id)" in sql
    assert "unique (tenant_id, conversation_id)" in sql
    assert "enable row level security" in sql
    assert "force row level security" in sql
    assert "app.current_org_id" in sql


def test_workflow_runtime_contract_preserves_authorization_and_evidence():
    sql = _migration("0034_workflow_runtime_contract.sql")
    for field in (
        "authorization_mode", "credential_version", "uncounted_attempts",
        "reconcile_after", "reconcile_attempts", "receipt_json",
        "attestation_json",
    ):
        assert field in sql
    assert "create table orchestrator.workflow_campaign_bindings" in sql
    assert "force row level security" in sql
