"""Connect existing (BYO) agents: an externally hosted agent joins by URL.

The runner fetches its published card server-side, validates the trust
extension, registers it into the registry (mocked here), and thereafter only
health-checks its endpoint — it never launches it.
"""

import pytest

from runner.app import RunnerService
from runner.connect import ConnectError, inspect
from runner.store import DefinitionStore
from runner.supervisor import Supervisor

from tests.runner._card_server import _CardServer


@pytest.fixture
def service(tmp_path, monkeypatch):
    store = DefinitionStore(str(tmp_path))
    sup = Supervisor("http://127.0.0.1:8090", "http://127.0.0.1:8080",
                     mint_key_fn=lambda: "testkey")
    # don't touch a live registry in tests
    monkeypatch.setattr("runner.app.register_external", lambda *a, **k: None)
    return RunnerService(store, sup)


# -- card inspection ---------------------------------------------------------


def test_inspect_reads_name_capabilities_and_principal():
    with _CardServer() as srv:
        detected = inspect(srv.url)
    assert detected["name"] == "External Bot"
    assert detected["version"] == "1.2.3"
    assert detected["principal_id"] == srv.principal_id
    assert detected["capabilities"] == ["terraform.generate"]


def test_agent_that_signs_the_challenge_is_verified():
    """An agent that proves possession of its key is Verified — and keeps its
    own (proven) principal_id."""
    with _CardServer(prove=True) as srv:
        detected = inspect(srv.url)
    assert detected["trust_tier"] == "verified"
    assert detected["proof"] == "proven"
    assert detected["principal_id"] == srv.principal_id


def test_claimed_identity_that_cannot_sign_is_downgraded_to_basic():
    """Declaring the extension is not enough: an agent that will not sign the
    nonce cannot prove possession, so it drops to Basic and its unproven claim
    is discarded for an assigned id."""
    from runner.connect import UNVERIFIED_PREFIX

    with _CardServer(prove=False) as srv:
        detected = inspect(srv.url)
    assert detected["trust_tier"] == "basic"
    assert detected["proof"] == "unproven"
    assert detected["principal_id"].startswith(UNVERIFIED_PREFIX)


def test_copied_principal_id_cannot_pass_the_challenge():
    """The core protection: an agent that pastes someone else's principal_id can
    still sign with ITS key, but the key won't hash to the stolen id, so the
    binding check fails and it stays Basic."""
    with _CardServer(wrong_principal=True) as srv:
        detected = inspect(srv.url)
    assert detected["trust_tier"] == "basic"
    assert detected["proof"] == "unproven"


def test_plain_a2a_card_is_basic_tier_with_an_assigned_identity():
    """A plain A2A agent (no trust extension) still joins, as tier 'basic',
    with a marketplace-assigned identifier — never a keypair we hold."""
    from runner.connect import UNVERIFIED_PREFIX

    with _CardServer(with_trust=False) as srv:
        detected = inspect(srv.url)
        again = inspect(srv.url)
    assert detected["trust_tier"] == "basic"
    assert detected["principal_id"].startswith(UNVERIFIED_PREFIX)
    # stable: reconnecting the same endpoint reuses the same identifier
    assert detected["principal_id"] == again["principal_id"]


def test_basic_tier_publishes_an_attested_trust_extension(service, monkeypatch):
    """The registry requires the extension, so we add one — and the published
    card must say the identity was attested, not self-asserted."""
    published = {}
    monkeypatch.setattr(
        "runner.app.register_external",
        lambda registry, card, pid, key: published.update(card=card),
    )
    with _CardServer(with_trust=False) as srv:
        status, body = service.connect_agent({
            "endpoint_url": srv.url, "capabilities": ["data.analysis"],
        })
    assert status == 200, body
    assert body["trust_tier"] == "basic"
    ext = [e for e in published["card"]["capabilities"]["extensions"]
           if e["uri"].endswith("/trust/v1")][0]
    assert ext["params"]["self_asserted"] is False
    assert ext["params"]["attested_by"] == "marketplace"
    # discovery-only: it never opted into the negotiation vocabulary, so
    # requesters can filter it out of transactions from the registry alone
    assert ext["params"]["transactable"] is False


def test_verified_tier_keeps_the_agents_own_extension_untouched(service, monkeypatch):
    published = {}
    monkeypatch.setattr(
        "runner.app.register_external",
        lambda registry, card, pid, key: published.update(card=card),
    )
    with _CardServer() as srv:
        status, body = service.connect_agent({"endpoint_url": srv.url})
    assert status == 200, body
    assert body["trust_tier"] == "verified"
    exts = [e for e in published["card"]["capabilities"]["extensions"]
            if e["uri"].endswith("/trust/v1")]
    assert len(exts) == 1  # not duplicated
    assert "attested_by" not in exts[0].get("params", {})


def test_inspect_allows_a_card_without_skills():
    """External agents often publish no skills in our vocabulary — the operator
    declares them at connect time instead."""
    with _CardServer(with_skills=False) as srv:
        detected = inspect(srv.url)
    assert detected["capabilities"] == []
    assert detected["principal_id"] == srv.principal_id


