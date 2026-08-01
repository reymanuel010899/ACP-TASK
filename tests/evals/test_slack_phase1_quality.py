"""Independent Phase 1 Slack language-quality exit gate."""

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


CASES_PATH = Path(__file__).with_name("slack_phase1_quality_cases.jsonl")
PROJECT_ROOT = Path(__file__).parents[2]
MIN_OPERATION_ACCURACY = 0.90
MIN_REQUIRED_SLOT_ACCURACY = 0.85

_AUTHORITY_FIELDS = {
    "approval", "capability_id", "connection_id", "credential_id",
    "provider_id", "scope", "scopes", "team_id", "token", "user_id",
    "channel_id", "message_ts",
}
_PROVIDER_ID = re.compile(r"^(?:[BCDEGUTW][A-Z0-9]{8,}|\d{10,}\.\d+)$")


def _load_cases():
    return [
        json.loads(line)
        for line in CASES_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _registry_and_projection():
    definitions = slack_definitions()
    registry = load_slack_operations(definitions)
    projection = registry.model_projection(
        {definition.capability_id for definition in definitions},
        {flag: True for flag in registry.family_flags},
    )
    return registry, list(projection)


def _normalized(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.casefold().strip().lstrip("#@").strip(" \t\r\n:;,.!?\"'“”‘’")
    return " ".join(text.split())


def _slot_matches(expected, actual):
    expected = _normalized(expected)
    actual = _normalized(actual)
    return bool(
        expected == actual
        or (len(expected) >= 5 and expected in actual)
    )


def _actual_slots(result):
    values = {}
    for slot in result.slots:
        values.setdefault(slot.name, []).append(slot.value)
    for correction in result.corrections:
        values[correction.slot] = [correction.replacement]
    return values


def _authority_violations(value):
    violations = []

    def inspect(value, path="result"):
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key).casefold() in _AUTHORITY_FIELDS:
                    violations.append("%s.%s" % (path, key))
                if (
                    str(key).casefold() in {"field", "name", "slot"}
                    and str(item).casefold() in _AUTHORITY_FIELDS
                ):
                    violations.append("%s.%s=%s" % (path, key, item))
                inspect(item, "%s.%s" % (path, key))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                inspect(item, "%s[%s]" % (path, index))
        elif isinstance(value, str):
            candidate = value.strip().lstrip("#@")
            if (
                _PROVIDER_ID.fullmatch(candidate)
                or candidate.casefold().startswith(("xox", "bearer "))
            ):
                violations.append(path)

    inspect(value.model_dump() if hasattr(value, "model_dump") else value)
    return violations


def test_phase1_quality_corpus_is_frozen_grounded_and_independent():
    cases = _load_cases()
    registry, projection = _registry_and_projection()
    descriptors = {item.operation_id: item for item in registry.operations}
    coverage = {
        item["method"]: item
        for entries in registry.method_coverage.values()
        for item in entries
    }
    projected = {item["operation_id"] for item in projection}

    assert len(cases) >= 18
    assert len({case["id"] for case in cases}) == len(cases)
    locale_counts = {
        locale: sum(case["locale"] == locale for case in cases)
        for locale in ("es", "en", "mixed")
    }
    assert all(count >= 4 for count in locale_counts.values())
    style_counts = {
        style: sum(case["style"] == style for case in cases)
        for style in {case["style"] for case in cases}
    }
    assert {
        "typo", "fragment", "correction", "unsupported",
    }.issubset(style_counts)
    assert style_counts["typo"] >= 3
    assert style_counts["fragment"] >= 2
    assert style_counts["unsupported"] >= 4
    assert {case["support_state"] for case in cases} == {
        "supported", "conditional", "unsupported",
    }

    for case in cases:
        assert set(case).issubset({
            "id", "locale", "style", "input", "context",
            "expected_operations", "expected_slots", "support_state",
            "requested_method",
        })
        assert case["input"].strip()
        assert isinstance(case["context"], list)
        assert isinstance(case["expected_slots"], dict)
        assert all(
            not _PROVIDER_ID.fullmatch(str(value).lstrip("#@"))
            for value in case["expected_slots"].values()
        )
        if case["support_state"] == "unsupported":
            assert case["expected_operations"] == []
            method = coverage[case["requested_method"]]
            assert method["state"] in {"planned", "dormant"}
            continue
        assert "requested_method" not in case
        assert case["expected_operations"]
        for operation_id in case["expected_operations"]:
            assert operation_id in projected
            assert descriptors[operation_id].availability == case["support_state"]
        declared_slots = {
            slot.name
            for operation_id in case["expected_operations"]
            for slot in descriptors[operation_id].slots
        }
        assert set(case["expected_slots"]).issubset(declared_slots)

    # The evaluation sample is never imported or named by production routing.
    brain_source = (
        PROJECT_ROOT / "agents" / "orchestrator" / "brain.py"
    ).read_text(encoding="utf-8")
    assert CASES_PATH.name not in brain_source


def test_authority_metric_inspects_raw_fields_names_and_provider_ids():
    violations = _authority_violations({
        "operations": [{
            "operation_id": "slack.message.send",
            "capability_id": "slack.message.send",
        }],
        "slots": [
            {"name": "channel_id", "value": "general"},
            {"name": "channel", "value": "C123456789"},
        ],
    })

    assert len(violations) == 3


class _MeasuredGroqBrain(GroqBrain):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.live_calls = 0
        self.failed_calls = 0
        self.raw_responses = []

    def _chat(self, *args, **kwargs):
        pacing = max(0.0, float(os.environ.get("GROQ_EVAL_PACING_SECONDS", "0")))
        retries = max(0, int(os.environ.get("GROQ_EVAL_RATE_LIMIT_RETRIES", "0")))
        max_retry_after = max(
            1.0,
            float(os.environ.get("GROQ_EVAL_MAX_RETRY_AFTER_SECONDS", "30")),
        )
        if pacing:
            time.sleep(pacing)
        for attempt in range(retries + 1):
            try:
                response = super()._chat(*args, **kwargs)
            except Exception as exc:
                response_obj = getattr(exc, "response", None)
                status = getattr(response_obj, "status_code", None)
                if status == 429 and attempt < retries:
                    retry_after = (getattr(response_obj, "headers", {}) or {}).get(
                        "Retry-After"
                    )
                    try:
                        delay = max(pacing, float(retry_after or 0))
                    except (TypeError, ValueError):
                        delay = pacing
                    time.sleep(min(max_retry_after, max(1.0, delay)))
                    continue
                self.failed_calls += 1
                raise
            self.live_calls += 1
            self.raw_responses.append(response)
            return response


@pytest.mark.skipif(
    os.environ.get("RUN_GROQ_EVALS", "").casefold() != "true",
    reason="set RUN_GROQ_EVALS=true to run the live Groq language gate",
)
def test_live_groq_phase1_language_exit_gate():
    api_key = os.environ.get("GROQ_API_KEY")
    assert api_key, "RUN_GROQ_EVALS=true requires GROQ_API_KEY"
    cases = _load_cases()
    _registry, projection = _registry_and_projection()
    brain = _MeasuredGroqBrain(
        api_key=api_key,
        model=os.environ.get("GROQ_MODEL") or GROQ_MODEL_ID,
        timeout=float(os.environ.get("GROQ_EVAL_REQUEST_TIMEOUT_SECONDS", "15")),
    )

    correct_operations = 0
    correct_slots = 0
    expected_slots = 0
    authority_violations = []
    failures = []
    for index, case in enumerate(cases, start=1):
        print(
            "SLACK_PHASE1_CASE=%s/%s:%s" % (index, len(cases), case["id"]),
            flush=True,
        )
        failures_before = brain.failed_calls
        responses_before = len(brain.raw_responses)
        result = brain.understand_slack(case["input"], {
            "conversation": case["context"],
            "slack_operation_projection": projection,
        })
        transport_failed = brain.failed_calls > failures_before
        actual_operations = [] if transport_failed else [
            operation.operation_id for operation in result.operations
        ]
        operation_correct = actual_operations == case["expected_operations"]
        correct_operations += int(operation_correct)
        actual_slots = {} if transport_failed else _actual_slots(result)
        missed_slots = []
        for name, expected in case["expected_slots"].items():
            expected_slots += 1
            matches = any(
                _slot_matches(expected, actual)
                for actual in actual_slots.get(name, ())
            )
            correct_slots += int(matches)
            if not matches:
                missed_slots.append(name)
        violations = _authority_violations(result)
        if len(brain.raw_responses) > responses_before:
            try:
                raw_payload = json.loads(brain.raw_responses[-1])
            except (TypeError, ValueError):
                raw_payload = None
            if raw_payload is not None:
                violations.extend(
                    "raw.%s" % violation
                    for violation in _authority_violations(raw_payload)
                )
        authority_violations.extend(
            "%s:%s" % (case["id"], violation)
            for violation in violations
        )
        if not operation_correct or missed_slots:
            failures.append({
                "id": case["id"],
                "transport_failed": transport_failed,
                "expected_operations": case["expected_operations"],
                "actual_operations": actual_operations,
                "missed_slots": missed_slots,
            })

    operation_accuracy = correct_operations / len(cases)
    slot_accuracy = correct_slots / expected_slots
    summary = {
        "model": brain.model,
        "cases": len(cases),
        "operation_accuracy": round(operation_accuracy, 4),
        "required_slot_accuracy": round(slot_accuracy, 4),
        "authority_field_violations": len(authority_violations),
        "transport_failures": brain.failed_calls,
        "failures": failures,
    }
    print("SLACK_PHASE1_LANGUAGE_GATE=" + json.dumps(summary, sort_keys=True))

    assert brain.live_calls + brain.failed_calls == len(cases), summary
    assert brain.failed_calls == 0, summary
    assert operation_accuracy >= MIN_OPERATION_ACCURACY, summary
    assert slot_accuracy >= MIN_REQUIRED_SLOT_ACCURACY, summary
    assert authority_violations == [], summary
