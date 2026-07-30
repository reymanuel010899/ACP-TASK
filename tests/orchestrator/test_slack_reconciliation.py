from services.action_broker.reconciliation import SlackReconciler


class Gateway:
    def __init__(self, result):
        self.result = result

    def find_effect(self, **kwargs):
        return dict(self.result)


def _attempt():
    return {
        "connection_id": "conn:1", "channel_id": "C1",
        "capability_id": "slack.message.send", "approved_payload_hash": "a" * 64,
        "dispatch_started_at": 100, "dispatch_ended_at": 110,
    }


def test_found_effect_completes_without_second_write():
    result = SlackReconciler(Gateway({
        "outcome": "found", "provider_id": "123.45",
    })).reconcile(_attempt())
    assert result == {
        "execution_status": "completed",
        "verification_status": "pending",
        "provider_id": "123.45",
        "retry_safe": False,
    }


def test_only_proven_absence_across_full_interval_is_retryable():
    proven = SlackReconciler(Gateway({
        "outcome": "absent", "complete_interval": True,
    })).reconcile(_attempt())
    incomplete = SlackReconciler(Gateway({
        "outcome": "absent", "complete_interval": False,
    })).reconcile(_attempt())
    assert proven["execution_status"] == "queued"
    assert proven["retry_safe"] is True
    assert incomplete["execution_status"] == "execution_unknown"
    assert incomplete["retry_safe"] is False
