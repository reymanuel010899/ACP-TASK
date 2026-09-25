from agents.orchestrator.delivery_verdict import DeliveryVerdictService


class Workflows:
    def __init__(self):
        self.updates = []

    def set_verification_status(self, revision, step, tenant, status):
        self.updates.append((revision, step, tenant, status))


def effect(**overrides):
    value = {
        "tenant_id": "tenant:a", "effect_id": "effect:1",
        "workflow_revision_id": "revision:1", "step_id": "send",
        "address_id": "address:1", "channel": "sms", "accepted_at": 100,
        "verification_status": "pending", "conversation_closed": False,
    }
    value.update(overrides)
    return value


def test_provider_acceptance_and_delivery_truth_are_separate():
    workflows = Workflows()
    service = DeliveryVerdictService(workflows)
    assert service.apply(effect(), "queued") == "pending"
    assert workflows.updates == []
    assert service.apply(effect(), "delivered") == "verified"
    assert workflows.updates == [
        ("revision:1", "send", "tenant:a", "verified")
    ]


def test_only_durable_destination_evidence_suppresses():
    suppressions = []
    service = DeliveryVerdictService(
        Workflows(), suppression_writer=lambda **value: suppressions.append(value)
    )
    service.apply(effect(), "failed", "30001")
    service.apply(effect(effect_id="effect:2"), "undelivered", "30003")
    assert len(suppressions) == 1
    assert suppressions[0]["state"] == "suppressed_by_bounce"


def test_provider_optout_is_permanent_not_retryable():
    suppressions = []
    service = DeliveryVerdictService(
        Workflows(), suppression_writer=lambda **value: suppressions.append(value)
    )
    assert service.apply(effect(), "failed", "21610") == "failed"
    assert suppressions[0]["state"] == "suppressed_by_optout"


def test_deadline_becomes_inconclusive_and_emits_late_correction():
    workflows, corrections = Workflows(), []
    service = DeliveryVerdictService(
        workflows, correction_writer=lambda **value: corrections.append(value),
        clock=lambda: 100 + 24 * 60 * 60,
    )
    expired = service.expire([effect(conversation_closed=True)])
    assert expired == ["effect:1"]
    assert workflows.updates[-1] == (
        "revision:1", "send", "tenant:a", "inconclusive"
    )
    assert corrections[0]["verification_status"] == "inconclusive"
