"""U3: process supervisor lifecycle/status/logs. U8: identity stability.

Uses a stub provider (``_stub_provider.py``) launched via a monkeypatched
``build_command`` so lifecycle/health/logs are exercised deterministically
without a live registry or the real provider.
"""

import os
import sys
import time

import pytest

from runner.store import DefinitionStore
from runner.app import RunnerService
from runner.supervisor import Supervisor

STUB = os.path.join(os.path.dirname(__file__), "_stub_provider.py")


def _stub_build(defn, port, api_key, reg, ver):
    return [sys.executable, STUB, "--port", str(port)]


def _crash_build(defn, port, api_key, reg, ver):
    return [sys.executable, "-c", "pass"]  # exits immediately


@pytest.fixture
def service(tmp_path):
    store = DefinitionStore(str(tmp_path))
    sup = Supervisor("http://127.0.0.1:8090", "http://127.0.0.1:8080",
                     mint_key_fn=lambda: "testkey")
    svc = RunnerService(store, sup)
    yield svc
    sup.shutdown_all()


def _make(service, name="A"):
    _, defn = service.create_agent({
        "name": name, "template": "terraform-provider",
        "capabilities": ["terraform.generate"], "list_price": 9, "min_price": 8,
    })
    return defn["id"]


def _wait_status(service, agent_id, want, timeout=8.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        _, body = service.get_agent(agent_id)
        if body["runtime"]["status"] == want:
            return body["runtime"]
        time.sleep(0.15)
    _, body = service.get_agent(agent_id)
    return body["runtime"]


def test_start_reaches_online_with_principal(service, monkeypatch):
    monkeypatch.setattr("runner.supervisor.build_command", _stub_build)
    agent_id = _make(service)
    status, body = service.start_agent(agent_id)
    assert status == 200, body
    rt = _wait_status(service, agent_id, "online")
    assert rt["status"] == "online"
    assert rt["url"].startswith("http://127.0.0.1:")
    assert rt["principal_id"] == "stub-principal-123"


def test_stop_terminates_and_clears_port(service, monkeypatch):
    monkeypatch.setattr("runner.supervisor.build_command", _stub_build)
    agent_id = _make(service)
    service.start_agent(agent_id)
    _wait_status(service, agent_id, "online")
    status, body = service.stop_agent(agent_id)
    assert status == 200
    assert body["runtime"]["status"] == "stopped"
    assert body["runtime"]["port"] is None


def test_crashed_process_is_error_not_online(service, monkeypatch):
    monkeypatch.setattr("runner.supervisor.build_command", _crash_build)
    agent_id = _make(service)
    service.start_agent(agent_id)
    rt = _wait_status(service, agent_id, "error")
    assert rt["status"] == "error"


def test_two_agents_get_distinct_ports(service, monkeypatch):
    monkeypatch.setattr("runner.supervisor.build_command", _stub_build)
    a = _make(service, "A")
    b = _make(service, "B")
    service.start_agent(a)
    service.start_agent(b)
    ra = _wait_status(service, a, "online")
    rb = _wait_status(service, b, "online")
    assert ra["port"] != rb["port"]


def test_start_is_idempotent_while_running(service, monkeypatch):
    monkeypatch.setattr("runner.supervisor.build_command", _stub_build)
    agent_id = _make(service)
    service.start_agent(agent_id)
    rt1 = _wait_status(service, agent_id, "online")
    _, again = service.start_agent(agent_id)
    assert again["runtime"]["pid"] == rt1["pid"]  # same process


def test_logs_capture_stub_stdout(service, monkeypatch):
    monkeypatch.setattr("runner.supervisor.build_command", _stub_build)
    agent_id = _make(service)
    service.start_agent(agent_id)
    _wait_status(service, agent_id, "online")
    status, body = service.logs(agent_id, tail=50)
    assert status == 200
    assert any("stub provider up" in ln for ln in body["logs"])


def test_restart_reuses_same_keys_dir(service, monkeypatch, tmp_path):
    monkeypatch.setattr("runner.supervisor.build_command", _stub_build)
    agent_id = _make(service)
    # keys_dir is stable per agent across restarts (identity coherence, KTD2)
    before = service.store.get(agent_id)["keys_dir"]
    service.start_agent(agent_id)
    _wait_status(service, agent_id, "online")
    service.restart_agent(agent_id)
    _wait_status(service, agent_id, "online")
    after = service.store.get(agent_id)["keys_dir"]
    assert before == after


# -- U8: the provider persists+reuses its ed25519 key in keys-dir -------------

def test_provider_keypair_is_stable_across_loads(tmp_path):
    from agents.provider.agent import load_or_create_keypair
    d = str(tmp_path / "keys")
    k1 = load_or_create_keypair(d)
    k2 = load_or_create_keypair(d)  # same dir -> same identity
    assert bytes(k1.verify_key) == bytes(k2.verify_key)
    k3 = load_or_create_keypair(str(tmp_path / "other"))  # new dir -> new identity
    assert bytes(k3.verify_key) != bytes(k1.verify_key)
