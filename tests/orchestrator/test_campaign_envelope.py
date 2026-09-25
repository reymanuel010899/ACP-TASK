import pytest

from agents.orchestrator.campaign_repository import (
    CampaignEnvelopeChanged,
    CampaignPermissionDenied,
    CampaignRepository,
    CampaignStateConflict,
)


def definition(**overrides):
    value = {
        "audience_rule": {"branch_id": "branch:sales", "include_descendants": True},
        "content": {"kind": "sms", "body": "Hola"},
        "channels": ["sms"], "senders": {"sms": "sender:1"},
        "schedule": {"starts_at": 100, "ends_at": 1000},
        "frequency": {"max_per_contact": 1, "period_seconds": 86400},
        "budget_micros": 5000000, "concurrency": 2,
        "duration_seconds": 900,
        "stop_conditions": ["budget_exhausted", "emergency_stop"],
        "include_late_arrivals": False,
        "audience_ceiling": 100,
    }
    value.update(overrides)
    return value


def audience():
    return [
        {"contact_id": "contact:1", "channel": "sms", "address_id": "addr:1",
         "branch_id": "branch:sales", "masked_destination": "+1 •••• 0101"},
        # Same canonical contact through a second list is one effect (AE10).
        {"contact_id": "contact:1", "channel": "sms", "address_id": "addr:1",
         "branch_id": "branch:sales", "masked_destination": "+1 •••• 0101"},
        {"contact_id": "contact:2", "channel": "sms", "address_id": "addr:2",
         "branch_id": "branch:sales", "masked_destination": "+1 •••• 0202"},
    ]


def repository(tmp_path):
    return CampaignRepository(str(tmp_path / "campaigns.sqlite3"), clock=lambda: 100)


def test_preview_authorize_and_dedupe_a_fixed_cohort(tmp_path):
    repo = repository(tmp_path)
    preview = repo.create_preview(
        "tenant:a", "campaign:1", "user:operator", definition(), audience(),
        exclusions=[{"contact_id": "contact:3", "reason": "consent_missing"}],
        estimated_spend_micros=3000000,
    )

    assert preview["eligible_count"] == 2
    assert len(preview["envelope_hash"]) == 64
    assert preview["exclusion_reasons"] == {"consent_missing": 1}
    assert all("address_id" not in row for row in preview["audience"])
    authorized = repo.authorize(
        "tenant:a", "campaign:1", "user:operator",
        permission_check=lambda principal, branch: principal == "user:operator",
    )
    assert authorized["status"] == "authorized"
    assert len(authorized["envelope_hash"]) == 64
    assert len(repo.list_effects("tenant:a", "campaign:1")) == 2


def test_material_change_invalidates_authorization_and_halts_effects(tmp_path):
    repo = repository(tmp_path)
    repo.create_preview("tenant:a", "campaign:1", "user:operator", definition(), audience())
    repo.authorize("tenant:a", "campaign:1", "user:operator", lambda *_: True)

    with pytest.raises(CampaignEnvelopeChanged):
        repo.assert_envelope(
            "tenant:a", "campaign:1", definition(budget_micros=9000000)
        )

    assert repo.get("tenant:a", "campaign:1")["status"] == "invalidated"
    assert {row["status"] for row in repo.list_effects("tenant:a", "campaign:1")} == {"cancelled"}


def test_campaign_use_permission_is_required_and_loss_requires_reaffirmation(tmp_path):
    repo = repository(tmp_path)
    repo.create_preview("tenant:a", "campaign:1", "user:operator", definition(), audience())
    with pytest.raises(CampaignPermissionDenied):
        repo.authorize("tenant:a", "campaign:1", "user:operator", lambda *_: False)

    repo.authorize("tenant:a", "campaign:1", "user:operator", lambda *_: True)
    assert repo.check_authority(
        "tenant:a", "campaign:1", lambda *_: False, reaffirm_within_seconds=300
    ) == "reaffirmation_required"
    assert repo.get("tenant:a", "campaign:1")["status"] == "paused"


def test_snapshot_excludes_late_arrivals_and_never_exposes_raw_destinations(tmp_path):
    repo = repository(tmp_path)
    preview = repo.create_preview(
        "tenant:a", "campaign:1", "user:operator", definition(), audience()
    )
    repo.authorize("tenant:a", "campaign:1", "user:operator", lambda *_: True)

    assert repo.add_late_audience_member(
        "tenant:a", "campaign:1", {
            "contact_id": "contact:late", "channel": "sms", "address_id": "addr:late",
            "branch_id": "branch:new", "masked_destination": "+1 •••• 9999",
        }
    ) is False
    assert preview["audience"][0].keys() == {
        "contact_id", "channel", "branch_id", "masked_destination"
    }


def test_explicit_late_arrivals_are_bounded_by_the_authorized_ceiling(tmp_path):
    repo = repository(tmp_path)
    repo.create_preview(
        "tenant:a", "campaign:1", "user:operator",
        definition(include_late_arrivals=True, audience_ceiling=3), audience(),
    )
    original_hash = repo.authorize(
        "tenant:a", "campaign:1", "user:operator", lambda *_: True
    )["envelope_hash"]
    assert repo.add_late_audience_member(
        "tenant:a", "campaign:1", {
            "contact_id": "contact:late", "channel": "sms", "address_id": "addr:late",
            "branch_id": "branch:sales", "masked_destination": "+1 •••• 9999",
        }
    )
    assert not repo.add_late_audience_member(
        "tenant:a", "campaign:1", {
            "contact_id": "contact:too-late", "channel": "sms",
            "address_id": "addr:too-late", "branch_id": "branch:sales",
            "masked_destination": "+1 •••• 9998",
        }
    )
    assert repo.get("tenant:a", "campaign:1")["envelope_hash"] == original_hash


def test_preview_expires_before_authorization_but_scheduled_duration_does_not(tmp_path):
    now = [100]
    repo = CampaignRepository(str(tmp_path / "campaigns.sqlite3"), clock=lambda: now[0])
    repo.create_preview(
        "tenant:a", "campaign:1", "user:operator",
        definition(schedule={"starts_at": 1000, "ends_at": 2000}, duration_seconds=500),
        audience(), approval_ttl_seconds=10,
    )
    now[0] = 111
    with pytest.raises(CampaignStateConflict, match="preview authorization expired"):
        repo.authorize("tenant:a", "campaign:1", "user:operator", lambda *_: True)

    repo.create_preview(
        "tenant:a", "campaign:2", "user:operator",
        definition(schedule={"starts_at": 1000, "ends_at": 2000}, duration_seconds=500),
        audience(), approval_ttl_seconds=100,
    )
    authorized = repo.authorize(
        "tenant:a", "campaign:2", "user:operator", lambda *_: True
    )
    assert authorized["envelope_expires_at"] == 1500


def test_cohort_tampering_invalidates_before_execution(tmp_path):
    repo = repository(tmp_path)
    repo.create_preview("tenant:a", "campaign:1", "user:operator", definition(), audience())
    repo.authorize("tenant:a", "campaign:1", "user:operator", lambda *_: True)
    repo._connection.execute(
        """insert into campaign_cohort(
            tenant_id,campaign_id,contact_id,channel,address_id,branch_id,
            masked_destination,included
        ) values('tenant:a','campaign:1','contact:late','sms','addr:late',
                 'branch:sales','redacted',1)"""
    )
    with pytest.raises(CampaignEnvelopeChanged):
        repo.assert_envelope("tenant:a", "campaign:1", definition())
