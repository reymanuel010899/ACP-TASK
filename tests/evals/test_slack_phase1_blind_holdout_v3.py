"""Promotion gate for the independently authored Phase 1 blind holdout v3."""

import json
import os
import re
from pathlib import Path

import pytest

from agents.orchestrator.brain import GROQ_MODEL_ID
from tests.evals.test_slack_phase1_blind_holdout_v2 import (
    _MeasuredBrain,
    _authority_violations,
    _projection,
)


CASES_PATH = Path(__file__).with_name("slack_phase1_blind_holdout_v3.jsonl")
MIN_OPERATION_ACCURACY = 0.90
MIN_REQUIRED_SLOT_ACCURACY = 0.85


def _cases():
    return [
        json.loads(line)
        for line in CASES_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _normalize(value):
    import unicodedata

    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.casefold().strip().lstrip("#@").strip(" \t\r\n:;,.!?\"'“”‘’")
    return " ".join(text.split())


def _literal_matches(expected, actual):
    expected, actual = _normalize(expected), _normalize(actual)
    if expected == actual or (len(expected) >= 4 and expected in actual):
        return True
    expected_digits = re.findall(r"\d+", expected)
    return bool(expected_digits and expected_digits == re.findall(r"\d+", actual))


def _actual_slots(result, registry):
    declared = {
        operation.operation_id: {slot.name for slot in operation.slots}
        for operation in registry.operations
    }
    operations = [operation.operation_id for operation in result.operations]
    values = {}

    def add(name, value, provenance, operation_index):
        if operation_index is None:
            candidates = [
                index for index, operation_id in enumerate(operations)
                if name in declared.get(operation_id, set())
            ]
            if len(candidates) != 1:
                return
            operation_index = candidates[0]
        values.setdefault((operation_index, name), []).append(
            (value, provenance)
        )

    for slot in result.slots:
        add(slot.name, slot.value, slot.provenance, slot.operation_index)
    for correction in result.corrections:
        add(
            correction.slot, correction.replacement, correction.provenance,
            correction.operation_index,
        )
    return values


def test_blind_holdout_v3_is_well_formed_and_manifest_grounded():
    cases = _cases()
    registry, _model_projection = _projection()
    operations = {operation.operation_id: operation for operation in registry.operations}
    coverage = {
        item["method"]: item
        for entries in registry.method_coverage.values()
        for item in entries
    }

    # Grew to 25 when U5 and U6 promoted methods this corpus had covered as
    # refusals. The replacement cases target methods that remain dormant, so
    # refusal coverage is restored by adding, never by lowering the bar.
    assert len(cases) == 25
    assert len({case["id"] for case in cases}) == len(cases)
    assert {case["locale"] for case in cases} == {"es", "en", "mixed"}
    assert sum(case["support_state"] in {"planned", "dormant"} for case in cases) >= 5
    for case in cases:
        if case["support_state"] in {"planned", "dormant"}:
            assert case["expected_operations"] == []
            assert coverage[case["requested_method"]]["state"] == case["support_state"]
            continue
        assert "requested_method" not in case
        for operation_id in case["expected_operations"]:
            assert operation_id in operations
        for slot in case["expected_slots"]:
            assert slot["mode"] in {"literal", "context_reference", "missing"}
            operation_id = case["expected_operations"][slot["operation_index"]]
            assert slot["name"] in {
                item.name for item in operations[operation_id].slots
            }
            if slot["mode"] == "literal":
                assert "value" in slot
            elif slot["mode"] == "context_reference":
                assert slot["provenance"] == "conversation"
            else:
                assert slot["blocker"] == slot["name"]


@pytest.mark.skipif(
    os.environ.get("RUN_GROQ_BLIND_V3_EVALS", "").casefold() != "true",
    reason="set RUN_GROQ_BLIND_V3_EVALS=true for the one-shot live holdout",
)
def test_live_groq_phase1_blind_holdout_v3():
    api_key = os.environ.get("GROQ_API_KEY")
    assert api_key, "RUN_GROQ_BLIND_V3_EVALS=true requires GROQ_API_KEY"
    cases = _cases()
    registry, model_projection = _projection()
    brain = _MeasuredBrain(
        api_key=api_key,
        model=os.environ.get("GROQ_MODEL") or GROQ_MODEL_ID,
        timeout=float(os.environ.get("GROQ_EVAL_REQUEST_TIMEOUT_SECONDS", "20")),
    )
    correct_operations = 0
    correct_slots = 0
    expected_slots = 0
    violations = []
    failures = []

    for case_index, case in enumerate(cases, start=1):
        print(
            "SLACK_PHASE1_BLIND_V3_CASE=%s/%s:%s" % (
                case_index, len(cases), case["id"],
            ),
            flush=True,
        )
        failed_before = brain.failed_calls
        raw_before = len(brain.raw_responses)
        result = brain.understand_slack(case["input"], {
            "conversation": ([{
                "role": "concierge", "text": case["context"],
            }] if case["context"] else []),
            "slack_operation_projection": model_projection,
        })
        transport_failed = brain.failed_calls > failed_before
        actual_operations = [] if transport_failed else [
            operation.operation_id for operation in result.operations
        ]
        operation_correct = actual_operations == case["expected_operations"]
        correct_operations += int(operation_correct)
        actual = {} if transport_failed else _actual_slots(result, registry)
        blocker_fields = {blocker.field for blocker in result.blockers}
        missed = []
        for expected in case["expected_slots"]:
            expected_slots += 1
            candidates = actual.get(
                (expected["operation_index"], expected["name"]), ()
            )
            if expected["mode"] == "literal":
                matched = any(
                    _literal_matches(expected["value"], value)
                    for value, _provenance in candidates
                )
            elif expected["mode"] == "context_reference":
                matched = any(
                    bool(str(value).strip())
                    and provenance == expected["provenance"]
                    for value, provenance in candidates
                )
            else:
                matched = expected["blocker"] in blocker_fields
            correct_slots += int(matched)
            if not matched:
                missed.append(
                    "%s.%s:%s" % (
                        expected["operation_index"], expected["name"],
                        expected["mode"],
                    )
                )
        case_violations = _authority_violations(result)
        if len(brain.raw_responses) > raw_before:
            try:
                raw_payload = json.loads(brain.raw_responses[-1])
            except (TypeError, ValueError):
                raw_payload = None
            if raw_payload is not None:
                case_violations.extend(
                    "raw.%s" % item for item in _authority_violations(raw_payload)
                )
        violations.extend(
            "%s:%s" % (case["id"], item) for item in case_violations
        )
        if not operation_correct or missed:
            failures.append({
                "id": case["id"], "transport_failed": transport_failed,
                "expected_operations": case["expected_operations"],
                "actual_operations": actual_operations, "missed_slots": missed,
            })

    operation_accuracy = correct_operations / len(cases)
    slot_accuracy = correct_slots / expected_slots
    summary = {
        "model": brain.model, "cases": len(cases),
        "operation_accuracy": round(operation_accuracy, 4),
        "required_slot_accuracy": round(slot_accuracy, 4),
        "authority_field_violations": len(violations),
        "transport_failures": brain.failed_calls, "failures": failures,
    }
    print("SLACK_PHASE1_BLIND_V3_GATE=" + json.dumps(summary, sort_keys=True))

    assert brain.live_calls + brain.failed_calls == len(cases), summary
    assert brain.failed_calls == 0, summary
    assert operation_accuracy >= MIN_OPERATION_ACCURACY, summary
    assert slot_accuracy >= MIN_REQUIRED_SLOT_ACCURACY, summary
    assert violations == [], summary
