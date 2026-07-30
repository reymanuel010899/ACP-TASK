import pytest

from agents.orchestrator.workflow_broker_dispatcher import _matches_approved_template


def test_provider_output_cannot_change_static_recipient_or_add_fields():
    approved = {"to": "laura@example.com", "body": {"$ref": "read.output.summary"}}
    assert _matches_approved_template(approved, {"to": "laura@example.com", "body": "Resumen"})
    assert not _matches_approved_template(approved, {"to": "attacker@example.com", "body": "Resumen"})
    assert not _matches_approved_template(approved, {"to": "laura@example.com", "body": "Resumen", "bcc": "attacker@example.com"})


def test_production_store_fails_closed_without_workflow_kms(tmp_path, monkeypatch):
    from agents.orchestrator.workflow_repository import WorkflowRepository
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("TESSERA_WORKFLOW_KMS_KEY_ID", raising=False)
    with pytest.raises(RuntimeError, match="KMS_KEY_ID"):
        WorkflowRepository.from_environment(str(tmp_path / "workflow.sqlite3"), "service:test")
