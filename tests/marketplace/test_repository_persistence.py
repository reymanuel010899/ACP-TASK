"""Tests for Postgres-backed Marketplace persistence (unit U6, ``marketplace``
schema -- migrations/0007_marketplace.sql, apps/marketplace/server/repository.py).

Needs migrations/0001-0007 already applied against a reachable Postgres --
see tests/vault/test_persistence.py's identical convention. Since every test
in this DIRECTORY already assumes a live Postgres (tests/marketplace/
conftest.py truncates marketplace.* before each test), these tests use
``libs.db.Database()`` directly rather than a separate skip-if-unreachable
fixture.

Test scenarios:
    * Happy path   -- test_task_lifecycle_persists_across_a_restart
    * Edge case    -- test_negotiation_thread_is_paginated_not_one_blob
    * Integration  -- test_second_work_result_creates_new_row_not_overwrite
    * Integration  -- test_offer_and_counter_offer_validate_against_real_schemas
    * Integration  -- test_single_round_counter_offer_enforced
"""

import json
import pathlib

import jsonschema
import pytest

from apps.marketplace.server.repository import MarketplaceRepository
from libs.db import Database

_SCHEMAS_DIR = pathlib.Path(__file__).resolve().parents[2] / "schemas"
_OFFER_SCHEMA = json.loads((_SCHEMAS_DIR / "offer.schema.json").read_text())
_COUNTER_OFFER_SCHEMA = json.loads(
    (_SCHEMAS_DIR / "counter-offer.schema.json").read_text()
)


def _new_repository():
    """A fresh MarketplaceRepository backed by its own Database/connection
    pool -- the same shape of object a freshly-started process would
    construct, used to simulate "the service restarted" without actually
    killing a process (mirrors tests/vault/test_persistence.py)."""
    return MarketplaceRepository(Database())


# ---------------------------------------------------------------------------
# 1. Happy path: open -> accepted -> delivered -> completed persists and
#    survives a simulated restart (fresh repository instance, same DB).
# ---------------------------------------------------------------------------


def test_task_lifecycle_persists_across_a_restart():
    author = "user:lifecycle-author"
    worker = "agent:lifecycle-worker"
    repo = _new_repository()

    task = repo.create_task(author, "write the quarterly report")
    task_id = task["id"]
    assert task["status"] == "open"

    accepted, error = repo.accept_task(task_id, worker)
    assert error is None
    assert accepted["status"] == "accepted"
    assert accepted["worker_principal"] == worker

    delivered, error = repo.submit_work_result(
        task_id, worker, "draft attached", evidence={"pages": 4}
    )
    assert error is None
    assert delivered["status"] == "delivered"
    assert delivered["work_result"]["result_summary"] == "draft attached"
    assert delivered["work_result"]["evidence"] == {"pages": 4}

    completed, error = repo.complete_task(task_id, author, "great work")
    assert error is None
    assert completed["status"] == "completed"
    assert completed["outcome"] == "great work"

    # "Restart": throw away this repository/pool, build a brand new one
    # against the same DSN, and confirm everything is still there.
    restarted = _new_repository()
    fetched = restarted.get_task(task_id)
    assert fetched is not None
    assert fetched["status"] == "completed"
    assert fetched["author_principal"] == author
    assert fetched["worker_principal"] == worker
    assert fetched["outcome"] == "great work"


# ---------------------------------------------------------------------------
# 2. Edge case: a negotiation thread with many messages returns in order,
#    paginated -- not one unbounded blob.
# ---------------------------------------------------------------------------


def test_negotiation_thread_is_paginated_not_one_blob():
    author = "user:paginate-author"
    worker = "agent:paginate-worker"
    repo = _new_repository()

    task = repo.create_task(author, "a long negotiation")
    task_id = task["id"]
    repo.accept_task(task_id, worker)

    for i in range(25):
        sender = author if i % 2 == 0 else worker
        _, _, error = repo.add_negotiation_message(
            task_id, sender, "message %d" % i
        )
        assert error is None

    # Full read (default limit) is in order.
    full = repo.list_negotiations(task_id)
    assert len(full) == 25
    assert [m["message"] for m in full] == ["message %d" % i for i in range(25)]

    # Paginated reads: no page is the whole unbounded set, and pages
    # together reconstruct the same order.
    page1 = repo.list_negotiations(task_id, skip=0, limit=10)
    page2 = repo.list_negotiations(task_id, skip=10, limit=10)
    page3 = repo.list_negotiations(task_id, skip=20, limit=10)
    assert len(page1) == 10
    assert len(page2) == 10
    assert len(page3) == 5
    assert [m["message"] for m in page1 + page2 + page3] == (
        [m["message"] for m in full]
    )


