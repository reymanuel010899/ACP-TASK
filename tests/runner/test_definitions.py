"""U1: agent-definition store + create/list/get/delete + persistence."""

import pytest

from runner.app import RunnerService, build_service
from runner.store import DefinitionStore
from runner.supervisor import Supervisor


@pytest.fixture
def service(tmp_path):
    store = DefinitionStore(str(tmp_path))
    sup = Supervisor("http://127.0.0.1:8090", "http://127.0.0.1:8080",
                     mint_key_fn=lambda: "testkey")
    return RunnerService(store, sup)


def _valid_payload(**over):
    base = {
        "name": "DevOps Agent",
        "template": "terraform-provider",
        "capabilities": ["terraform.generate"],
        "list_price": 9,
        "min_price": 8,
    }
    base.update(over)
    return base


def test_create_returns_stopped_definition(service):
    status, body = service.create_agent(_valid_payload())
    assert status == 200, body
    assert body["id"].startswith("agt_")
    assert body["name"] == "DevOps Agent"
    assert body["template"] == "terraform-provider"
    assert body["runtime"]["status"] == "stopped"
    # internal paths are not leaked to the API
    assert "keys_dir" not in body and "log_path" not in body


def test_list_and_get_roundtrip(service):
    _, created = service.create_agent(_valid_payload(name="A"))
    status, listed = service.list_agents()
    assert status == 200
    assert any(a["id"] == created["id"] for a in listed["agents"])
    status, got = service.get_agent(created["id"])
    assert status == 200 and got["name"] == "A"


def test_get_missing_is_404(service):
    status, _ = service.get_agent("agt_nope")
    assert status == 404


def test_delete_removes_definition(service):
    _, created = service.create_agent(_valid_payload())
    status, _ = service.delete_agent(created["id"])
    assert status == 200
    assert service.get_agent(created["id"])[0] == 404


def test_unknown_template_is_422(service):
    status, _ = service.create_agent(_valid_payload(template="nope"))
    assert status == 422


def test_empty_capabilities_is_422(service):
    status, _ = service.create_agent(_valid_payload(capabilities=[]))
    assert status == 422


def test_min_price_above_list_is_422(service):
    status, _ = service.create_agent(_valid_payload(list_price=3, min_price=9))
    assert status == 422


def test_negative_price_is_422(service):
    status, _ = service.create_agent(_valid_payload(list_price=-1))
    assert status == 422


def test_definitions_reload_from_disk(tmp_path):
    svc1 = build_service("http://127.0.0.1:8090", "http://127.0.0.1:8080", str(tmp_path))
    _, created = svc1.create_agent(_valid_payload(name="Persisted"))
    # a fresh service pointed at the same data-dir reloads the definition
    svc2 = build_service("http://127.0.0.1:8090", "http://127.0.0.1:8080", str(tmp_path))
    status, got = svc2.get_agent(created["id"])
    assert status == 200 and got["name"] == "Persisted"
    assert got["runtime"]["status"] == "stopped"
