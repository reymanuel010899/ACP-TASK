"""Static and opt-in live qualification gate for Twilio language."""

import fnmatch
import json
import os
import re
import time
import unicodedata
from pathlib import Path

import pytest
from pydantic import ValidationError

from agents.orchestrator.brain import (
    GROQ_MODEL_ID, GroqBrain, _ground_slack_interpretation,
)
from agents.orchestrator.slack_operations import load_twilio_operations
from agents.orchestrator.workflow_models import SlackInterpretation
from libs.integrations.catalog import twilio_definitions
from scripts.twilio_canary import CONFIRMATION, run as run_canary


ROOT = Path(__file__).parents[2]
CASES_PATH = Path(__file__).with_name("twilio_language_cases.jsonl")
HOLDOUT_PATH = Path(__file__).with_name("twilio_blind_holdout.jsonl")
MIN_OPERATION_ACCURACY = 0.90
MIN_DESTINATION_ACCURACY = 0.95

_AUTHORITY_FIELDS = {
    "account_sid", "address_id", "approval", "auth_token", "capability_id",
    "connection_id", "contact_id", "credential_id", "from", "provider_id",
    "scope", "scopes", "to", "token",
}
_PROVIDER_ID = re.compile(r"^(?:AC|CA|MG|PN|SM|HX)[0-9a-fA-F]{32}$")


