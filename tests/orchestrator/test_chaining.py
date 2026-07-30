"""Output chaining and partial-failure coverage (U14)."""

from agents.orchestrator.tools import ChainExecutor


def _chain():
    return [
        {
            "id": "step-1",
            "capability": "calendar.create",
            "input": {"title": "Planning"},
            "depends_on": [],
        },
        {
            "id": "step-2",
            "capability": "gmail.send",
            "input": {
                "event_id": {"$ref": "step-1.output.event_id"},
                "receipt_id": {"$ref": "step-1.receipt.id"},
            },
            "depends_on": ["step-1"],
        },
    ]


def test_prior_output_and_receipt_feed_later_input_in_declared_order():
    calls = []

    def execute(step):
        calls.append(step)
        if step["id"] == "step-1":
            return {
                "status": "done",
                "output": {"event_id": "event-7"},
                "receipt": {"id": "receipt-7"},
            }
        return {
            "status": "done",
            "output": {"message_id": "message-9"},
            "receipt": {"id": "receipt-9"},
        }

    result = ChainExecutor().execute("chain-1", _chain(), execute)

    assert result["status"] == "complete"
    assert [call["id"] for call in calls] == ["step-1", "step-2"]
    assert calls[1]["input"] == {
        "event_id": "event-7",
        "receipt_id": "receipt-7",
    }
    assert result["receipts"]["step-1"] == {"id": "receipt-7"}


def test_partial_failure_keeps_receipt_and_retry_does_not_double_execute():
    counts = {"step-1": 0, "step-2": 0}

    def execute(step):
        counts[step["id"]] += 1
        if step["id"] == "step-1":
            return {
                "status": "done",
                "output": {"event_id": "event-7"},
                "receipt": {"id": "receipt-7"},
            }
        if counts["step-2"] == 1:
            raise RuntimeError("mail provider unavailable")
        return {
            "status": "done",
            "output": {"message_id": "message-9"},
            "receipt": {"id": "receipt-9"},
        }

    chain = ChainExecutor()
    partial = chain.execute("chain-1", _chain(), execute)

    assert partial["status"] == "partial_failure"
    assert partial["completed"] == ["step-1"]
    assert partial["failed_step"] == "step-2"
    assert partial["receipts"] == {"step-1": {"id": "receipt-7"}}
    assert "No automatic rollback" in partial["compensation"]

    completed = chain.execute("chain-1", _chain(), execute)
    assert completed["status"] == "complete"
    assert counts == {"step-1": 1, "step-2": 2}
    assert completed["receipts"]["step-1"] == {"id": "receipt-7"}
    assert completed["receipts"]["step-2"] == {"id": "receipt-9"}


def test_unknown_reference_stops_before_executing_dependent_step():
    calls = []
    steps = _chain()
    steps[1]["input"]["event_id"] = {"$ref": "step-1.output.unknown"}

    result = ChainExecutor().execute(
        "chain-1",
        steps,
        lambda step: (
            calls.append(step)
            or {
                "status": "done",
                "output": {"event_id": "event-7"},
                "receipt": {"id": "receipt-7"},
            }
        ),
    )

    assert result["status"] == "partial_failure"
    assert result["failed_step"] == "step-2"
    assert [call["id"] for call in calls] == ["step-1"]
