"""One-shot blind holdout for the Phase 1 typed Slack interpretation gate."""

import json
import os
import re
import time
import unicodedata
from pathlib import Path

import pytest

from agents.orchestrator.brain import GROQ_MODEL_ID, GroqBrain
from agents.orchestrator.slack_operations import load_slack_operations
from libs.integrations.catalog import slack_definitions


CASES_PATH = Path(__file__).with_name("slack_phase1_blind_holdout_v2.jsonl")
MIN_OPERATION_ACCURACY = 0.90
MIN_REQUIRED_SLOT_ACCURACY = 0.85
_MISSING_MARKERS = (
    "unspecified", "clarification required", "sin especificar",
    "requiere aclaracion",
)
_AUTHORITY_FIELDS = {
    "approval", "capability_id", "connection_id", "credential_id",
    "provider_id", "scope", "scopes", "team_id", "token", "user_id",
    "channel_id", "message_ts",
}
_PROVIDER_ID = re.compile(r"^(?:[BCDEGUTW][A-Z0-9]{8,}|\d{10,}\.\d+)$")


def _cases():
    return [
        json.loads(line)
        for line in CASES_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _projection():
    definitions = slack_definitions()
    registry = load_slack_operations(definitions)
    return registry, list(registry.model_projection(
        {definition.capability_id for definition in definitions},
        {flag: True for flag in registry.family_flags},
    ))


def _normalize(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.casefold().strip().lstrip("#@").strip(" \t\r\n:;,.!?\"'“”‘’")
    return " ".join(text.split())


def _matches(expected, actual):
    expected, actual = _normalize(expected), _normalize(actual)
    if expected == actual or (len(expected) >= 5 and expected in actual):
        return True
    expected_digits = re.findall(r"\d+", expected)
    return bool(expected_digits and expected_digits == re.findall(r"\d+", actual))


def _is_missing_expectation(value):
    normalized = _normalize(value)
    return any(marker in normalized for marker in _MISSING_MARKERS)


def _authority_violations(value):
    violations = []

    def inspect(item, path="result"):
        if isinstance(item, dict):
            for key, nested in item.items():
                if str(key).casefold() in _AUTHORITY_FIELDS:
                    violations.append("%s.%s" % (path, key))
                inspect(nested, "%s.%s" % (path, key))
        elif isinstance(item, list):
            for index, nested in enumerate(item):
                inspect(nested, "%s[%s]" % (path, index))
        elif isinstance(item, str):
            candidate = item.strip().lstrip("#@")
            if _PROVIDER_ID.fullmatch(candidate) or candidate.casefold().startswith(
                ("xox", "bearer ")
            ):
                violations.append(path)

    inspect(value.model_dump() if hasattr(value, "model_dump") else value)
    return violations


def _actual_slots(result, registry):
    declared = {
        operation.operation_id: {slot.name for slot in operation.slots}
        for operation in registry.operations
    }
    operations = [operation.operation_id for operation in result.operations]
    values = {}

    def add(name, value, operation_index):
        if operation_index is None:
            candidates = [
                index for index, operation_id in enumerate(operations)
                if name in declared.get(operation_id, set())
            ]
            if len(candidates) != 1:
                return
            operation_index = candidates[0]
        values.setdefault((operation_index, name), []).append(value)

    for slot in result.slots:
        add(slot.name, slot.value, slot.operation_index)
    for correction in result.corrections:
        values[(correction.operation_index, correction.slot)] = [
            correction.replacement
        ]
    return values


class _MeasuredBrain(GroqBrain):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.live_calls = 0
        self.failed_calls = 0
        self.raw_responses = []

    def _chat(self, *args, **kwargs):
        pacing = max(0.0, float(os.environ.get("GROQ_EVAL_PACING_SECONDS", "0")))
        retries = max(0, int(os.environ.get("GROQ_EVAL_RATE_LIMIT_RETRIES", "0")))
        retry_cap = max(
            1.0, float(os.environ.get("GROQ_EVAL_MAX_RETRY_AFTER_SECONDS", "30"))
        )
        if pacing:
            time.sleep(pacing)
        for attempt in range(retries + 1):
            try:
                response = super()._chat(*args, **kwargs)
            except Exception as exc:
                response_obj = getattr(exc, "response", None)
                if getattr(response_obj, "status_code", None) == 429 and attempt < retries:
                    raw_delay = (getattr(response_obj, "headers", {}) or {}).get(
                        "Retry-After"
                    )
                    try:
                        delay = max(pacing, float(raw_delay or 0))
                    except (TypeError, ValueError):
                        delay = pacing
                    time.sleep(min(retry_cap, max(1.0, delay)))
                    continue
                self.failed_calls += 1
                raise
            self.live_calls += 1
            self.raw_responses.append(response)
            return response


def test_blind_holdout_v2_is_well_formed_and_manifest_grounded():
    cases = _cases()
    registry, _model_projection = _projection()
    runtime_operations = {operation.operation_id for operation in registry.operations}
    method_coverage = {
        item["method"]: item
        for entries in registry.method_coverage.values()
        for item in entries
    }

    assert len(cases) == 24
    assert len({case["id"] for case in cases}) == len(cases)
    assert {case["locale"] for case in cases} == {"es", "en", "mixed"}
    assert all(isinstance(case["context"], str) for case in cases)
    for case in cases:
        if case["support_state"] in {"planned", "dormant"}:
            assert case["expected_operations"] == []
            assert method_coverage[case["requested_method"]]["state"] == case["support_state"]
        else:
            assert set(case["expected_operations"]).issubset(runtime_operations)
            assert "requested_method" not in case


@pytest.mark.skipif(
    os.environ.get("RUN_GROQ_BLIND_EVALS", "").casefold() != "true",
    reason="set RUN_GROQ_BLIND_EVALS=true for the one-shot live holdout",
)
def test_live_groq_phase1_blind_holdout_v2():
    api_key = os.environ.get("GROQ_API_KEY")
    assert api_key, "RUN_GROQ_BLIND_EVALS=true requires GROQ_API_KEY"
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
            "SLACK_PHASE1_BLIND_CASE=%s/%s:%s" % (
                case_index, len(cases), case["id"],
            ),
            flush=True,
        )
        failed_before = brain.failed_calls
        raw_before = len(brain.raw_responses)
        result = brain.understand_slack(case["input"], {
            "conversation": [{"role": "concierge", "text": case["context"]}],
            "slack_operation_projection": model_projection,
        })
        transport_failed = brain.failed_calls > failed_before
        actual_operations = [] if transport_failed else [
            operation.operation_id for operation in result.operations
        ]
        operation_correct = actual_operations == case["expected_operations"]
        correct_operations += int(operation_correct)
        actual = {} if transport_failed else _actual_slots(result, registry)
        blockers = {blocker.field for blocker in result.blockers}
        missed = []
        for operation_index, expected_operation in enumerate(case["expected_slots"]):
            for name, expected in expected_operation["slots"].items():
                expected_slots += 1
                if _is_missing_expectation(expected):
                    matched = name in blockers
                else:
                    matched = any(
                        _matches(expected, candidate)
                        for candidate in actual.get((operation_index, name), ())
                    )
                correct_slots += int(matched)
                if not matched:
                    missed.append("%s.%s" % (operation_index, name))
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
        violations.extend("%s:%s" % (case["id"], item) for item in case_violations)
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
    print("SLACK_PHASE1_BLIND_GATE=" + json.dumps(summary, sort_keys=True))

    assert brain.live_calls + brain.failed_calls == len(cases), summary
    assert brain.failed_calls == 0, summary
    assert operation_accuracy >= MIN_OPERATION_ACCURACY, summary
    assert slot_accuracy >= MIN_REQUIRED_SLOT_ACCURACY, summary
    assert violations == [], summary
