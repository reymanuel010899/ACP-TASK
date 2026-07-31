from web.concierge import (
    _conversation_id_from_path, _valid_conversation_id, _workflow_id_from_path,
)


def test_workflow_path_decodes_the_identifier_forwarded_by_nextjs():
    assert _workflow_id_from_path(
        "/workflows/workflow%3Aa12/approve", "approve"
    ) == "workflow:a12"


def test_workflow_get_path_decodes_the_identifier_forwarded_by_nextjs():
    assert _workflow_id_from_path(
        "/workflows/workflow%3Aa12"
    ) == "workflow:a12"


def test_conversation_paths_decode_opaque_identifiers_and_reject_malformed_values():
    assert _conversation_id_from_path(
        "/conversations/conversation%3Aa12/close", "close"
    ) == "conversation:a12"
    assert _valid_conversation_id("conversation:a12")
    assert not _valid_conversation_id("../conversation:a12")
    assert not _valid_conversation_id("workflow:a12")
