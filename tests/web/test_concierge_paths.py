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


def test_effect_paths_split_into_a_conversation_and_one_effect():
    from web.concierge import _effect_path_parts, _valid_effect_id

    assert _effect_path_parts(
        "/conversations/conversation%3Aabc/effects/effect%3A1"
    ) == ("conversation:abc", "effect:1")
    # Anything that is not that exact shape yields no pair at all, so the
    # handler decides on a well-formed reference rather than a string prefix.
    assert _effect_path_parts("/conversations/conversation:abc/close") == (None, None)
    assert _effect_path_parts("/conversations/conversation:abc/effects/") == (None, None)
    assert _effect_path_parts(
        "/conversations/conversation:abc/effects/effect:1/extra"
    ) == (None, None)
    assert _valid_effect_id("effect:2f9a")
    assert not _valid_effect_id("../../etc/passwd")
    assert not _valid_effect_id("conversation:abc")
