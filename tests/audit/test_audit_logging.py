"""Tests for the central Audit & Compliance service (Phase B, unit U12).

Covers the audit service itself (append-only store + HTTP API), the
best-effort AuditClient, and the ecosystem integrations: Registry, Vault,
Task Marketplace, and Agent Marketplace emitting central audit entries.

All servers run on EPHEMERAL ports (port=0), never fixed ports.
"""

import re
import socket
import threading
import time
from datetime import datetime, timezone

import pytest
import requests

from agent_marketplace.app import make_server as make_agent_marketplace_server
from apps.marketplace.server.app import make_server as make_marketplace_server
from audit.app import make_server as make_audit_server
from audit.audit_store import AuditStore
from libs.audit_client import AuditClient, NullAuditClient
from registry.app import make_server as make_registry_server
from vault.app import make_server as make_vault_server

TIMEOUT = 5.0

RFC3339_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$"
)


def _start(server):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return thread


def _url(server):
    host, port = server.server_address[:2]
    return "http://%s:%d" % (host, port)


def _stop(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def _post_entry(audit_url, principal_id, activity_type, status="ok",
                resource_id=None, details=None):
    body = {
        "principal_id": principal_id,
        "activity_type": activity_type,
        "status": status,
    }
    if resource_id is not None:
        body["resource_id"] = resource_id
    if details is not None:
        body["details"] = details
    resp = requests.post(
        "%s/audit" % audit_url, json=body, timeout=TIMEOUT
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["entry"]


def _query(audit_url, **params):
    resp = requests.get(
        "%s/audit" % audit_url, params=params, timeout=TIMEOUT
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.fixture
def audit_server():
    server = make_audit_server(port=0)
    thread = _start(server)
    try:
        yield server
    finally:
        _stop(server, thread)


# ---------------------------------------------------------------------------
# 1-2. POST /audit: valid entries and validation
# ---------------------------------------------------------------------------


def test_post_valid_entry_assigns_id_and_rfc3339_timestamp(audit_server):
    url = _url(audit_server)
    entry = _post_entry(
        url, "user:alice", "credential.access", status="granted",
        resource_id="cred-1", details={"scope": "read"},
    )
    assert entry["entry_id"]
    assert RFC3339_RE.match(entry["timestamp"]), entry["timestamp"]
    # Timestamp must carry an explicit UTC offset (RFC 3339).
    parsed = datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    assert entry["principal_id"] == "user:alice"
    assert entry["activity_type"] == "credential.access"
    assert entry["status"] == "granted"
    assert entry["resource_id"] == "cred-1"
    assert entry["details"] == {"scope": "read"}

    # GET returns it.
    body = _query(url)
    assert body["total_matched"] == 1
    assert body["entries"][0]["entry_id"] == entry["entry_id"]


def test_post_missing_required_fields_is_422(audit_server):
    url = _url(audit_server)
    valid = {
        "principal_id": "user:alice",
        "activity_type": "work.bid",
        "status": "ok",
    }
    for field in ("principal_id", "activity_type", "status"):
        body = dict(valid)
        del body[field]
        resp = requests.post("%s/audit" % url, json=body, timeout=TIMEOUT)
        assert resp.status_code == 422, (field, resp.text)
        # Empty string is as bad as missing.
        body = dict(valid)
        body[field] = ""
        resp = requests.post("%s/audit" % url, json=body, timeout=TIMEOUT)
        assert resp.status_code == 422, (field, resp.text)


# ---------------------------------------------------------------------------
# 3. Immutability: no update/delete over HTTP nor on the store
# ---------------------------------------------------------------------------


def test_put_and_delete_are_405_immutable(audit_server):
    url = _url(audit_server)
    entry = _post_entry(url, "user:alice", "work.bid")

    resp = requests.put(
        "%s/audit/%s" % (url, entry["entry_id"]),
        json={"status": "tampered"},
        timeout=TIMEOUT,
    )
    assert resp.status_code == 405

    resp = requests.delete(
        "%s/audit/%s" % (url, entry["entry_id"]), timeout=TIMEOUT
    )
    assert resp.status_code == 405

    # Bare collection too.
    assert requests.put(
        "%s/audit" % url, json={}, timeout=TIMEOUT
    ).status_code == 405
    assert requests.delete("%s/audit" % url, timeout=TIMEOUT).status_code == 405

    # Entry untouched.
    body = _query(url)
    assert body["total_matched"] == 1
    assert body["entries"][0]["status"] == "ok"


def test_audit_store_has_no_update_or_delete_api():
    store = AuditStore()
    for name in (
        "delete", "remove", "update", "pop", "clear",
        "delete_entry", "update_entry", "remove_entry", "truncate",
    ):
        assert not hasattr(store, name), (
            "AuditStore must be append-only; found %r" % name
        )


# ---------------------------------------------------------------------------
# 4-6. Querying: filters, ordering, limit, total_matched
# ---------------------------------------------------------------------------


def test_query_by_principal_newest_first(audit_server):
    url = _url(audit_server)
    e1 = _post_entry(url, "user:alice", "work.bid")
    _post_entry(url, "user:bob", "work.bid")
    e3 = _post_entry(url, "user:alice", "work.complete")

    body = _query(url, principal_id="user:alice")
    assert body["total_matched"] == 2
    ids = [e["entry_id"] for e in body["entries"]]
    assert ids == [e3["entry_id"], e1["entry_id"]]  # newest first
    assert all(e["principal_id"] == "user:alice" for e in body["entries"])


def test_query_filters(audit_server):
    url = _url(audit_server)
    e1 = _post_entry(url, "user:alice", "work.bid", resource_id="task-1")
    time.sleep(0.02)
    mid = datetime.now(timezone.utc).isoformat()
    time.sleep(0.02)
    e2 = _post_entry(url, "user:alice", "work.complete", resource_id="task-2")
    e3 = _post_entry(url, "user:bob", "work.bid", resource_id="task-2")

    # By activity_type.
    body = _query(url, activity_type="work.bid")
    assert body["total_matched"] == 2
    assert {e["entry_id"] for e in body["entries"]} == {
        e1["entry_id"], e3["entry_id"]
    }

    # By resource_id.
    body = _query(url, resource_id="task-2")
    assert body["total_matched"] == 2
    assert {e["entry_id"] for e in body["entries"]} == {
        e2["entry_id"], e3["entry_id"]
    }

    # By time range.
    body = _query(url, start_time=mid)
    assert {e["entry_id"] for e in body["entries"]} == {
        e2["entry_id"], e3["entry_id"]
    }
    body = _query(url, end_time=mid)
    assert {e["entry_id"] for e in body["entries"]} == {e1["entry_id"]}
    body = _query(url, start_time=e1["timestamp"], end_time=mid)
    assert {e["entry_id"] for e in body["entries"]} == {e1["entry_id"]}

    # Combined filters.
    body = _query(
        url, principal_id="user:alice", activity_type="work.bid"
    )
    assert body["total_matched"] == 1
    assert body["entries"][0]["entry_id"] == e1["entry_id"]
    body = _query(
        url, activity_type="work.bid", resource_id="task-2"
    )
    assert body["total_matched"] == 1
    assert body["entries"][0]["entry_id"] == e3["entry_id"]


def test_query_limit_and_total_matched(audit_server):
    url = _url(audit_server)
    for i in range(5):
        _post_entry(url, "user:alice", "work.bid", resource_id="task-%d" % i)

    body = _query(url, limit=2)
    assert len(body["entries"]) == 2
    assert body["total_matched"] == 5
    # Newest first even under limit.
    assert body["entries"][0]["resource_id"] == "task-4"
    assert body["entries"][1]["resource_id"] == "task-3"

    # Invalid limit -> 400.
    resp = requests.get(
        "%s/audit" % url, params={"limit": "nope"}, timeout=TIMEOUT
    )
    assert resp.status_code == 400
    resp = requests.get(
        "%s/audit" % url, params={"limit": "0"}, timeout=TIMEOUT
    )
    assert resp.status_code == 400


def test_healthz(audit_server):
    resp = requests.get("%s/healthz" % _url(audit_server), timeout=TIMEOUT)
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# 7. Best-effort client: a dead audit service never raises
# ---------------------------------------------------------------------------


def test_audit_client_log_against_dead_service_never_raises():
    # Grab a port that is guaranteed closed.
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    dead_port = sock.getsockname()[1]
    sock.close()

    client = AuditClient("http://127.0.0.1:%d" % dead_port, timeout=0.5)
    # Must swallow the connection error silently.
    result = client.log(
        "user:alice", "work.bid", resource_id="task-1",
        status="ok", details={"k": "v"},
    )
    assert result is None


def test_null_audit_client_is_a_silent_noop():
    client = NullAuditClient()
    assert client.log("user:alice", "work.bid") is None
    body = client.query(principal_id="user:alice")
    assert body == {"entries": [], "total_matched": 0}


# ---------------------------------------------------------------------------
# 8. Integration: Registry emits central audit entries
# ---------------------------------------------------------------------------


def test_registry_emits_agent_register_and_reputation_update(audit_server):
    audit_url = _url(audit_server)
    registry = make_registry_server(port=0, audit_url=audit_url)
    thread = _start(registry)
    try:
        registry_url = _url(registry)
        resp = requests.post(
            "%s/agents/register" % registry_url,
            json={
                "principal_id": "agent:auditor-1",
                "created_by": "user:owner",
                "agent_card": {
                    "name": "auditor-1",
                    "description": "test agent",
                    "capabilities": ["marketplace.tasks"],
                },
            },
            timeout=TIMEOUT,
        )
        assert resp.status_code == 200, resp.text

        resp = requests.post(
            "%s/users/agent:auditor-1/reputation" % registry_url,
            json={
                "task_id": "task-1",
                "verified": True,
                "capability_id": "marketplace.tasks",
            },
            timeout=TIMEOUT,
        )
        assert resp.status_code == 200, resp.text

        body = _query(
            audit_url, principal_id="agent:auditor-1",
            activity_type="agent.register",
        )
        assert body["total_matched"] == 1

        body = _query(
            audit_url, principal_id="agent:auditor-1",
            activity_type="reputation.update",
        )
        assert body["total_matched"] == 1
        assert body["entries"][0]["resource_id"] == "task-1"
    finally:
        _stop(registry, thread)


def test_registry_emits_principal_app_register_and_permission_check(
    audit_server,
):
    audit_url = _url(audit_server)
    registry = make_registry_server(port=0, audit_url=audit_url)
    thread = _start(registry)
    try:
        registry_url = _url(registry)
        # principal.register
        resp = requests.post(
            "%s/auth/register" % registry_url,
            json={"principal_id": "user:carol"},
            timeout=TIMEOUT,
        )
        assert resp.status_code == 200, resp.text

        # app.register
        resp = requests.post(
            "%s/apps/register" % registry_url,
            json={
                "app_id": "some-app",
                "app_endpoint": "http://127.0.0.1:1",
                "p2p_endpoint": "http://127.0.0.1:1",
                "capabilities": ["some.cap"],
            },
            timeout=TIMEOUT,
        )
        assert resp.status_code == 200, resp.text

        # permission.check: one allowed, one denied
        resp = requests.post(
            "%s/p2p/permissions/check" % registry_url,
            json={
                "requester_principal_id": "user:carol",
                "target_app_id": "some-app",
                "capability_id": "some.cap",
            },
            timeout=TIMEOUT,
        )
        assert resp.status_code == 200 and resp.json()["allowed"] is True
        resp = requests.post(
            "%s/p2p/permissions/check" % registry_url,
            json={
                "requester_principal_id": "user:nobody",
                "target_app_id": "some-app",
                "capability_id": "some.cap",
            },
            timeout=TIMEOUT,
        )
        assert resp.status_code == 200 and resp.json()["allowed"] is False

        body = _query(audit_url, activity_type="principal.register")
        assert body["total_matched"] == 1
        assert body["entries"][0]["principal_id"] == "user:carol"

        body = _query(audit_url, activity_type="app.register")
        assert body["total_matched"] == 1
        assert body["entries"][0]["principal_id"] == "some-app"

        body = _query(audit_url, activity_type="permission.check")
        assert body["total_matched"] == 2
        allowed_flags = sorted(
            e["details"]["allowed"] for e in body["entries"]
        )
        assert allowed_flags == [False, True]
    finally:
        _stop(registry, thread)


# ---------------------------------------------------------------------------
# 9. Integration: Vault emits central entries AND keeps its local audit
# ---------------------------------------------------------------------------


def test_vault_emits_credential_access_granted_and_denied(audit_server):
    audit_url = _url(audit_server)
    vault = make_vault_server(port=0, audit_url=audit_url)
    thread = _start(vault)
    try:
        vault_url = _url(vault)
        resp = requests.post(
            "%s/credentials" % vault_url,
            json={
                "name": "api key",
                "credential_type": "api_key",
                "encrypted_data": "Y2lwaGVydGV4dA==",
                "nonce": "bm9uY2U=",
                "user_principal_id": "user:owner",
            },
            timeout=TIMEOUT,
        )
        assert resp.status_code == 200, resp.text
        credential_id = resp.json()["credential_id"]

        resp = requests.post(
            "%s/credentials/%s/grants" % (vault_url, credential_id),
            json={
                "agent_principal_id": "agent:worker",
                "scope": "read",
                "granted_by": "user:owner",
            },
            timeout=TIMEOUT,
        )
        assert resp.status_code == 200, resp.text

        # Granted access.
        resp = requests.post(
            "%s/credentials/%s/access" % (vault_url, credential_id),
            json={"agent_principal_id": "agent:worker"},
            timeout=TIMEOUT,
        )
        assert resp.status_code == 200 and resp.json()["access_granted"]

        # Denied access.
        resp = requests.post(
            "%s/credentials/%s/access" % (vault_url, credential_id),
            json={"agent_principal_id": "agent:intruder"},
            timeout=TIMEOUT,
        )
        assert resp.status_code == 403

        body = _query(
            audit_url, activity_type="credential.access",
            resource_id=credential_id,
        )
        assert body["total_matched"] == 2
        by_status = {e["status"]: e for e in body["entries"]}
        assert by_status["granted"]["principal_id"] == "agent:worker"
        assert by_status["denied"]["principal_id"] == "agent:intruder"

        # credential.grant went central too.
        body = _query(audit_url, activity_type="credential.grant")
        assert body["total_matched"] == 1

        # Local vault audit (U7 contract) still works alongside.
        resp = requests.get(
            "%s/audit" % vault_url,
            params={"principal_id": "agent:worker"},
            timeout=TIMEOUT,
        )
        assert resp.status_code == 200
        local = resp.json()["entries"]
        assert any(
            e["action"] == "access" and e["status"] == "granted"
            for e in local
        )
    finally:
        _stop(vault, thread)


# ---------------------------------------------------------------------------
# 10. Integration: full marketplace agent cycle emits work.* entries
# ---------------------------------------------------------------------------


def test_marketplace_agent_cycle_emits_work_entries(audit_server):
    audit_url = _url(audit_server)
    marketplace = make_marketplace_server(port=0, audit_url=audit_url)
    thread = _start(marketplace)
    try:
        mp_url = _url(marketplace)
        author = "user:author"
        agent = "agent:worker-9"

        resp = requests.post(
            "%s/api/tasks" % mp_url,
            json={"principal_id": author, "description": "translate a doc"},
            timeout=TIMEOUT,
        )
        assert resp.status_code == 200, resp.text
        task_id = resp.json()["task"]["id"]

        # Agent bids over P2P.
        resp = requests.post(
            "%s/p2p/request" % mp_url,
            json={
                "requester_principal_id": agent,
                "request_type": "submit.work_bid",
                "capability_id": "marketplace.tasks",
                "input": {"task_id": task_id, "proposed_terms": "1 day"},
            },
            timeout=TIMEOUT,
        )
        assert resp.status_code == 200, resp.text
        bid_id = resp.json()["result"]["bid"]["bid_id"]

        # Author accepts the bid.
        resp = requests.post(
            "%s/api/tasks/%s/bids/%s/accept" % (mp_url, task_id, bid_id),
            json={"author_principal": author},
            timeout=TIMEOUT,
        )
        assert resp.status_code == 200, resp.text

        # Agent delivers.
        resp = requests.post(
            "%s/p2p/request" % mp_url,
            json={
                "requester_principal_id": agent,
                "request_type": "submit.work_result",
                "capability_id": "marketplace.tasks",
                "input": {"task_id": task_id, "result_summary": "done"},
            },
            timeout=TIMEOUT,
        )
        assert resp.status_code == 200, resp.text

        # Author completes.
        resp = requests.post(
            "%s/api/negotiations/%s/complete" % (mp_url, task_id),
            json={"author_principal": author, "outcome": "great work"},
            timeout=TIMEOUT,
        )
        assert resp.status_code == 200, resp.text

        for activity_type in ("work.bid", "work.submit", "work.complete"):
            body = _query(
                audit_url, principal_id=agent, activity_type=activity_type,
            )
            assert body["total_matched"] == 1, activity_type
            assert body["entries"][0]["resource_id"] == task_id
    finally:
        _stop(marketplace, thread)


# ---------------------------------------------------------------------------
# 11. Integration: agent marketplace hire + revoke + rate emit entries
# ---------------------------------------------------------------------------


def test_agent_marketplace_hire_revoke_rate_emit_entries(audit_server):
    audit_url = _url(audit_server)
    registry = make_registry_server(port=0)
    registry_thread = _start(registry)
    agent_mp = make_agent_marketplace_server(
        port=0, registry_url=_url(registry), audit_url=audit_url
    )
    agent_mp_thread = _start(agent_mp)
    try:
        resp = requests.post(
            "%s/agents/register" % _url(registry),
            json={
                "principal_id": "agent:hireling",
                "created_by": "user:owner",
                "agent_card": {
                    "name": "hireling",
                    "description": "for hire",
                    "capabilities": ["marketplace.tasks"],
                },
            },
            timeout=TIMEOUT,
        )
        assert resp.status_code == 200, resp.text

        amp_url = _url(agent_mp)
        resp = requests.post(
            "%s/marketplace/hiring-grants" % amp_url,
            json={
                "agent_principal_id": "agent:hireling",
                "user_principal_id": "user:employer",
                "scoped_capabilities": ["marketplace.tasks"],
            },
            timeout=TIMEOUT,
        )
        assert resp.status_code == 200, resp.text
        grant_id = resp.json()["grant"]["grant_id"]

        resp = requests.post(
            "%s/marketplace/ratings" % amp_url,
            json={
                "agent_principal_id": "agent:hireling",
                "user_principal_id": "user:employer",
                "rating": 5,
            },
            timeout=TIMEOUT,
        )
        assert resp.status_code == 200, resp.text

        resp = requests.delete(
            "%s/marketplace/hiring-grants/%s" % (amp_url, grant_id),
            json={"user_principal_id": "user:employer"},
            timeout=TIMEOUT,
        )
        assert resp.status_code == 200, resp.text

        for activity_type in ("agent.hire", "agent.rate", "agent.revoke"):
            body = _query(audit_url, activity_type=activity_type)
            assert body["total_matched"] == 1, activity_type
            entry = body["entries"][0]
            assert entry["principal_id"] == "user:employer"
            assert (
                entry["details"]["agent_principal_id"] == "agent:hireling"
            )
    finally:
        _stop(agent_mp, agent_mp_thread)
        _stop(registry, registry_thread)


# ---------------------------------------------------------------------------
# 12. No audit_url configured -> NullAuditClient, zero behavior change
# ---------------------------------------------------------------------------


def test_services_without_audit_url_use_null_client_and_work_as_before():
    marketplace = make_marketplace_server(port=0)
    thread = _start(marketplace)
    try:
        assert isinstance(
            marketplace.service.audit_client, NullAuditClient
        )
        mp_url = _url(marketplace)
        resp = requests.post(
            "%s/api/tasks" % mp_url,
            json={"principal_id": "user:solo", "description": "a task"},
            timeout=TIMEOUT,
        )
        assert resp.status_code == 200, resp.text
    finally:
        _stop(marketplace, thread)

    vault = make_vault_server(port=0)
    vthread = _start(vault)
    try:
        assert isinstance(
            vault.service.audit_client, NullAuditClient
        )
        resp = requests.get("%s/healthz" % _url(vault), timeout=TIMEOUT)
        assert resp.status_code == 200
    finally:
        _stop(vault, vthread)

    registry = make_registry_server(port=0)
    rthread = _start(registry)
    try:
        assert isinstance(
            registry.service.audit_client, NullAuditClient
        )
        resp = requests.post(
            "%s/auth/register" % _url(registry),
            json={"principal_id": "user:quiet"},
            timeout=TIMEOUT,
        )
        assert resp.status_code == 200, resp.text
    finally:
        _stop(registry, rthread)


# ---------------------------------------------------------------------------
# 13. Concurrency: appends from many threads are all recorded
# ---------------------------------------------------------------------------


def test_concurrent_store_appends_all_recorded():
    store = AuditStore()
    n_threads, per_thread = 8, 25

    def worker(i):
        for j in range(per_thread):
            store.append({
                "principal_id": "user:t%d" % i,
                "activity_type": "stress.test",
                "status": "ok",
                "resource_id": "r%d-%d" % (i, j),
            })

    threads = [
        threading.Thread(target=worker, args=(i,)) for i in range(n_threads)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    entries = store.query(limit=n_threads * per_thread + 10)
    assert len(entries) == n_threads * per_thread
    entry_ids = {e["entry_id"] for e in entries}
    assert len(entry_ids) == n_threads * per_thread


def test_concurrent_http_appends_all_recorded(audit_server):
    url = _url(audit_server)
    n_threads, per_thread = 5, 8
    errors = []

    def worker(i):
        try:
            for j in range(per_thread):
                _post_entry(url, "user:c%d" % i, "stress.http")
        except Exception as exc:  # pragma: no cover - failure reporting
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=(i,)) for i in range(n_threads)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    body = _query(url, activity_type="stress.http", limit=100)
    assert body["total_matched"] == n_threads * per_thread