def test_accepts_the_full_card_url_without_duplicating_the_path():
    """Pasting the card URL itself must not append /.well-known twice."""
    from runner.connect import card_url_for, base_url_for

    full = "https://example.com/.well-known/agent-card.json"
    assert card_url_for(full) == full
    assert base_url_for(full) == "https://example.com"
    # base form still gets the well-known path appended
    assert card_url_for("https://example.com") == full
    # a bare .json path is treated as the card itself
    assert card_url_for("https://example.com/card.json") == "https://example.com/card.json"


def test_inspect_works_when_given_the_full_card_url():
    with _CardServer() as srv:
        detected = inspect(srv.url + "/.well-known/agent-card.json")
    assert detected["principal_id"] == srv.principal_id


def test_forbidden_host_gives_an_actionable_message(monkeypatch):
    import urllib.error
    import runner.connect as connect_mod

    def boom(*a, **k):
        raise urllib.error.HTTPError("u", 403, "Forbidden", {}, None)

    monkeypatch.setattr(connect_mod.urllib.request, "urlopen", boom)
    with pytest.raises(ConnectError, match="403 Forbidden"):
        inspect("https://blocked.example.com")


def test_inspect_rejects_unreachable_endpoint():
    with pytest.raises(ConnectError, match="could not reach"):
        inspect("http://127.0.0.1:1")  # nothing listening


def test_inspect_rejects_non_http_url():
    with pytest.raises(ConnectError, match="http"):
        inspect("ftp://example.com")


# -- connect flow ------------------------------------------------------------


def test_verify_connect_returns_detected_fields(service):
    with _CardServer() as srv:
        status, body = service.verify_connect({"endpoint_url": srv.url})
    assert status == 200, body
    assert body["name"] == "External Bot"
    assert body["principal_id"] == srv.principal_id
    assert body["capabilities"] == ["terraform.generate"]


def test_verify_connect_missing_url_is_422(service):
    status, _ = service.verify_connect({})
    assert status == 422


def test_connect_stores_a_connected_definition(service):
    with _CardServer() as srv:
        status, body = service.connect_agent({"endpoint_url": srv.url})
        assert status == 200, body
        assert body["kind"] == "connected"
        assert body["endpoint_url"] == srv.url
        assert body["principal_id"] == srv.principal_id
        assert body["capabilities"] == ["terraform.generate"]
        # externally hosted + reachable -> online, with no process of ours
        assert body["runtime"]["status"] == "online"
        assert body["runtime"]["pid"] is None


def test_connected_agent_reports_offline_when_host_goes_away(service):
    with _CardServer() as srv:
        _, created = service.connect_agent({"endpoint_url": srv.url})
    # server stopped -> health-check fails
    status, body = service.get_agent(created["id"])
    assert status == 200
    assert body["runtime"]["status"] == "offline"


def test_connected_agent_cannot_be_started(service):
    with _CardServer() as srv:
        _, created = service.connect_agent({"endpoint_url": srv.url})
    status, body = service.start_agent(created["id"])
    assert status == 400
    assert "externally" in body["error"]


def test_merge_skills_adds_declared_capabilities_to_the_card():
    from runner.connect import merge_skills

    card = {"skills": [{"id": "terraform.generate", "name": "TF"}]}
    merged = merge_skills(card, ["terraform.generate", "security.pentest"])
    ids = [s["id"] for s in merged["skills"]]
    assert ids == ["terraform.generate", "security.pentest"]  # existing kept, new appended
    assert card["skills"] == [{"id": "terraform.generate", "name": "TF"}]  # input untouched


def test_operator_declared_capabilities_win_and_are_published(service, monkeypatch):
    """An agent whose card declares no skills can still join: the operator picks
    capabilities, and they must land IN the registered card for discovery."""
    published = {}
    monkeypatch.setattr(
        "runner.app.register_external",
        lambda registry, card, pid, key: published.update(card=card),
    )
    with _CardServer(with_skills=False) as srv:
        status, body = service.connect_agent({
            "endpoint_url": srv.url,
            "capabilities": ["security.pentest", "data.analysis"],
        })
    assert status == 200, body
    assert body["capabilities"] == ["security.pentest", "data.analysis"]
    ids = [s["id"] for s in published["card"]["skills"]]
    assert ids == ["security.pentest", "data.analysis"]


def test_connect_without_any_capability_is_422(service):
    with _CardServer(with_skills=False) as srv:
        status, body = service.connect_agent({"endpoint_url": srv.url})
    assert status == 422
    assert "at least one" in body["error"]


def test_declared_capabilities_must_be_strings(service):
    with _CardServer() as srv:
        status, _ = service.connect_agent({"endpoint_url": srv.url, "capabilities": [1, 2]})
    assert status == 422


def test_connected_agent_appears_in_the_list(service):
    with _CardServer() as srv:
        _, created = service.connect_agent({"endpoint_url": srv.url})
        status, listed = service.list_agents()
    assert status == 200
    ids = [a["id"] for a in listed["agents"]]
    assert created["id"] in ids