# ---------------------------------------------------------------------------
# 3. Integration: a second work-result submission creates a NEW row rather
#    than overwriting the first; the single-object view returns the latest.
# ---------------------------------------------------------------------------


def test_second_work_result_creates_new_row_not_overwrite():
    author = "user:redelivery-author"
    worker = "agent:redelivery-worker"
    repo = _new_repository()

    task = repo.create_task(author, "iterative work")
    task_id = task["id"]
    repo.accept_task(task_id, worker)

    first, error = repo.submit_work_result(
        task_id, worker, "first draft", evidence={"version": 1}
    )
    assert error is None
    assert first["work_result"]["result_summary"] == "first draft"

    # A second delivery is only possible once the task is "accepted" again
    # in this app's state machine, but the REPOSITORY layer's history
    # invariant is what's under test here: insert directly to simulate two
    # deliveries against the same task without round-tripping through the
    # HTTP status-machine guard (that guard is tested at the app.py layer
    # already, in tests/marketplace/test_marketplace_app.py's equivalents).
    with repo._db.transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE marketplace.tasks SET status = 'accepted' "
                "WHERE task_id = %s",
                (task_id,),
            )

    second, error = repo.submit_work_result(
        task_id, worker, "revised draft", evidence={"version": 2}
    )
    assert error is None
    assert second["work_result"]["result_summary"] == "revised draft"

    history = repo.list_work_results(task_id)
    assert len(history) == 2
    assert history[0]["result_summary"] == "first draft"
    assert history[1]["result_summary"] == "revised draft"

    # The single-object view (what GET /api/tasks/{id} returns) is the
    # LATEST row, not the first.
    latest = repo.get_task(task_id)
    assert latest["work_result"]["result_summary"] == "revised draft"
    assert latest["work_result"]["evidence"] == {"version": 2}


# ---------------------------------------------------------------------------
# 4. Integration: an Offer and a CounterOffer round-trip through the REAL
#    schemas/offer.schema.json / schemas/counter-offer.schema.json JSON
#    Schema validation (RFC-0002 §6 adoption).
# ---------------------------------------------------------------------------


def test_offer_and_counter_offer_validate_against_real_schemas():
    author = "user:negotiate-author"
    provider = "agent:negotiate-provider"
    repo = _new_repository()

    task = repo.create_task(author, "translate a document")
    task_id = task["id"]

    offer_wire = {
        "type": "task.offer",
        "task_id": task_id,
        "capability_id": "marketplace.tasks",
        "price": 50,
        "currency": "USD",
        "delivery": "2 days",
    }
    # Validates against the REAL schema file -- not a hand-rolled lookalike.
    jsonschema.validate(instance=offer_wire, schema=_OFFER_SCHEMA)

    offer, error = repo.create_offer(
        task_id, provider, offer_wire["price"], offer_wire["currency"],
        offer_wire["delivery"],
    )
    assert error is None
    assert offer["price"] == 50.0

    counter_wire = {
        "type": "task.counter",
        "task_id": task_id,
        "proposed_price": 35,
    }
    jsonschema.validate(instance=counter_wire, schema=_COUNTER_OFFER_SCHEMA)

    counter, error = repo.create_counter_offer(
        task_id, counter_wire["proposed_price"], "USD"
    )
    assert error is None
    assert counter["proposed_price"] == 35.0

    # The reservation/floor is never part of either wire shape by
    # construction: additionalProperties is false, so a leaked reservation
    # field is a validation error, not merely an application-level omission.
    leaked = dict(offer_wire, reservation_price=10)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=leaked, schema=_OFFER_SCHEMA)


def test_single_round_counter_offer_enforced():
    """RFC-0002 §6.1: a requester MAY send exactly one task.counter per
    task; a second is rejected rather than silently re-evaluated (closing
    the one-bit price-discovery oracle the RFC calls out)."""
    author = "user:single-round-author"
    provider = "agent:single-round-provider"
    repo = _new_repository()

    task = repo.create_task(author, "a single-round negotiation")
    task_id = task["id"]
    repo.create_offer(task_id, provider, 100, "USD")

    _, error = repo.create_counter_offer(task_id, 80, "USD")
    assert error is None

    _, error = repo.create_counter_offer(task_id, 79, "USD")
    assert error == "already_countered"

    assert len(repo.list_counter_offers(task_id)) == 1


def test_counter_offer_without_a_standing_offer_is_rejected():
    repo = _new_repository()
    task = repo.create_task("user:no-offer-author", "nothing offered yet")
    _, error = repo.create_counter_offer(task["id"], 10, "USD")
    assert error == "no_standing_offer"
