import pytest

from agents.orchestrator.campaign_repository import CampaignRepository
from services.campaign_worker.app import CampaignWorker
from libs.connectors.base import ProviderHTTPError, ProviderNetworkError


def definition(**overrides):
    value = {
        "audience_rule": {"branch_id": "branch:sales", "include_descendants": True},
        "content": {"kind": "sms", "body": "Hola"}, "channels": ["sms"],
        "senders": {"sms": "sender:1"},
        "schedule": {"starts_at": 100, "ends_at": 1000},
        "frequency": {"max_per_contact": 1, "period_seconds": 86400},
        "budget_micros": 5000000, "concurrency": 2, "duration_seconds": 900,
        "stop_conditions": ["budget_exhausted", "emergency_stop"],
        "include_late_arrivals": False,
        "audience_ceiling": 100,
    }
    value.update(overrides)
    return value


def member(number):
    return {"contact_id": "contact:%s" % number, "channel": "sms",
            "address_id": "address:%s" % number, "branch_id": "branch:sales",
            "masked_destination": "+1 •••• %04d" % number}


def setup_campaign(tmp_path, clock, members=3, campaign_definition=None):
    repo = CampaignRepository(str(tmp_path / "campaigns.db"), clock=clock)
    repo.create_preview("tenant:a", "campaign:1", "user:operator",
                        campaign_definition or definition(),
                        [member(index) for index in range(members)])
    repo.authorize("tenant:a", "campaign:1", "user:operator", lambda *_: True)
    return repo


def test_campaign_completes_as_small_per_contact_effects(tmp_path):
    clock = lambda: 100
    repo = setup_campaign(tmp_path, clock)
    dispatched = []
    worker = CampaignWorker(
        repo, "worker:1", eligibility=lambda effect, campaign: {"allowed": True},
        dispatch=lambda effect, campaign: dispatched.append(effect["contact_id"]) or {"provider_id": "SM" + effect["contact_id"]},
        clock=clock,
    )
    while worker.tick():
        pass
    report = repo.report("tenant:a", "campaign:1")
    assert len(dispatched) == 3
    assert report["status"] == "drained"
    assert report["outcomes"] == {"completed": 3, "in_progress": 0, "prevented": 0, "uncertain": 0, "never_eligible_within_window": 0}


def test_live_optout_prevents_one_contact_and_campaign_continues(tmp_path):
    repo = setup_campaign(tmp_path, lambda: 100)
    worker = CampaignWorker(
        repo, "worker:1",
        eligibility=lambda effect, campaign: {"allowed": effect["contact_id"] != "contact:1", "reason": "suppressed_by_optout"},
        dispatch=lambda *_: {"provider_id": "SM1"}, clock=lambda: 100,
    )
    while worker.tick():
        pass
    report = repo.report("tenant:a", "campaign:1")
    assert report["outcomes"]["prevented"] == 1
    assert report["outcomes"]["completed"] == 2
    assert repo.get("tenant:a", "campaign:1")["envelope_hash"]


def test_quiet_hours_defer_then_send_without_consuming_an_attempt(tmp_path):
    now = [100]
    repo = setup_campaign(tmp_path, lambda: now[0], members=1)
    worker = CampaignWorker(
        repo, "worker:1",
        eligibility=lambda *_: ({"allowed": False, "reason": "quiet_hours", "defer_until": 200} if now[0] < 200 else {"allowed": True}),
        dispatch=lambda *_: {"provider_id": "SM1"}, clock=lambda: now[0],
    )
    assert worker.tick() == "deferred"
    assert repo.list_effects("tenant:a", "campaign:1")[0]["attempt_count"] == 0
    now[0] = 200
    assert worker.tick() == "completed"


def test_connection_outage_pauses_without_consuming_attempts(tmp_path):
    repo = setup_campaign(tmp_path, lambda: 100, members=1)
    connected = [False]
    worker = CampaignWorker(
        repo, "worker:1", eligibility=lambda *_: {"allowed": True},
        dispatch=lambda *_: {"provider_id": "SM1"},
        connection_available=lambda *_: connected[0], clock=lambda: 100,
    )
    assert worker.tick() == "blocked_connection"
    assert repo.list_effects("tenant:a", "campaign:1")[0]["attempt_count"] == 0
    connected[0] = True
    assert worker.tick() == "completed"


