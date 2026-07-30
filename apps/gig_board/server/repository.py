"""Thin adapter putting the Gig Board (unit U4) on the SAME
``marketplace.tasks`` table ``apps/marketplace`` already uses (unit U6 --
see ``apps/marketplace/server/repository.py``), rather than a dedicated
``gig_board`` schema. There is none: the design doc (§7) merges gig-board,
marketplace and agent_marketplace at the schema level -- "a single ``tasks``
table backs all three product surfaces" -- so this module composes
``MarketplaceRepository``'s existing methods instead of re-implementing any
of its SQL (KTD1's spirit extended: don't duplicate a working query either).

Mapping
-------
A **Service** listing (``register_service``) is one ``marketplace.tasks``
row: ``author_principal_id`` is the provider, ``capability_id`` is the
fixed ``"gig-board.gigs"`` convention this codebase already uses as the
default capability for gig-board's P2P registration path (see
``GigBoardService.P2P_CAPABILITIES``/``_p2p_register_service``). It is
NEVER accepted or completed itself -- it stays ``status='open'`` forever,
existing purely as a directory entry a buyer can discover and hire.

A **Gig** booking (``create_gig``) is a SEPARATE ``marketplace.tasks`` row
per booking -- not the Service's own row transitioning state -- so that one
Service can be hired repeatedly and concurrently, matching the pre-existing
in-memory ``GigBoardService.create_gig``, which never restricted a
``service_id`` to a single active gig. ``author_principal_id`` is the buyer
(the one who wants work done -- exactly marketplace's "task poster" role)
and ``worker_principal_id`` is the provider, composed from two EXISTING
``MarketplaceRepository`` calls -- :meth:`~MarketplaceRepository.create_task`
then :meth:`~MarketplaceRepository.accept_task` -- rather than a new INSERT.
The tiny window between those two calls where the fresh task briefly sits
``status='open'`` (visible to ``apps/marketplace``'s own unscoped
``/api/tasks``, since nothing here can change that app's code) is a known,
accepted risk of literal table sharing without RLS/app-layer partitioning
-- see this unit's report for detail; no test in this codebase can win that
race (gig-board is the only writer of ``capability_id='gig-board.gigs'``
rows), so it stays purely theoretical.

The JSON envelope wrinkle (no columns for ``service_name``/``service_id``)
---------------------------------------------------------------------------
``marketplace.tasks`` has exactly one free-text field per row --
``description`` -- and no metadata column at all. A Service needs to keep
BOTH ``service_name`` and ``description`` as distinct API fields; a Gig
needs to remember which Service it booked (``service_id``). Rather than a
migration for two rarely-queried strings, both are folded into the
``description`` column as a small JSON envelope (:func:`_encode_service`/
:func:`_encode_gig`/:func:`_decode`) -- the same "reuse what's there" move
``MarketplaceRepository`` itself already documents for ``outcome`` and the
P2P ``evidence`` blob. The ``"kind"`` key (``"service"`` or ``"gig"``) is
what tells the two apart when scanning every ``gig-board.gigs`` row (a
plain marketplace task's ``description`` is ordinary prose, not JSON, so it
never collides with either kind -- see :meth:`_capability_tasks`).

``gigs_completed`` is NEVER stored
-----------------------------------
:meth:`gigs_completed` runs a live ``COUNT(*) ... WHERE worker_principal_id
= ? AND capability_id = 'gig-board.gigs' AND status = 'completed'`` every
time a Service view is built. There is no counter column to increment and
therefore nothing that can drift from the underlying completed-gig rows
(the prior in-memory ``service["gigs_completed"] += 1`` this replaces was
exactly that kind of counter -- this unit's plan calls out fixing it).
"""

import json

from typing import List, Optional, Tuple

from apps.marketplace.server.repository import MarketplaceRepository
from libs.db import Database

#: Fixed capability convention every gig-board ``marketplace.tasks`` row
#: (both Service listings and Gig bookings) is scoped under. Also the
#: default ``capability_id`` gig-board's own P2P registration path
#: (``_p2p_register_service``) has always used.
GIG_BOARD_CAPABILITY_ID = "gig-board.gigs"


