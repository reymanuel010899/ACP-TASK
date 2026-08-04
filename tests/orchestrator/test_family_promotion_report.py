"""U8: the evidence a family enablement decision must be made from."""

import pytest

from agents.orchestrator.workflow_repository import WorkflowRepository

NOW = 1_700_000_000


def _repository(tmp_path):
    return WorkflowRepository(str(tmp_path / "workflows.sqlite3"))


def _conversation(repository, index):
    conversation = repository.create_conversation(
        "org:acme", "user:alice", NOW, ttl_seconds=600,
        conversation_id="conversation:%d" % index,
    )
    return conversation["conversation_id"]


def _record(repository, conversation_id, event_type, family, at=NOW + 1):
    repository.append_conversation_outcome_event(
        conversation_id, "org:acme", "user:alice", event_type, at,
        operation_family=family,
    )


def test_a_family_is_reported_against_the_gate_it_must_pass(tmp_path):
    repository = _repository(tmp_path)
    for index in range(4):
        conversation_id = _conversation(repository, index)
        _record(repository, conversation_id, "operation_attempted", "post")
        _record(repository, conversation_id, "previewed", "post")
        if index < 3:
            _record(repository, conversation_id, "completed", "post")
        else:
            _record(repository, conversation_id, "abandoned", "post")

    report = {item["family"]: item for item in
              repository.family_promotion_report("org:acme", NOW, NOW + 100)}

    post = report["post"]
    assert post["attempted"] == 4
    assert post["completed"] == 3
    assert post["abandoned"] == 1
    assert post["preview_conversion"] == 0.75


def test_a_rate_is_absent_rather_than_zero_when_there_is_no_data(tmp_path):
    repository = _repository(tmp_path)
    conversation_id = _conversation(repository, 0)
    _record(repository, conversation_id, "operation_attempted", "read")

    report = repository.family_promotion_report("org:acme", NOW, NOW + 100)

    # Nothing was previewed, so a conversion of 0.0 would read as "nobody
    # converts" rather than "nobody was asked".
    assert report[0]["preview_conversion"] is None
    assert report[0]["clarification_rate"] == 0.0


def test_thin_evidence_says_so_instead_of_looking_decisive(tmp_path):
    repository = _repository(tmp_path)
    conversation_id = _conversation(repository, 0)
    _record(repository, conversation_id, "operation_attempted", "post")
    _record(repository, conversation_id, "completed", "post")

    report = repository.family_promotion_report("org:acme", NOW, NOW + 100)

    # One completed attempt is a 100% completion rate and means nothing.
    assert report[0]["sufficient_evidence"] is False


def test_attempts_at_a_disabled_family_are_counted_as_demand(tmp_path):
    repository = _repository(tmp_path)
    for index in range(3):
        conversation_id = _conversation(repository, index)
        _record(repository, conversation_id, "operation_attempted", "canvas")

    report = {item["family"]: item for item in
              repository.family_promotion_report("org:acme", NOW, NOW + 100)}

    # Nobody built canvases. People asking for them anyway is precisely the
    # evidence that decides whether they get built.
    assert report["canvas"]["attempted"] == 3
    assert report["canvas"]["completed"] == 0


def test_the_report_is_tenant_scoped(tmp_path):
    repository = _repository(tmp_path)
    conversation_id = _conversation(repository, 0)
    _record(repository, conversation_id, "operation_attempted", "post")

    assert repository.family_promotion_report("org:other", NOW, NOW + 100) == []


def test_a_finished_read_records_its_completion(tmp_path):
    """A read finishes in the projection, not in the service.

    Without this the read family reported a hundred attempts and zero
    completions, and any gate reading that would have judged a working family
    as broken.
    """
    repository = _repository(tmp_path)
    conversation_id = _conversation(repository, 0)
    repository.update_conversation(
        conversation_id, "org:acme", "user:alice",
        {"status": "retrieving", "operation": "read"}, NOW,
    )
    _record(repository, conversation_id, "operation_attempted", "read")

    repository._record_read_completion(
        conversation_id, "org:acme", "user:alice", NOW + 2,
    )

    report = {item["family"]: item for item in
              repository.family_promotion_report("org:acme", NOW, NOW + 100)}
    assert report["read"]["attempted"] == 1
    assert report["read"]["completed"] == 1
