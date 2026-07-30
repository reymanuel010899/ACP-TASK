"""Postgres-backed storage for the Task Marketplace (unit U6, ``marketplace``
schema -- ``migrations/0007_marketplace.sql``).

Replaces ``apps/marketplace/server/app.py``'s in-memory ``self.tasks`` dict
(each value there was a hand-built record embedding unbounded
``negotiations``/``bids`` lists and a single overwritable ``work_result``
slot). This module keeps ``TaskService``'s exact pre-existing method
signatures and return-value shapes so ``apps/marketplace/server/app.py`` and
every existing test needed no HTTP-contract changes (R10) -- only how the
task dict gets built changed, not what it looks like on the wire.

FK wrinkles (principal + capability) -- same resolution pattern as
``vault/repository.py``'s ``_ensure_principal`` / ``registry/repository.py``'s
``_ensure_principal``/``_ensure_capability`` (see those modules' docstrings
for the full precedent this follows)
--------------------------------------------------------------------------
``author_principal_id``, ``worker_principal_id``, ``agent_principal_id``,
``from_principal_id``, ``submitted_by`` and ``provider_principal_id`` are all
foreign keys into ``identity.principals`` -- but no existing marketplace
caller has ever had to "register a principal" as a separate step before
posting a task, bidding, negotiating, or delivering. Every write path that
introduces a *new* principal_id calls :meth:`_ensure_principal` first, an
idempotent "insert a minimal row if one doesn't already exist" helper built
on ``libs.identity_repository.IdentityRepository`` (composition, not a second
hand-rolled INSERT path). ``capability_id`` on ``marketplace.tasks`` is
nullable and OPTIONAL in the existing API (task creation has never taken a
capability_id) -- :meth:`_ensure_capability` is therefore only ever called
when a caller actually supplies one, never speculatively.

``evidence_id`` on ``marketplace.work_results`` is a nullable FK into
``trust.evidence`` (U5). This module never fabricates a row there to satisfy
it -- real Evidence persistence is out of scope for this unit (U5's agent
already noted the same for ``trust.evidence`` itself); ``evidence_id`` stays
``NULL`` unless a caller supplies a real one (nothing does today).

The "outcome" wrinkle (no DDL column for it)
---------------------------------------------
The design doc's ``marketplace.tasks`` DDL has no ``outcome`` column, but the
pre-existing ``POST /api/negotiations/{task_id}/complete`` contract returns
one (free text describing how the task went, set only at completion time).
Rather than add an undocumented column for a single string, this module
reuses ``marketplace.work_results`` -- the table this unit's design doc
ALREADY introduces to hold "one row per delivery" -- since a task's
completion outcome genuinely IS its final delivery record: :meth:`complete_task`
inserts a ``work_results`` row (``result_summary=outcome``,
``submitted_by=`` the completing author, ``evidence_id=NULL``) rather than a
bespoke column. The HTTP-visible ``task["outcome"]`` field is then just "the
latest work_results row's ``result_summary``, but only once the task is
actually completed" -- never populated for an in-flight ``delivered`` task
whose worker submitted a result but whose author hasn't completed it yet.

The opaque P2P "evidence" blob (schema addition, see migrations/0007_marketplace.sql)
---------------------------------------------------------------------------------------
The pre-existing ``submit.work_result`` P2P contract accepts an arbitrary
JSON ``evidence`` object (e.g. ``{"word_count": 4200}``) that has never been,
and is not, a reference into ``trust.evidence`` -- it has no ``evidence_id``
shape at all. ``migrations/0007_marketplace.sql`` therefore adds one column
beyond the design doc's literal DDL, ``work_results.evidence jsonb``, purely
to round-trip this pre-existing opaque blob (R10); the design doc's own
``evidence_id`` column is untouched and stays NULL per the wrinkle above.

Uses ``libs.db.Database`` for every connection -- no hand-rolled psycopg
connection handling here (KTD1). New surrogate keys this module introduces
that have no pre-existing app-generated format (``offer_id``, ``counter_id``,
``work_result_id``) are ULIDs (KTD4); ``task_id`` is ALSO a ULID -- the
design doc annotates it explicitly (``docs/architecture/database-design.md``
§7: ``task_id text primary key, -- ULID``), overriding the pre-existing
in-memory ``str(uuid.uuid4())`` format ``apps/marketplace/server/app.py``
minted before this table existed (no test or caller depends on that
specific format, only on ``task["id"]`` being a non-empty string). ``bid_id``
keeps the pre-existing ``uuid.uuid4()`` string format instead -- the design
doc has no such override comment for it, so this mirrors
``vault/repository.py``'s identical ``credential_id`` precedent (an id
format callers might already depend on is left alone absent a stated reason
to change it). ``message_id`` is the DDL's own ``bigserial``, needing no
application-generated id at all.
"""