class GigBoardRepository(object):
    """Repository for the Gig Board's Service/Gig resources, persisted as
    ``marketplace.tasks`` rows via a composed :class:`MarketplaceRepository`
    (see module docstring for the mapping)."""

    def __init__(self, db=None, marketplace=None):
        # type: (Optional[Database], Optional[MarketplaceRepository]) -> None
        self._db = db or Database()
        self._marketplace = marketplace or MarketplaceRepository(self._db)

    # -- services -------------------------------------------------------------

    def register_service(self, principal_id, service_name, description,
                         pricing=None):
        # type: (str, str, str, object) -> dict
        """Register a new Service listing; return the full view (R10
        shape)."""
        payload = {
            "kind": "service",
            "service_name": service_name,
            "description": description,
        }
        if pricing is not None:
            payload["pricing"] = pricing
        task = self._marketplace.create_task(
            principal_id, json.dumps(payload),
            capability_id=GIG_BOARD_CAPABILITY_ID,
        )
        return self._service_view(task)

    def list_all_services(self):
        # type: () -> List[dict]
        """Every Service listing, newest first (unpaginated -- used both by
        the paginated HTTP list and the P2P work-opportunities feed, which
        has never itself been paginated)."""
        services = []
        for task in self._capability_tasks():
            decoded = _decode(task["description"])
            if decoded.get("kind") == "service":
                services.append(self._service_view(task, decoded))
        return services

    def list_services(self, skip=0, limit=50):
        # type: (int, int) -> Tuple[List[dict], int]
        services = self.list_all_services()
        total = len(services)
        return services[skip:skip + limit], total

    def get_service(self, service_id):
        # type: (str) -> Optional[dict]
        task = self._marketplace.get_task(service_id)
        if task is None or task.get("capability_id") != GIG_BOARD_CAPABILITY_ID:
            return None
        decoded = _decode(task["description"])
        if decoded.get("kind") != "service":
            return None
        return self._service_view(task, decoded)

    # -- gigs -------------------------------------------------------------------

    def create_gig(self, service_id, buyer_principal, description):
        # type: (str, str, str) -> Tuple[Optional[dict], Optional[str]]
        """Hire a service provider (create + immediately accept a NEW task
        row -- see module docstring). Error codes: ``"not_found"`` (unknown
        service) plus whatever :meth:`MarketplaceRepository.accept_task`
        could theoretically return (practically unreachable here -- the
        task this method just created is brand new and gig-board is the
        only writer of its capability)."""
        service_task = self._marketplace.get_task(service_id)
        if (
            service_task is None
            or service_task.get("capability_id") != GIG_BOARD_CAPABILITY_ID
            or _decode(service_task["description"]).get("kind") != "service"
        ):
            return None, "not_found"

        provider_principal = service_task["author_principal"]
        payload = {"kind": "gig", "service_id": service_id,
                   "description": description}
        gig_task = self._marketplace.create_task(
            buyer_principal, json.dumps(payload),
            capability_id=GIG_BOARD_CAPABILITY_ID,
        )
        accepted, error = self._marketplace.accept_task(
            gig_task["id"], provider_principal
        )
        if error is not None:
            return None, error
        return self._gig_view(accepted), None

    def list_all_gigs(self, principal_id):
        # type: (str) -> List[dict]
        """Every Gig booking where ``principal_id`` is either the buyer or
        the provider, newest first (unpaginated)."""
        gigs = []
        for task in self._capability_tasks():
            decoded = _decode(task["description"])
            if decoded.get("kind") != "gig":
                continue
            if principal_id not in (
                task["author_principal"], task["worker_principal"],
            ):
                continue
            gigs.append(self._gig_view(task, decoded))
        return gigs

    def list_gigs(self, principal_id, skip=0, limit=50):
        # type: (str, int, int) -> Tuple[List[dict], int]
        gigs = self.list_all_gigs(principal_id)
        total = len(gigs)
        return gigs[skip:skip + limit], total

    def get_gig(self, gig_id):
        # type: (str) -> Optional[dict]
        task = self._marketplace.get_task(gig_id)
        if task is None or task.get("capability_id") != GIG_BOARD_CAPABILITY_ID:
            return None
        decoded = _decode(task["description"])
        if decoded.get("kind") != "gig":
            return None
        return self._gig_view(task, decoded)

    def complete_gig(self, gig_id, buyer_principal, outcome):
        # type: (str, str, str) -> Tuple[Optional[dict], Optional[str]]
        """Delegates to :meth:`MarketplaceRepository.complete_task` --
        error codes ``"not_found"``, ``"not_author"``, ``"not_ready"``,
        ``"no_worker"`` pass straight through (see that method's
        docstring)."""
        task, error = self._marketplace.complete_task(
            gig_id, buyer_principal, outcome
        )
        if error is not None:
            return None, error
        return self._gig_view(task), None

    # -- derived stats (never stored -- see module docstring) ------------------

    def gigs_completed(self, provider_principal):
        # type: (str) -> int
        """Live count of ``provider_principal``'s completed gig bookings."""
        with self._db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT count(*) FROM marketplace.tasks
                    WHERE worker_principal_id = %s
                      AND capability_id = %s
                      AND status = 'completed'
                    """,
                    (provider_principal, GIG_BOARD_CAPABILITY_ID),
                )
                return cur.fetchone()[0]

    # -- internals ----------------------------------------------------------

    def _capability_tasks(self):
        # type: () -> List[dict]
        """Every ``gig-board.gigs``-scoped task (Services AND Gigs mixed),
        newest first, as FULL task views built via ``MarketplaceRepository``
        -- never a hand-rolled duplicate of its ``_task_view`` join logic.
        The one bit of new SQL this module adds: a plain ``WHERE
        capability_id = ...`` id lookup, since ``MarketplaceRepository`` has
        no capability-scoped listing method (nothing needed one before this
        unit)."""
        with self._db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT task_id FROM marketplace.tasks "
                    "WHERE capability_id = %s ORDER BY created_at DESC",
                    (GIG_BOARD_CAPABILITY_ID,),
                )
                task_ids = [row[0] for row in cur.fetchall()]
        return [self._marketplace.get_task(task_id) for task_id in task_ids]

    def _service_view(self, task, decoded=None):
        # type: (dict, Optional[dict]) -> dict
        if decoded is None:
            decoded = _decode(task["description"])
        provider = task["author_principal"]
        view = {
            "id": task["id"],
            "provider_principal": provider,
            "service_name": decoded.get("service_name", ""),
            "description": decoded.get("description", ""),
            "created_at": task["created_at"],
            "gigs_completed": self.gigs_completed(provider),
            "rating": None,
            "capability_id": GIG_BOARD_CAPABILITY_ID,
        }
        if "pricing" in decoded:
            view["pricing"] = decoded["pricing"]
        return view

    def _gig_view(self, task, decoded=None):
        # type: (dict, Optional[dict]) -> dict
        if decoded is None:
            decoded = _decode(task["description"])
        status = "completed" if task["status"] == "completed" else "active"
        completed_at = None
        work_result = task.get("work_result")
        if status == "completed" and work_result is not None:
            completed_at = work_result["submitted_at"]
        return {
            "id": task["id"],
            "service_id": decoded.get("service_id"),
            "provider_principal": task["worker_principal"],
            "buyer_principal": task["author_principal"],
            "description": decoded.get("description", ""),
            "status": status,
            "created_at": task["created_at"],
            "completed_at": completed_at,
            "outcome": task["outcome"],
        }


def _decode(raw):
    # type: (object) -> dict
    """Best-effort JSON-decode of a ``marketplace.tasks.description`` value.
    A plain marketplace task's description is ordinary prose, not JSON, so
    this returns ``{}`` for it -- that's what keeps unrelated marketplace
    tasks from ever being mistaken for a gig-board Service/Gig even in the
    (currently impossible, see module docstring) case they shared this
    capability_id."""
    if not isinstance(raw, str):
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}