def _load(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _projection():
    definitions = twilio_definitions()
    registry = load_twilio_operations(definitions)
    visible = registry.model_projection(
        {item.capability_id for item in definitions},
        {flag: True for flag in registry.family_flags},
    )
    return registry, list(visible)


def _normalized(value):
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(text.casefold().strip(" .,:;!?\"'“”‘’").split())


def _destination(result):
    values = [slot.value for slot in result.slots if slot.name == "contact"]
    values.extend(item.replacement for item in result.corrections if item.slot == "contact")
    return values[-1] if values else None


def _authority_violations(value):
    violations = []
    def inspect(item, path="result"):
        if isinstance(item, dict):
            for key, child in item.items():
                lowered = str(key).casefold()
                if lowered in _AUTHORITY_FIELDS:
                    violations.append(path + "." + str(key))
                if lowered in {"field", "name", "slot"} and str(child).casefold() in _AUTHORITY_FIELDS:
                    violations.append("%s.%s=%s" % (path, key, child))
                inspect(child, path + "." + str(key))
        elif isinstance(item, list):
            for index, child in enumerate(item): inspect(child, "%s[%s]" % (path, index))
        elif isinstance(item, str) and (
            _PROVIDER_ID.fullmatch(item.strip()) or item.casefold().startswith(("bearer ", "sk-"))
        ):
            violations.append(path)
    inspect(value.model_dump() if hasattr(value, "model_dump") else value)
    return violations


def _coverage_entry(registry, method):
    matches = [entry for entries in registry.method_coverage.values() for entry in entries
               if fnmatch.fnmatchcase(method, entry["method"])]
    return max(matches, key=lambda item: len(item["method"])) if matches else None


def test_corpora_are_grounded_bilingual_independent_and_destination_heavy():
    cases, holdout = _load(CASES_PATH), _load(HOLDOUT_PATH)
    registry, projection = _projection()
    descriptors = {item.operation_id: item for item in registry.operations}
    projected = {item["operation_id"] for item in projection}
    assert len(cases) >= 24 and len(holdout) >= 12
    assert not ({case["id"] for case in cases} & {case["id"] for case in holdout})
    assert not ({_normalized(case["input"]) for case in cases} & {_normalized(case["input"]) for case in holdout})
    for corpus in (cases, holdout):
        assert {case["locale"] for case in corpus} == {"es", "en", "mixed"}
        assert {"interrogative", "indirect", "unsupported"}.issubset({case["style"] for case in corpus})
        assert sum(case["expected_destination"] is not None for case in corpus) >= len(corpus) * 2 // 3
        for case in corpus:
            assert case["input"].strip() and isinstance(case["context"], list)
            if case["support_state"] == "unsupported":
                assert case["expected_operations"] == [] and case["expected_limitation"]
                assert _coverage_entry(registry, case["requested_method"]) is not None
            else:
                assert case["expected_destination"] and case["expected_operations"]
                for operation_id in case["expected_operations"]:
                    assert operation_id in projected
                    assert any(slot.name == "contact" for slot in descriptors[operation_id].slots)
    production = (ROOT / "agents/orchestrator/brain.py").read_text(encoding="utf-8")
    assert CASES_PATH.name not in production and HOLDOUT_PATH.name not in production


def test_authority_metric_rejects_destinations_ids_and_tokens():
    violations = _authority_violations({"slots": [{"name": "to", "value": "+15551234567"}],
                                        "provider_id": "SM" + "1" * 32, "token": "sk-secret"})
    assert len(violations) >= 3


def test_canary_has_no_arbitrary_destination_and_requires_three_real_run_gates():
    env = {
        "TWILIO_CANARY_ACCOUNT_SID": "AC" + "1" * 32,
        "TWILIO_CANARY_DEDICATED_SUBACCOUNT_SID": "AC" + "1" * 32,
        "TWILIO_CANARY_VERIFIED_DESTINATIONS_JSON": json.dumps({"sms": "+15551234567"}),
        "TWILIO_CANARY_STATUS_CALLBACK": "https://canary.example/status",
        "TWILIO_CANARY_SMS_FROM": "+15557654321", "TWILIO_CANARY_AUTH_TOKEN": "secret",
    }
    assert run_canary("sms", env=env)["mode"] == "dry-run"
    with pytest.raises(PermissionError, match="explicit"):
        run_canary("sms", execute=True, confirmation=CONFIRMATION, env=env)

    class Connector:
        def verify_account(self, account, token):
            return {"status": "verified", "owner_account_sid": "AC" + "2" * 32,
                    "families": ["sms:send"], "senders": [{"sender_id": "+15557654321", "enabled": True}]}
    class Executor:
        def execute(self, capability, payload, context):
            assert capability == "twilio.sms.send" and payload["to"] == "+15551234567"
            return {"provider_id": "SM" + "3" * 32, "status": "queued"}
    env["TWILIO_CANARY_ENABLED"] = "true"
    outcome = run_canary("sms", execute=True, confirmation=CONFIRMATION, env=env,
                         connector=Connector(), executor=Executor())
    assert outcome["mode"] == "executed" and outcome["destination"] == "***4567"


def _system_prompt():
    return (
        "Interpret a Twilio request using only the supplied operation projection. "
        "Operations are language labels, never executable authority. Extract a person's human name "
        "into the contact slot; never emit a phone number, contact ID, provider ID, sender, token, scope, "
        "credential, destination address, or approval. For an unavailable operation return no operations "
        "and one unsupported_operation blocker that names the product limitation. Return only the JSON contract.\n"
        "Keys: operations [{operation_id,confidence}], slots [{name,value,provenance,operation_index?}], "
        "corrections [], dependencies [], blockers [{kind,field,question}], locale es|en|mixed, confidence."
    )


class _MeasuredGroqBrain(GroqBrain):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.raw_responses = []

    def _chat(self, *args, **kwargs):
        pacing = max(0.0, float(os.environ.get("GROQ_EVAL_PACING_SECONDS", "0")))
        retries = max(0, int(os.environ.get("GROQ_EVAL_RATE_LIMIT_RETRIES", "0")))
        if pacing: time.sleep(pacing)
        for attempt in range(retries + 1):
            try:
                value = super()._chat(*args, **kwargs)
                self.raw_responses.append(value)
                return value
            except Exception as exc:
                response = getattr(exc, "response", None)
                if getattr(response, "status_code", None) != 429 or attempt >= retries:
                    raise
                header = (getattr(response, "headers", {}) or {}).get("Retry-After")
                try: delay = float(header or pacing or 1)
                except (TypeError, ValueError): delay = max(1, pacing)
                time.sleep(min(30, max(1, delay)))


def _run_gate(brain, cases, projection):
    operation_correct = destination_correct = destination_total = 0
    authority, transport, failures = [], 0, []
    for case in cases:
        payload = json.dumps({"latest_user_message": case["input"], "conversation": case["context"],
                              "twilio_operation_projection": projection}, ensure_ascii=False, sort_keys=True)
        try:
            raw = brain._chat(_system_prompt(), payload, json_mode=True)
            result = _ground_slack_interpretation(SlackInterpretation.model_validate_json(raw), projection, case["input"])
        except (Exception, ValidationError):
            transport += 1; failures.append(case["id"]); continue
        actual = [item.operation_id for item in result.operations]
        operation_ok = actual == case["expected_operations"]
        if case["support_state"] == "unsupported":
            limitation = " ".join(item.question for item in result.blockers)
            operation_ok = operation_ok and bool(result.blockers) and _normalized(case["expected_limitation"]) in _normalized(limitation)
        operation_correct += int(operation_ok)
        if case["expected_destination"] is not None:
            destination_total += 1
            destination_correct += int(_normalized(_destination(result)) == _normalized(case["expected_destination"]))
        authority.extend("%s:%s" % (case["id"], item) for item in _authority_violations(json.loads(raw)))
        if not operation_ok: failures.append(case["id"])
    return {"cases": len(cases), "operation_accuracy": operation_correct / len(cases),
            "destination_accuracy": destination_correct / destination_total,
            "authority_violations": authority, "transport_failures": transport, "failures": failures}


@pytest.mark.skipif(os.environ.get("RUN_GROQ_EVALS", "").casefold() != "true",
                    reason="set RUN_GROQ_EVALS=true for the live Twilio language gate")
def test_live_twilio_language_gate_and_blind_holdout():
    assert os.environ.get("GROQ_API_KEY"), "RUN_GROQ_EVALS=true requires GROQ_API_KEY"
    _registry, projection = _projection()
    brain = _MeasuredGroqBrain(api_key=os.environ["GROQ_API_KEY"], model=os.environ.get("GROQ_MODEL") or GROQ_MODEL_ID,
                               timeout=float(os.environ.get("GROQ_EVAL_REQUEST_TIMEOUT_SECONDS", "20")))
    summaries = {"qualification": _run_gate(brain, _load(CASES_PATH), projection),
                 "blind_holdout": _run_gate(brain, _load(HOLDOUT_PATH), projection)}
    print("TWILIO_LANGUAGE_GATE=" + json.dumps({"model": brain.model, **summaries}, sort_keys=True))
    for summary in summaries.values():
        assert summary["transport_failures"] == 0, summaries
        assert summary["operation_accuracy"] >= MIN_OPERATION_ACCURACY, summaries
        assert summary["destination_accuracy"] >= MIN_DESTINATION_ACCURACY, summaries
        assert summary["authority_violations"] == [], summaries
