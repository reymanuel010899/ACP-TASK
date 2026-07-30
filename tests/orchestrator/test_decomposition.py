"""Bounded ordered goal decomposition coverage (U13)."""

from agents.orchestrator.decomposition import decompose_goal
from agents.orchestrator.tools import plan_subtasks


def test_two_capability_goal_is_ordered_with_dependency():
    plan = decompose_goal(
        "Create a calendar event, then email the invitation",
        ["calendar.create", "gmail.send", "drive.upload"],
    )

    assert plan["status"] == "ready"
    assert [step["capability"] for step in plan["subtasks"]] == [
        "calendar.create",
        "gmail.send",
    ]
    assert plan["subtasks"][0]["depends_on"] == []
    assert plan["subtasks"][1]["depends_on"] == ["step-1"]


def test_single_capability_goal_yields_one_subtask():
    plan = decompose_goal("Upload this file", ["drive.upload"])

    assert plan == {
        "status": "ready",
        "subtasks": [
            {
                "id": "step-1",
                "capability": "drive.upload",
                "input": {},
                "depends_on": [],
            }
        ],
    }


def test_unsatisfiable_capability_surfaces_cleanly():
    plan = decompose_goal(
        "Create a calendar event and send the invitation",
        ["calendar.create"],
    )

    assert plan["status"] == "unsatisfiable"
    assert plan["missing_capabilities"] == ["gmail.send"]
    assert "gmail.send" in plan["message"]


def test_plan_subtasks_rejects_future_dependencies_and_unbounded_plans():
    invalid = [
        {
            "id": "step-1",
            "capability": "calendar.create",
            "input": {},
            "depends_on": ["step-2"],
        },
        {
            "id": "step-2",
            "capability": "gmail.send",
            "input": {},
            "depends_on": [],
        },
    ]

    assert plan_subtasks(invalid)["status"] == "invalid"
    assert plan_subtasks(
        [{"capability": "cap.%d" % index} for index in range(6)]
    )["status"] == "invalid"