def test_network_loss_after_dispatch_boundary_is_uncertain_not_retryable(tmp_path):
    repo = setup_campaign(tmp_path, lambda: 100, members=1)
    worker = CampaignWorker(
        repo, "worker:1", eligibility=lambda *_: {"allowed": True},
        dispatch=lambda *_: (_ for _ in ()).throw(ProviderNetworkError("lost")),
        clock=lambda: 100,
    )
    assert worker.tick() == "uncertain"
    assert repo.report("tenant:a", "campaign:1")["status"] == "reconciling"


def test_provider_rejection_prevents_recipient_and_does_not_strand_claim(tmp_path):
    repo = setup_campaign(tmp_path, lambda: 100, members=1)
    worker = CampaignWorker(
        repo, "worker:1", eligibility=lambda *_: {"allowed": True},
        dispatch=lambda *_: (_ for _ in ()).throw(
            ProviderHTTPError("twilio", 400, "message creation")
        ),
        clock=lambda: 100,
    )
    assert worker.tick() == "prevented"
    report = repo.report("tenant:a", "campaign:1")
    assert report["status"] == "drained"
    assert report["outcomes"]["prevented"] == 1


def test_permission_loss_pauses_for_reaffirmation_before_claim(tmp_path):
    repo = setup_campaign(tmp_path, lambda: 100, members=1)
    worker = CampaignWorker(
        repo, "worker:1", eligibility=lambda *_: {"allowed": True},
        dispatch=lambda *_: pytest.fail("must not dispatch"), clock=lambda: 100,
        authority_check=lambda *_: False,
    )
    assert worker.tick() == "reaffirmation_required"
    assert repo.list_effects("tenant:a", "campaign:1")[0]["status"] == "pending"


def test_never_eligible_when_deferral_exceeds_envelope_window(tmp_path):
    repo = setup_campaign(tmp_path, lambda: 100, members=1)
    worker = CampaignWorker(
        repo, "worker:1",
        eligibility=lambda *_: {"allowed": False, "reason": "quiet_hours", "defer_until": 1001},
        dispatch=lambda *_: pytest.fail("must not dispatch"), clock=lambda: 100,
    )
    assert worker.tick() == "never_eligible"
    assert repo.report("tenant:a", "campaign:1")["outcomes"]["never_eligible_within_window"] == 1


def test_expiry_cancels_remaining_effects_and_cannot_be_extended(tmp_path):
    now = [100]
    repo = setup_campaign(tmp_path, lambda: now[0], members=2,
                          campaign_definition=definition(duration_seconds=10))
    now[0] = 111
    worker = CampaignWorker(repo, "worker:1", lambda *_: {"allowed": True}, lambda *_: {}, clock=lambda: now[0])
    assert worker.tick() == "expired"
    assert repo.report("tenant:a", "campaign:1")["outcomes"]["prevented"] == 2
    with pytest.raises(ValueError, match="cannot be extended"):
        repo.extend_envelope("tenant:a", "campaign:1", 100)


def test_expired_worker_claim_is_bulk_quarantined_as_uncertain(tmp_path):
    now = [100]
    repo = setup_campaign(tmp_path, lambda: now[0], members=1)
    claim = repo.claim_next("worker:dead", now[0], lease_seconds=5)
    assert claim
    now[0] = 106
    assert repo.recover_expired_claims(now[0]) == 1
    assert repo.report("tenant:a", "campaign:1")["outcomes"]["uncertain"] == 1


def test_two_workers_claim_one_contact_cycle_once(tmp_path):
    repo = setup_campaign(tmp_path, lambda: 100, members=1)
    first = repo.claim_next("worker:1", 100, 30)
    second = repo.claim_next("worker:2", 100, 30)
    assert first is not None
    assert second is None
