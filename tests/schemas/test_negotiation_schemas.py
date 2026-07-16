"""Tests for the AgentTrust negotiation vocabulary schemas (RFC-0002, U1).

Test-first: these define the contract for ``schemas/offer.schema.json`` and
``schemas/counter-offer.schema.json`` before the schemas exist.

The load-bearing invariant (R2 / KTD-N2): a provider's private minimum
(reservation) price has NO place in any serialized object. Both schemas set
``additionalProperties: false``, so an offer or counter carrying a
``min_price`` / ``reservation`` field is rejected by validation — the schema
itself refuses to let the reservation cross the wire.
"""

import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schemas"


def load_schema(name):
    return json.loads((SCHEMA_DIR / ("%s.schema.json" % name)).read_text())


def valid_offer():
    return {
        "type": "task.offer",
        "task_id": "task-abc",
        "capability_id": "terraform.generate",
        "price": 5,
        "currency": "USD",
        "delivery": "immediate",
    }


def valid_counter():
    return {
        "type": "task.counter",
        "task_id": "task-abc",
        "proposed_price": 4,
    }


# ---------------------------------------------------------------------------
# Schemas are well-formed draft-07
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["offer", "counter-offer"])
def test_schema_is_valid_draft7(name):
    Draft7Validator.check_schema(load_schema(name))


@pytest.mark.parametrize(
    "name,expected_id",
    [
        ("offer", "https://agenttrust.example/schemas/offer.schema.json"),
        (
            "counter-offer",
            "https://agenttrust.example/schemas/counter-offer.schema.json",
        ),
    ],
)
def test_schema_id(name, expected_id):
    assert load_schema(name)["$id"] == expected_id


# ---------------------------------------------------------------------------
# Offer: happy path + the reservation-privacy invariant (R2)
# ---------------------------------------------------------------------------


def test_valid_offer_accepted():
    Draft7Validator(load_schema("offer")).validate(valid_offer())


def test_offer_with_reservation_field_is_rejected():
    # R2 / KTD-N2: the private minimum must never appear in a serialized offer.
    validator = Draft7Validator(load_schema("offer"))
    for leaked in ("min_price", "reservation", "floor", "minimum_price"):
        bad = valid_offer()
        bad[leaked] = 3
        errors = list(validator.iter_errors(bad))
        assert errors, "offer carrying %r must be rejected" % leaked


def test_offer_negative_or_nonnumeric_price_rejected():
    validator = Draft7Validator(load_schema("offer"))
    for bad_price in (-1, "cheap", None):
        bad = valid_offer()
        bad["price"] = bad_price
        assert list(validator.iter_errors(bad)), "price=%r must fail" % (bad_price,)


def test_offer_missing_required_fields_rejected():
    validator = Draft7Validator(load_schema("offer"))
    for field in ("type", "task_id", "capability_id", "price", "currency"):
        bad = valid_offer()
        del bad[field]
        assert list(validator.iter_errors(bad)), "missing %s must fail" % field


def test_offer_wrong_type_discriminator_rejected():
    bad = valid_offer()
    bad["type"] = "task.accept"
    assert list(Draft7Validator(load_schema("offer")).iter_errors(bad))


# ---------------------------------------------------------------------------
# Counter-offer: happy path + shape
# ---------------------------------------------------------------------------


def test_valid_counter_accepted():
    Draft7Validator(load_schema("counter-offer")).validate(valid_counter())


def test_counter_with_reservation_field_is_rejected():
    validator = Draft7Validator(load_schema("counter-offer"))
    bad = valid_counter()
    bad["min_price"] = 2
    assert list(validator.iter_errors(bad))


def test_counter_negative_price_rejected():
    bad = valid_counter()
    bad["proposed_price"] = -5
    assert list(Draft7Validator(load_schema("counter-offer")).iter_errors(bad))


def test_counter_missing_required_fields_rejected():
    validator = Draft7Validator(load_schema("counter-offer"))
    for field in ("type", "task_id", "proposed_price"):
        bad = valid_counter()
        del bad[field]
        assert list(validator.iter_errors(bad)), "missing %s must fail" % field
