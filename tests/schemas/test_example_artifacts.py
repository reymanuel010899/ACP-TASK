"""The published example artifacts (U8) must validate against their schemas.

Per the plan, U8 has no behavior of its own — but the example JSON files under
``examples/`` are advertised as spec-faithful, so this locks that promise in
CI. They are derived from the real U1/U2 schemas, not hand-written guesses.
"""

import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator

ROOT = Path(__file__).resolve().parents[2]

# (example file, schema file) pairs.
EXAMPLES = [
    ("examples/evidence.json", "schemas/evidence.schema.json"),
    ("examples/verification-result.json", "schemas/verification-result.schema.json"),
    ("examples/reputation-record.json", "schemas/reputation-record.schema.json"),
]


@pytest.mark.parametrize("example,schema", EXAMPLES)
def test_example_validates_against_schema(example, schema):
    instance = json.loads((ROOT / example).read_text())
    validator = Draft7Validator(json.loads((ROOT / schema).read_text()))
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
    assert not errors, "%s: %s" % (
        example,
        "; ".join("%s %s" % (list(e.path), e.message) for e in errors),
    )
