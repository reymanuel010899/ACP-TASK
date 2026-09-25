from agents.orchestrator.campaign_repository import CampaignRepository
from agents.orchestrator.dispatch_ledger import AmbiguousDispatch
from libs.spend_ledger import SpendCeilingExceeded
from services.campaign_worker.app import CampaignWorker


def _definition():
    return {
        "audience_rule": {"branch_id": "branch:all", "include_descendants": True},
        "content": {"kind": "sms", "body": "hello"}, "channels": ["sms"],
        "senders": {"sms": "sender:1"},
        "schedule": {"starts_at": 100, "ends_at": 1000},
        "frequency": {"max_per_contact": 1, "period_seconds": 86400},
        "budget_micros": 1000000, "concurrency": 1, "duration_seconds": 900,
        "stop_conditions": ["budget_exhausted", "emergency_stop"],
        "include_late_arrivals": False,
        "audience_ceiling": 100,
    }


def _repo(tmp_path, count=3):
    repo = CampaignRepository(str(tmp_path / "campaigns.db"), clock=lambda: 100)
    audience = [{
        "contact_id": "contact:%d" % index, "channel": "sms",
        "address_id": "address:%d" % index, "branch_id": "branch:all",
        "masked_destination": "+1 •••• %04d" % index,
    } for index in range(count)]
    repo.create_preview("tenant:a", "campaign:1", "user:operator", _definition(), audience)
    repo.authorize("tenant:a", "campaign:1", "user:operator", lambda *_: True)
    return repo


def test_spend_ceiling_prevents_every_remaining_effect_and_buckets_sum(tmp_path):
    repo = _repo(tmp_path)
    worker = CampaignWorker(
        repo, "worker:1", lambda *_: {"allowed": True},
        lambda *_: (_ for _ in ()).throw(SpendCeilingExceeded("campaign_ceiling_exhausted")),
        clock=lambda: 100,
    )
    assert worker.tick() == "prevented"
    report = repo.report("tenant:a", "campaign:1")
    assert report["outcomes"]["prevented"] == 3
    assert sum(report["outcomes"].values()) == report["audience_total"] == 3
    assert report["status"] == "drained"


def test_emergency_stop_prevents_new_dispatch_without_reclassifying_claimed_work(tmp_path):
    repo = _repo(tmp_path, count=2)
    claim = repo.claim_next("worker:live", 100, 60)
    worker = CampaignWorker(
        repo, "worker:stop", lambda *_: {"allowed": True}, lambda *_: {},
        emergency_stopped=lambda _tenant: True, clock=lambda: 100,
    )
    assert worker.tick() == "stopped"
    report = repo.report("tenant:a", "campaign:1")
    assert report["outcomes"]["prevented"] == 1
    assert report["outcomes"]["in_progress"] == 1
    assert claim["contact_id"]


def test_ambiguous_provider_outcome_waits_in_reconciliation(tmp_path):
    repo = _repo(tmp_path, count=1)
    worker = CampaignWorker(
        repo, "worker:1", lambda *_: {"allowed": True},
        lambda *_: (_ for _ in ()).throw(AmbiguousDispatch("unknown")),
        clock=lambda: 100,
    )
    assert worker.tick() == "uncertain"
    report = repo.report("tenant:a", "campaign:1")
    assert report["status"] == "reconciling"
    assert report["outcomes"]["uncertain"] == 1
    assert repo.reconcile_effect(
        "tenant:a", "campaign:1", "contact:0", "sms", "delivered", "SM1"
    )
    assert repo.report("tenant:a", "campaign:1")["status"] == "drained"


def test_operator_can_pause_and_resume_without_changing_the_envelope(tmp_path):
    repo = _repo(tmp_path, count=1)
    envelope = repo.get("tenant:a", "campaign:1")["envelope_hash"]
    repo.pause("tenant:a", "campaign:1", "user:operator")
    assert repo.next_campaign(100) is None
    repo.resume("tenant:a", "campaign:1", "user:operator")
    assert repo.next_campaign(100)["campaign_id"] == "campaign:1"
    assert repo.get("tenant:a", "campaign:1")["envelope_hash"] == envelope


def test_new_operator_can_reaffirm_after_original_permission_is_lost(tmp_path):
    repo = _repo(tmp_path, count=1)
    envelope = repo.get("tenant:a", "campaign:1")["envelope_hash"]
    assert repo.check_authority(
        "tenant:a", "campaign:1", lambda *_: False, reaffirm_within_seconds=30
    ) == "reaffirmation_required"
    campaign = repo.reaffirm(
        "tenant:a", "campaign:1", "user:new-operator", lambda *_: True
    )
    assert campaign["authorized_by"] == "user:new-operator"
    assert campaign["envelope_hash"] == envelope
    assert campaign["status"] == "running"