import json
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from psycopg.rows import dict_row

from libs.db import Database
from libs.identity_repository import IdentityRepository
from libs.ulid import generate_ulid


class MarketplaceRepository(object):
    """Repository for ``marketplace.*`` tables: tasks, offers,
    counter_offers, bids, negotiation_messages, work_results."""

    def __init__(self, db=None):
        # type: (Optional[Database]) -> None
        self._db = db or Database()
        self._identity = IdentityRepository(self._db)

    # -- FK-satisfying helpers (see module docstring) ----------------------

    def _ensure_principal(self, principal_id, principal_type):
        # type: (Optional[str], str) -> None
        if not principal_id:
            return
        if self._identity.principal_exists(principal_id):
            return
        try:
            self._identity.register_principal(principal_id, principal_type)
        except ValueError:
            pass  # lost a race with a concurrent ensure/registration -- fine

    def _ensure_capability(self, conn, capability_id):
        # type: (object, Optional[str]) -> None
        if not capability_id:
            return
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO catalog.capabilities
                    (capability_id, version, description)
                VALUES (%s, '0.0.0-auto',
                        'auto-registered by marketplace on first use')
                ON CONFLICT (capability_id) DO NOTHING
                """,
                (capability_id,),
            )

    # -- tasks --------------------------------------------------------------

    def create_task(self, principal_id, description, capability_id=None,
                    organization_id=None):
        # type: (str, str, Optional[str], Optional[str]) -> dict
        """Create a new task; return the full task view (R10 shape)."""
        self._ensure_principal(principal_id, "user")
        task_id = generate_ulid()
        with self._db.transaction() as conn:
            if capability_id:
                self._ensure_capability(conn, capability_id)
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    INSERT INTO marketplace.tasks
                        (task_id, organization_id, author_principal_id,
                         capability_id, description)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (task_id, organization_id, principal_id, capability_id,
                     description),
                )
                row = cur.fetchone()
            return self._task_view(conn, row)

    def list_tasks(self, skip=0, limit=50):
        # type: (int, int) -> Tuple[List[dict], int]
        """All marketplace-native tasks, newest first, paginated; returns
        ``(tasks, total)``.

        Unit U7: ``marketplace.tasks`` is now also the backing store for
        ``apps/gig-board``'s Service/Gig listings (capability_id =
        'gig-board.gigs'), scoped to that app's own reads. This listing --
        apps/marketplace's own "all tasks" view -- excludes those rows so a
        marketplace user browsing tasks doesn't see unrelated gig-board
        postings mixed in; direct lookup by task_id (get_task) is
        intentionally NOT filtered, since a caller with a specific id has a
        legitimate reason to fetch it regardless of which app created it.
        """
        with self._db.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT count(*) AS n FROM marketplace.tasks "
                    "WHERE capability_id IS DISTINCT FROM 'gig-board.gigs'"
                )
                total = cur.fetchone()["n"]
                cur.execute(
                    """
                    SELECT * FROM marketplace.tasks
                    WHERE capability_id IS DISTINCT FROM 'gig-board.gigs'
                    ORDER BY created_at DESC
                    OFFSET %s LIMIT %s
                    """,
                    (skip, limit),
                )
                rows = cur.fetchall()
            tasks = [self._task_view(conn, row) for row in rows]
        return tasks, total

    def get_task(self, task_id):
        # type: (str) -> Optional[dict]
        """Fetch one task's full view, or ``None`` if unknown."""
        with self._db.connection() as conn:
            row = self._fetch_task_row(conn, task_id)
            if row is None:
                return None
            return self._task_view(conn, row)

    def task_exists(self, task_id):
        # type: (str) -> bool
        with self._db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM marketplace.tasks WHERE task_id = %s",
                    (task_id,),
                )
                return cur.fetchone() is not None

    def list_open_tasks(self):
        # type: () -> List[dict]
        """Light rows (no nested negotiations/bids) for P2P work-opportunity
        discovery -- newest first. Excludes gig-board's rows; see
        ``list_tasks``'s docstring."""
        with self._db.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT task_id, description, author_principal_id,
                           created_at
                    FROM marketplace.tasks
                    WHERE status = 'open'
                      AND capability_id IS DISTINCT FROM 'gig-board.gigs'
                    ORDER BY created_at DESC
                    """
                )
                rows = cur.fetchall()
        return [
            {
                "id": row["task_id"],
                "description": row["description"],
                "author_principal": row["author_principal_id"],
                "created_at": _iso(row["created_at"]),
            }
            for row in rows
        ]

    def accept_task(self, task_id, worker_principal_id):
        # type: (str, str) -> Tuple[Optional[dict], Optional[str]]
        """Accept an open task as ``worker_principal_id``. Returns
        ``(task_view, None)`` on success or ``(None, error_code)`` where
        ``error_code`` is one of ``"not_found"``, ``"not_open"``,
        ``"own_task"``."""
        self._ensure_principal(worker_principal_id, "user")
        with self._db.transaction() as conn:
            row = self._fetch_task_row(conn, task_id)
            if row is None:
                return None, "not_found"
            if row["status"] != "open":
                return None, "not_open"
            if row["author_principal_id"] == worker_principal_id:
                return None, "own_task"
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    UPDATE marketplace.tasks
                    SET status = 'accepted', worker_principal_id = %s,
                        updated_at = now()
                    WHERE task_id = %s AND status = 'open'
                    RETURNING *
                    """,
                    (worker_principal_id, task_id),
                )
                updated = cur.fetchone()
            if updated is None:
                return None, "not_open"  # lost a race
            return self._task_view(conn, updated), None

    def complete_task(self, task_id, author_principal_id, outcome):
        # type: (str, str, str) -> Tuple[Optional[dict], Optional[str]]
        """Mark a task completed, recording ``outcome`` as a work_results
        row (see module docstring). Error codes: ``"not_found"``,
        ``"not_author"``, ``"not_ready"`` (not accepted/delivered),
        ``"no_worker"``."""
        with self._db.transaction() as conn:
            row = self._fetch_task_row(conn, task_id)
            if row is None:
                return None, "not_found"
            if row["author_principal_id"] != author_principal_id:
                return None, "not_author"
            if row["status"] not in ("accepted", "delivered"):
                return None, "not_ready"
            if row["worker_principal_id"] is None:
                return None, "no_worker"

            work_result_id = generate_ulid()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO marketplace.work_results
                        (work_result_id, task_id, result_summary,
                         submitted_by)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (work_result_id, task_id, outcome, author_principal_id),
                )
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    UPDATE marketplace.tasks
                    SET status = 'completed', updated_at = now()
                    WHERE task_id = %s
                    RETURNING *
                    """,
                    (task_id,),
                )
                updated = cur.fetchone()
            return self._task_view(conn, updated), None

    def _fetch_task_row(self, conn, task_id):
        # type: (object, str) -> Optional[dict]
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM marketplace.tasks WHERE task_id = %s",
                (task_id,),
            )
            return cur.fetchone()

    def _task_view(self, conn, row):
        # type: (object, dict) -> dict
        """Build the full R10-shaped task dict: pre-existing consumers read
        ``id``/``author_principal``/``worker_principal``/``negotiations``/
        ``bids``/``work_result``/``outcome`` off this exact structure."""
        task_id = row["task_id"]
        negotiations = self._list_negotiation_rows(conn, task_id, limit=1000)
        bids = self._list_bid_rows(conn, task_id)
        latest_wr = self._latest_work_result_row(conn, task_id)

        work_result = None
        outcome = None
        if latest_wr is not None:
            work_result = {
                "result_summary": latest_wr["result_summary"],
                "evidence": latest_wr.get("evidence") or {},
                "evidence_id": latest_wr.get("evidence_id"),
                "submitted_by": latest_wr["submitted_by"],
                "submitted_at": _iso(latest_wr["submitted_at"]),
            }
            if row["status"] == "completed":
                outcome = latest_wr["result_summary"]

        return {
            "id": task_id,
            "author_principal": row["author_principal_id"],
            "description": row["description"],
            "status": row["status"],
            "created_at": _iso(row["created_at"]),
            "worker_principal": row.get("worker_principal_id"),
            "negotiations": negotiations,
            "outcome": outcome,
            "bids": bids,
            "work_result": work_result,
            "capability_id": row.get("capability_id"),
            "organization_id": row.get("organization_id"),
        }

    # -- bids ----------------------------------------------------------------

    def create_bid(self, task_id, agent_principal_id, proposed_terms,
                   agent_reputation_note=None):
        # type: (str, str, str, Optional[str]) -> Tuple[Optional[dict], Optional[str]]
        """Bid on an open task. A second bid from the same agent replaces its
        pending bid (matches the prior in-memory replace-not-duplicate
        behavior). Error codes: ``"not_found"``, ``"not_open"``."""
        self._ensure_principal(agent_principal_id, "agent")
        with self._db.transaction() as conn:
            row = self._fetch_task_row(conn, task_id)
            if row is None:
                return None, "not_found"
            if row["status"] != "open":
                return None, "not_open"

            bid_id = str(uuid.uuid4())
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM marketplace.bids
                    WHERE task_id = %s AND agent_principal_id = %s
                      AND status = 'pending'
                    """,
                    (task_id, agent_principal_id),
                )
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    INSERT INTO marketplace.bids
                        (bid_id, task_id, agent_principal_id,
                         proposed_terms, agent_reputation_note)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (bid_id, task_id, agent_principal_id, proposed_terms,
                     agent_reputation_note),
                )
                bid_row = cur.fetchone()
        return self._bid_view(bid_row), None

    def list_bids(self, task_id):
        # type: (str) -> List[dict]
        with self._db.connection() as conn:
            return self._list_bid_rows(conn, task_id)

    def _list_bid_rows(self, conn, task_id):
        # type: (object, str) -> List[dict]
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT * FROM marketplace.bids "
                "WHERE task_id = %s ORDER BY created_at",
                (task_id,),
            )
            return [self._bid_view(row) for row in cur.fetchall()]

    def get_bid(self, task_id, bid_id):
        # type: (str, str) -> Optional[dict]
        with self._db.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM marketplace.bids "
                    "WHERE task_id = %s AND bid_id = %s",
                    (task_id, bid_id),
                )
                row = cur.fetchone()
        return self._bid_view(row) if row is not None else None

    def accept_bid(self, task_id, bid_id, author_principal_id):
        # type: (str, str, str) -> Tuple[Optional[dict], Optional[dict], Optional[str]]
        """Author accepts an agent's bid: the bidding agent becomes worker,
        the task moves to "accepted", every other bid is rejected. Error
        codes: ``"not_found"`` (task), ``"not_author"``, ``"not_open"``,
        ``"bid_not_found"``."""
        with self._db.transaction() as conn:
            row = self._fetch_task_row(conn, task_id)
            if row is None:
                return None, None, "not_found"
            if row["author_principal_id"] != author_principal_id:
                return None, None, "not_author"
            if row["status"] != "open":
                return None, None, "not_open"

            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM marketplace.bids "
                    "WHERE task_id = %s AND bid_id = %s",
                    (task_id, bid_id),
                )
                bid_row = cur.fetchone()
            if bid_row is None:
                return None, None, "bid_not_found"

            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE marketplace.bids SET status = 'accepted' "
                    "WHERE bid_id = %s",
                    (bid_id,),
                )
                cur.execute(
                    "UPDATE marketplace.bids SET status = 'rejected' "
                    "WHERE task_id = %s AND bid_id != %s",
                    (task_id, bid_id),
                )
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    UPDATE marketplace.tasks
                    SET status = 'accepted', worker_principal_id = %s,
                        updated_at = now()
                    WHERE task_id = %s
                    RETURNING *
                    """,
                    (bid_row["agent_principal_id"], task_id),
                )
                updated_task = cur.fetchone()

            bid_row["status"] = "accepted"
            return (
                self._task_view(conn, updated_task),
                self._bid_view(bid_row),
                None,
            )

    def _bid_view(self, row):
        # type: (Optional[dict]) -> Optional[dict]
        if row is None:
            return None
        bid = {
            "bid_id": row["bid_id"],
            "task_id": row["task_id"],
            "agent_principal_id": row["agent_principal_id"],
            "proposed_terms": row["proposed_terms"],
            "status": row["status"],
            "created_at": _iso(row["created_at"]),
        }
        if row.get("agent_reputation_note") is not None:
            bid["agent_reputation_note"] = row["agent_reputation_note"]
        return bid

    # -- negotiation messages --------------------------------------------------

    def add_negotiation_message(self, task_id, from_principal_id, message):
        # type: (str, str, str) -> Tuple[Optional[dict], Optional[dict], Optional[str]]
        """Append a negotiation message. Error codes: ``"not_found"``,
        ``"not_authorized"`` (neither the task's author nor its worker)."""
        with self._db.transaction() as conn:
            row = self._fetch_task_row(conn, task_id)
            if row is None:
                return None, None, "not_found"
            if from_principal_id not in (
                row["author_principal_id"], row["worker_principal_id"],
            ):
                return None, None, "not_authorized"

            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    INSERT INTO marketplace.negotiation_messages
                        (task_id, from_principal_id, message)
                    VALUES (%s, %s, %s)
                    RETURNING *
                    """,
                    (task_id, from_principal_id, message),
                )
                msg_row = cur.fetchone()
            task_view = self._task_view(conn, row)
        return self._negotiation_view(msg_row), task_view, None

    def list_negotiations(self, task_id, skip=0, limit=1000):
        # type: (str, int, int) -> List[dict]
        """Negotiation thread in order, paginated by ``(task_id,
        created_at)`` -- never an unbounded blob."""
        with self._db.connection() as conn:
            return self._list_negotiation_rows(
                conn, task_id, skip=skip, limit=limit
            )

    def _list_negotiation_rows(self, conn, task_id, skip=0, limit=1000):
        # type: (object, str, int, int) -> List[dict]
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT * FROM marketplace.negotiation_messages
                WHERE task_id = %s
                ORDER BY message_id
                OFFSET %s LIMIT %s
                """,
                (task_id, skip, limit),
            )
            return [self._negotiation_view(row) for row in cur.fetchall()]

    def _negotiation_view(self, row):
        # type: (dict) -> dict
        return {
            "from": row["from_principal_id"],
            "message": row["message"],
            "timestamp": _iso(row["created_at"]),
        }

    # -- work results ----------------------------------------------------------

    def submit_work_result(self, task_id, requester_principal_id,
                           result_summary, evidence=None, evidence_id=None):
        # type: (str, str, str, Optional[dict], Optional[str]) -> Tuple[Optional[dict], Optional[str]]
        """The accepted worker delivers work: inserts a NEW work_results row
        (preserving redelivery history, unlike the prior single overwritable
        slot) and moves the task to "delivered". Error codes:
        ``"not_found"``, ``"not_accepted"``, ``"forbidden"`` (not the
        accepted worker)."""
        self._ensure_principal(requester_principal_id, "agent")
        with self._db.transaction() as conn:
            row = self._fetch_task_row(conn, task_id)
            if row is None:
                return None, "not_found"
            if row["status"] != "accepted":
                return None, "not_accepted"
            if row["worker_principal_id"] != requester_principal_id:
                return None, "forbidden"

            work_result_id = generate_ulid()
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO marketplace.work_results
                        (work_result_id, task_id, result_summary, evidence,
                         evidence_id, submitted_by)
                    VALUES (%s, %s, %s, %s::jsonb, %s, %s)
                    """,
                    (
                        work_result_id, task_id, result_summary,
                        _dumps(evidence or {}), evidence_id,
                        requester_principal_id,
                    ),
                )
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    UPDATE marketplace.tasks
                    SET status = 'delivered', updated_at = now()
                    WHERE task_id = %s
                    RETURNING *
                    """,
                    (task_id,),
                )
                updated = cur.fetchone()
            return self._task_view(conn, updated), None

    def _latest_work_result_row(self, conn, task_id):
        # type: (object, str) -> Optional[dict]
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT * FROM marketplace.work_results
                WHERE task_id = %s
                ORDER BY submitted_at DESC
                LIMIT 1
                """,
                (task_id,),
            )
            return cur.fetchone()

    def list_work_results(self, task_id):
        # type: (str) -> List[dict]
        """Every delivery for a task, oldest first (full redelivery
        history -- the latest is what :meth:`get_task`'s single-object
        ``work_result`` view returns)."""
        with self._db.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT * FROM marketplace.work_results
                    WHERE task_id = %s
                    ORDER BY submitted_at
                    """,
                    (task_id,),
                )
                rows = cur.fetchall()
        return [
            {
                "work_result_id": row["work_result_id"],
                "result_summary": row["result_summary"],
                "evidence": row.get("evidence") or {},
                "evidence_id": row.get("evidence_id"),
                "submitted_by": row["submitted_by"],
                "submitted_at": _iso(row["submitted_at"]),
            }
            for row in rows
        ]

    # -- Offers / CounterOffers (RFC-0002 §6, unit U6 adoption) ---------------
    #
    # See apps/marketplace/server/app.py's ``_p2p_task_offer``/
    # ``_p2p_task_counter`` docstrings for why these are P2P request types
    # (not a new REST surface) and how they coexist with the pre-existing
    # bids[]/agent_reputation_note mechanism.

    def create_offer(self, task_id, provider_principal_id, price, currency,
                     delivery=None, terms=None):
        # type: (str, str, float, str, Optional[str], Optional[dict]) -> Tuple[Optional[dict], Optional[str]]
        """Record a provider's public price offer for an open task. Error
        codes: ``"not_found"``, ``"not_open"``."""
        self._ensure_principal(provider_principal_id, "agent")
        offer_id = generate_ulid()
        with self._db.transaction() as conn:
            row = self._fetch_task_row(conn, task_id)
            if row is None:
                return None, "not_found"
            if row["status"] != "open":
                return None, "not_open"
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    INSERT INTO marketplace.offers
                        (offer_id, task_id, provider_principal_id, price,
                         currency, delivery, terms)
                    VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                    RETURNING *
                    """,
                    (
                        offer_id, task_id, provider_principal_id, price,
                        currency, delivery, _dumps(terms or {}),
                    ),
                )
                offer_row = cur.fetchone()
        return self._offer_view(offer_row), None

    def list_offers(self, task_id):
        # type: (str) -> List[dict]
        with self._db.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM marketplace.offers "
                    "WHERE task_id = %s ORDER BY created_at",
                    (task_id,),
                )
                return [self._offer_view(row) for row in cur.fetchall()]

    def _offer_view(self, row):
        # type: (dict) -> dict
        return {
            "offer_id": row["offer_id"],
            "task_id": row["task_id"],
            "provider_principal_id": row["provider_principal_id"],
            "price": float(row["price"]),
            "currency": row["currency"],
            "delivery": row.get("delivery"),
            "terms": row.get("terms") or {},
            "created_at": _iso(row["created_at"]),
        }

    def create_counter_offer(self, task_id, proposed_price, currency):
        # type: (str, float, str) -> Tuple[Optional[dict], Optional[str]]
        """Record the requester's single-round counter-offer. Error codes:
        ``"not_found"``, ``"no_standing_offer"`` (nothing to counter yet),
        ``"already_countered"`` (single round only, RFC-0002 §6.1)."""
        counter_id = generate_ulid()
        with self._db.transaction() as conn:
            row = self._fetch_task_row(conn, task_id)
            if row is None:
                return None, "not_found"
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM marketplace.offers "
                    "WHERE task_id = %s",
                    (task_id,),
                )
                if cur.fetchone()[0] == 0:
                    return None, "no_standing_offer"
                cur.execute(
                    "SELECT count(*) FROM marketplace.counter_offers "
                    "WHERE task_id = %s",
                    (task_id,),
                )
                if cur.fetchone()[0] > 0:
                    return None, "already_countered"
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    INSERT INTO marketplace.counter_offers
                        (counter_id, task_id, proposed_price, currency)
                    VALUES (%s, %s, %s, %s)
                    RETURNING *
                    """,
                    (counter_id, task_id, proposed_price, currency),
                )
                counter_row = cur.fetchone()
        return self._counter_offer_view(counter_row), None

    def list_counter_offers(self, task_id):
        # type: (str) -> List[dict]
        with self._db.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM marketplace.counter_offers "
                    "WHERE task_id = %s ORDER BY created_at",
                    (task_id,),
                )
                return [
                    self._counter_offer_view(row) for row in cur.fetchall()
                ]

    def _counter_offer_view(self, row):
        # type: (dict) -> dict
        return {
            "counter_id": row["counter_id"],
            "task_id": row["task_id"],
            "proposed_price": float(row["proposed_price"]),
            "currency": row["currency"],
            "created_at": _iso(row["created_at"]),
        }


def _dumps(value):
    # type: (dict) -> str
    """JSON-encode a dict for a ``jsonb`` column parameter."""
    return json.dumps(value)


def _iso(value):
    # type: (object) -> object
    return value.isoformat() if isinstance(value, datetime) else value
