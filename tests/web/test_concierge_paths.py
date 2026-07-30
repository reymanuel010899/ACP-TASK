from web.concierge import _workflow_id_from_path


def test_workflow_path_decodes_the_identifier_forwarded_by_nextjs():
    assert _workflow_id_from_path(
        "/workflows/workflow%3Aa12/approve", "approve"
    ) == "workflow:a12"


def test_workflow_get_path_decodes_the_identifier_forwarded_by_nextjs():
    assert _workflow_id_from_path(
        "/workflows/workflow%3Aa12"
    ) == "workflow:a12"
