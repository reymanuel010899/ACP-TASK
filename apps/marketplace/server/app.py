"""Task Marketplace Backend (unit U3; Postgres-backed since unit U6 -- see
``apps/marketplace/server/repository.py``).

A federated task marketplace where users post tasks, accept them, negotiate
outcomes, and earn reputation through the registry.

API endpoints:
- POST /api/tasks - Create new task
- GET /api/tasks - List all tasks (with pagination/filters)
- GET /api/tasks/{task_id} - Get task details
- POST /api/tasks/{task_id}/accept - Accept task (user becomes worker)
- GET  /api/tasks/{task_id}/bids - List agent bids on a task (U10)
- POST /api/tasks/{task_id}/bids/{bid_id}/accept - Author accepts a bid (U10)
- POST /api/negotiations/{task_id} - Send negotiation message
- GET /api/negotiations/{task_id}[?skip=&limit=] - Get negotiation thread
  (U6: paginated, ``skip``/``limit`` optional and additive)
- POST /api/negotiations/{task_id}/complete - Mark task complete with outcome
- POST /p2p/request - Direct P2P request from another app/agent (U6,
  RFC-0003): permission is checked with the Registry when configured;
  standalone mode (no --registry-url) processes without the check.
  Request types (U10 adds the work-coordination types; U6 adds the
  RFC-0002 Offer/CounterOffer types):
  ping, list.work_opportunities, submit.work_bid, get.task_status,
  submit.work_result, task.offer, task.counter.

Run: python -m apps.marketplace.server.app [--port 8001] [--registry-url URL]
"""

import argparse
import json
import pathlib
import uuid
from typing import Optional, Tuple
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

import jsonschema
import requests

from apps.marketplace.server.repository import MarketplaceRepository
from libs.audit_client import make_audit_client
from libs.db import Database, bind_organization_id
from libs.federation_client import FederationClient, FederationError
from libs.request_auth import RequestAuthenticator

#: RFC-0002 competitive-negotiation schemas (unit U6 adoption) -- loaded once
#: at import time, not per-request. See ``TaskService._p2p_task_offer``/
#: ``_p2p_task_counter`` for why these are validated as real JSON Schema
#: instances rather than hand-checked field by field.
_SCHEMAS_DIR = pathlib.Path(__file__).resolve().parents[3] / "schemas"
_OFFER_SCHEMA = json.loads((_SCHEMAS_DIR / "offer.schema.json").read_text())
_COUNTER_OFFER_SCHEMA = json.loads(
    (_SCHEMAS_DIR / "counter-offer.schema.json").read_text()
)


class TaskService:
    """Core task marketplace logic (unit U6: Postgres-backed via
    ``apps.marketplace.server.repository.MarketplaceRepository``, replacing
    the prior in-memory ``self.tasks`` dict -- see that module's docstring
    for the storage design)."""

    APP_ID = "marketplace"
    P2P_CAPABILITIES = ["marketplace.tasks", "p2p.ping"]

    def __init__(self, registry_url=None, http_timeout=3.0, audit_url=None,
                 require_signatures=False, public_key_resolver=None,
                 db=None, repository=None):
        # type: (Optional[str], float, Optional[str], bool, object, object, Optional[MarketplaceRepository]) -> None
        self.registry_url = (
            registry_url.rstrip("/") if registry_url else None
        )
        self.http_timeout = http_timeout
        # Central audit emitter (U12): best-effort, fire-and-forget; a
        # NullAuditClient (no-op) when no audit_url is configured.
        self.audit_client = make_audit_client(audit_url)
        # Request authentication (U18, RFC-0005): a no-op pass-through when
        # require_signatures is False (today's behavior). When on, P2P
        # requests must carry a valid two-link signature and the verified
        # principal must equal the payload's requester_principal_id. The
        # resolver is injectable for tests; by default it fetches public keys
        # from the Registry authority endpoint.
        self.require_signatures = require_signatures
        self.authenticator = RequestAuthenticator(
            self.registry_url,
            require_signatures=require_signatures,
            http_timeout=http_timeout,
            public_key_resolver=public_key_resolver,
        )
        # Unit U6: Postgres-backed storage. `db=`/`repository=` are
        # injectable (mirrors vault/app.py's make_server) so tests can point
        # at a specific DSN or a fake, and so a "simulated restart" can build
        # a brand new repository/pool against the same database.
        self.repository = repository or MarketplaceRepository(db or Database())
        self.app_id = self.APP_ID
        self.capabilities = list(self.P2P_CAPABILITIES)
        # app_ids discovered at registration time (U9, RFC-0004).
        self.discovered_ecosystem = []  # type: list
        # request_type -> handler(payload); U10 plugs real work types in here.
        # U6 adds "task.offer"/"task.counter" -- named after RFC-0002's own
        # message discriminators (schemas/offer.schema.json's/
        # counter-offer.schema.json's "type" const) rather than this
        # module's verb.noun convention (e.g. "submit.work_bid"), since these
        # ARE the wire vocabulary RFC-0002 already defines; see
        # `_p2p_task_offer`'s docstring for the full adoption rationale.
        self._p2p_handlers = {
            "ping": self._p2p_ping,
            "list.work_opportunities": self._p2p_list_work_opportunities,
            "submit.work_bid": self._p2p_submit_work_bid,
            "get.task_status": self._p2p_get_task_status,
            "submit.work_result": self._p2p_submit_work_result,
            "task.offer": self._p2p_task_offer,
            "task.counter": self._p2p_task_counter,
        }

    def create_task(self, principal_id, description):
        # type: (str, str) -> Tuple[int, dict]
        """Create a new task."""
        if not isinstance(principal_id, str) or not principal_id:
            return 422, {"error": "missing or invalid 'principal_id'"}
        if not isinstance(description, str) or not description.strip():
            return 422, {"error": "missing or invalid 'description'"}

        task = self.repository.create_task(principal_id, description.strip())
        return 200, {"task": task}

    def list_tasks(self, skip=0, limit=50):
        # type: (int, int) -> Tuple[int, dict]
        """List all tasks with pagination."""
        if not isinstance(skip, int) or skip < 0:
            return 400, {"error": "skip must be a non-negative integer"}
        if not isinstance(limit, int) or limit < 1 or limit > 100:
            return 400, {"error": "limit must be between 1 and 100"}

        tasks, total = self.repository.list_tasks(skip, limit)

        return 200, {
            "tasks": tasks,
            "total": total,
            "skip": skip,
            "limit": limit,
        }

    def get_task(self, task_id):
        # type: (str) -> Tuple[int, dict]
        """Get a specific task by ID."""
        if not isinstance(task_id, str) or not task_id:
            return 422, {"error": "missing or invalid 'task_id'"}

        task = self.repository.get_task(task_id)
        if task is None:
            return 404, {"error": "task not found"}

        return 200, {"task": task}

    def accept_task(self, task_id, worker_principal):
        # type: (str, str) -> Tuple[int, dict]
        """Accept a task as a worker."""
        if not isinstance(task_id, str) or not task_id:
            return 422, {"error": "missing or invalid 'task_id'"}
        if not isinstance(worker_principal, str) or not worker_principal:
            return 422, {"error": "missing or invalid 'worker_principal'"}

        task, error = self.repository.accept_task(task_id, worker_principal)
        if error == "not_found":
            return 404, {"error": "task not found"}
        if error == "not_open":
            return 400, {"error": "task is not open for acceptance"}
        if error == "own_task":
            return 400, {"error": "cannot accept your own task"}

        return 200, {"task": task}

    def list_bids(self, task_id):
        # type: (str) -> Tuple[int, dict]
        """List agent bids on a task (U10) so the author can review them."""
        if not isinstance(task_id, str) or not task_id:
            return 422, {"error": "missing or invalid 'task_id'"}

        if not self.repository.task_exists(task_id):
            return 404, {"error": "task not found"}

        return 200, {
            "task_id": task_id,
            "bids": self.repository.list_bids(task_id),
        }

    def accept_bid(self, task_id, bid_id, author_principal):
        # type: (str, str, str) -> Tuple[int, dict]
        """Author accepts an agent's bid (U10): the bidding agent becomes
        the worker, the task moves to "accepted", and every other bid is
        rejected."""
        if not isinstance(task_id, str) or not task_id:
            return 422, {"error": "missing or invalid 'task_id'"}
        if not isinstance(bid_id, str) or not bid_id:
            return 422, {"error": "missing or invalid 'bid_id'"}
        if not isinstance(author_principal, str) or not author_principal:
            return 422, {"error": "missing or invalid 'author_principal'"}

        task, bid, error = self.repository.accept_bid(
            task_id, bid_id, author_principal
        )
        if error == "not_found":
            return 404, {"error": "task not found"}
        if error == "not_author":
            return 403, {"error": "only task author can accept bids"}
        if error == "not_open":
            return 400, {"error": "task is not open for bid acceptance"}
        if error == "bid_not_found":
            return 404, {"error": "bid not found"}

        return 200, {"task": task, "bid": bid}

    def send_negotiation_message(self, task_id, from_principal, message):
        # type: (str, str, str) -> Tuple[int, dict]
        """Send a negotiation message for a task."""
        if not isinstance(task_id, str) or not task_id:
            return 422, {"error": "missing or invalid 'task_id'"}
        if not isinstance(from_principal, str) or not from_principal:
            return 422, {"error": "missing or invalid 'from_principal'"}
        if not isinstance(message, str) or not message.strip():
            return 422, {"error": "missing or invalid 'message'"}

        msg_obj, task, error = self.repository.add_negotiation_message(
            task_id, from_principal, message.strip()
        )
        if error == "not_found":
            return 404, {"error": "task not found"}
        if error == "not_authorized":
            return 403, {"error": "not authorized to negotiate this task"}

        return 200, {"message": msg_obj, "task": task}

    def get_negotiations(self, task_id, skip=0, limit=1000):
        # type: (str, int, int) -> Tuple[int, dict]
        """Get the negotiation thread for a task, in order and paginated
        (never one unbounded blob) -- ``skip``/``limit`` are optional and
        additive to the pre-existing response shape."""
        if not isinstance(task_id, str) or not task_id:
            return 422, {"error": "missing or invalid 'task_id'"}

        if not self.repository.task_exists(task_id):
            return 404, {"error": "task not found"}

        return 200, {
            "task_id": task_id,
            "negotiations": self.repository.list_negotiations(
                task_id, skip=skip, limit=limit
            ),
        }

    def complete_task(self, task_id, author_principal, outcome):
        # type: (str, str, str) -> Tuple[int, dict]
        """Mark a task as completed and record reputation."""
        if not isinstance(task_id, str) or not task_id:
            return 422, {"error": "missing or invalid 'task_id'"}
        if not isinstance(author_principal, str) or not author_principal:
            return 422, {"error": "missing or invalid 'author_principal'"}
        if not isinstance(outcome, str) or not outcome.strip():
            return 422, {"error": "missing or invalid 'outcome'"}

        task = self.repository.get_task(task_id)
        if task is None:
            return 404, {"error": "task not found"}

        # Only the task author can complete
        if task["author_principal"] != author_principal:
            return 403, {"error": "only task author can complete"}

        # U10: a task is completable once a worker is engaged — either
        # directly "accepted" (human flow) or "delivered" (an agent already
        # submitted its work result over P2P).
        if task["status"] not in ("accepted", "delivered"):
            return 400, {
                "error": "task must be accepted or delivered before "
                "completion"
            }

        if not task["worker_principal"]:
            return 400, {"error": "task has no worker assigned"}

        # Record reputation for worker -- BEFORE persisting completion, so a
        # registry failure leaves the task exactly as it was (matches the
        # prior in-memory ordering).
        if self.registry_url:
            status, resp = self._record_reputation(
                task["worker_principal"], task_id, outcome
            )
            if status != 200:
                return status, resp

        updated, error = self.repository.complete_task(
            task_id, author_principal, outcome.strip()
        )
        if error is not None:
            # Preconditions were already checked above against the same
            # row; only a concurrent mutation between the checks and this
            # call could land here. Map defensively rather than 500.
            return 400, {"error": "task could not be completed"}

        self.audit_client.log(
            updated["worker_principal"], "work.complete",
            resource_id=task_id,
            details={"app_id": self.app_id,
                     "author_principal": author_principal},
        )
        return 200, {"task": updated}

    # -- P2P (U6, RFC-0003) ---------------------------------------------------

    def handle_p2p_request(self, payload, raw_body=None, headers=None):
        # type: (dict, Optional[bytes], object) -> Tuple[int, dict]
        """Process a direct P2P request from another app or agent.

        Flow: validate required fields (422) → authenticate the request
        cryptographically and bind identity (U18: only when
        ``require_signatures`` is on — 401 on a bad/missing signature, 403 if
        the verified principal is not the claimed ``requester_principal_id``;
        a pure no-op otherwise) → check permission with the Registry when one
        is configured (403 on denial, 502 if the Registry is unreachable —
        fail closed) → dispatch on ``request_type`` (400 for unknown types).
        New request types plug into ``self._p2p_handlers``.
        """
        if not isinstance(payload, dict):
            return 422, {"error": "request body must be a JSON object"}

        for field in (
            "requester_principal_id", "request_type", "capability_id"
        ):
            value = payload.get(field)
            if not isinstance(value, str) or not value:
                return 422, {"error": "missing or invalid '%s'" % field}

        # U18: authenticate FIRST, then bind identity. When the flag is off the
        # authenticator returns (None, None) and both steps are skipped, so the
        # legacy flow below is preserved byte-for-byte.
        verified_principal, auth_error = self.authenticator.authenticate(
            "POST", "/p2p/request",
            raw_body if raw_body is not None else b"",
            headers if headers is not None else {},
        )
        if auth_error is not None:
            return auth_error.status, {"error": auth_error.message}
        if verified_principal is not None and (
            verified_principal != payload["requester_principal_id"]
        ):
            return 403, {
                "error": "identity mismatch",
                "reason": "authenticated principal does not match "
                "requester_principal_id",
            }

        if self.registry_url:
            status, verdict = self._check_p2p_permission(
                payload["requester_principal_id"], payload["capability_id"]
            )
            if status != 200:
                return status, verdict
            if not verdict.get("allowed"):
                return 403, {
                    "error": "permission denied",
                    "reason": verdict.get("reason", "denied by registry"),
                }

        handler = self._p2p_handlers.get(payload["request_type"])
        if handler is None:
            return 400, {
                "error": "unknown request_type: %s" % payload["request_type"]
            }
        return handler(payload)

    def _p2p_ping(self, payload):
        # type: (dict) -> Tuple[int, dict]
        return 200, {
            "result": {"pong": True, "app_id": self.app_id},
            "evidence_id": str(uuid.uuid4()),
        }

    # -- P2P work coordination (U10) -------------------------------------------

    @staticmethod
    def _p2p_input(payload):
        # type: (dict) -> Tuple[Optional[dict], Optional[Tuple[int, dict]]]
        """Extract the ``input`` object of a P2P payload (422 on bad type)."""
        p2p_input = payload.get("input")
        if p2p_input is None:
            p2p_input = {}
        if not isinstance(p2p_input, dict):
            return None, (422, {"error": "'input' must be a JSON object"})
        return p2p_input, None

    def _p2p_list_work_opportunities(self, payload):
        # type: (dict) -> Tuple[int, dict]
        """Open tasks an agent could bid on, optionally filtered by
        capability (every marketplace task is 'marketplace.tasks' work)."""
        p2p_input, err = self._p2p_input(payload)
        if err:
            return err
        capability_filter = p2p_input.get("capability_id")
        if capability_filter is not None and not isinstance(
            capability_filter, str
        ):
            return 422, {"error": "'capability_id' must be a string"}

        opportunities = []
        if not capability_filter or capability_filter == "marketplace.tasks":
            opportunities = [
                dict(t, capability_id="marketplace.tasks")
                for t in self.repository.list_open_tasks()
            ]

        return 200, {
            "result": {"opportunities": opportunities},
            "evidence_id": str(uuid.uuid4()),
        }

    def _p2p_submit_work_bid(self, payload):
        # type: (dict) -> Tuple[int, dict]
        """An agent bids on an open task. A second bid from the same agent
        replaces its pending bid (no duplicates)."""
        p2p_input, err = self._p2p_input(payload)
        if err:
            return err
        task_id = p2p_input.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            return 422, {"error": "missing or invalid 'task_id'"}
        proposed_terms = p2p_input.get("proposed_terms")
        if not isinstance(proposed_terms, str) or not proposed_terms.strip():
            return 422, {"error": "missing or invalid 'proposed_terms'"}
        note = p2p_input.get("agent_reputation_note")
        if note is not None and not isinstance(note, str):
            return 422, {"error": "'agent_reputation_note' must be a string"}

        agent_principal = payload["requester_principal_id"]

        bid, error = self.repository.create_bid(
            task_id, agent_principal, proposed_terms.strip(), note
        )
        if error == "not_found":
            return 404, {"error": "task not found"}
        if error == "not_open":
            return 400, {"error": "task is not open for bidding"}

        self.audit_client.log(
            agent_principal, "work.bid",
            resource_id=task_id,
            details={"app_id": self.app_id, "bid_id": bid["bid_id"]},
        )
        return 200, {
            "result": {"bid": bid},
            "evidence_id": str(uuid.uuid4()),
        }

    def _p2p_get_task_status(self, payload):
        # type: (dict) -> Tuple[int, dict]
        """Task state plus the requester's own bid, so an agent can poll
        whether its bid was accepted."""
        p2p_input, err = self._p2p_input(payload)
        if err:
            return err
        task_id = p2p_input.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            return 422, {"error": "missing or invalid 'task_id'"}

        requester = payload["requester_principal_id"]
        task = self.repository.get_task(task_id)
        if task is None:
            return 404, {"error": "task not found"}
        my_bid = None
        for bid in reversed(task.get("bids", [])):
            if bid["agent_principal_id"] == requester:
                my_bid = bid
                break

        return 200, {
            "result": {"task": task, "my_bid": my_bid},
            "evidence_id": str(uuid.uuid4()),
        }

    def _p2p_submit_work_result(self, payload):
        # type: (dict) -> Tuple[int, dict]
        """The accepted agent delivers its work: the task moves to
        'delivered' and holds the work_result for author review. Unit U6:
        each submission is a NEW row in ``marketplace.work_results``
        (redelivery history is preserved), not an overwritten slot -- the
        response still surfaces a single ``work_result`` object (the
        latest), so this pre-existing response shape doesn't change."""
        p2p_input, err = self._p2p_input(payload)
        if err:
            return err
        task_id = p2p_input.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            return 422, {"error": "missing or invalid 'task_id'"}
        result_summary = p2p_input.get("result_summary")
        if not isinstance(result_summary, str) or not result_summary.strip():
            return 422, {"error": "missing or invalid 'result_summary'"}
        evidence = p2p_input.get("evidence")
        if evidence is not None and not isinstance(evidence, dict):
            return 422, {"error": "'evidence' must be a JSON object"}

        requester = payload["requester_principal_id"]
        task, error = self.repository.submit_work_result(
            task_id, requester, result_summary.strip(), evidence=evidence
        )
        if error == "not_found":
            return 404, {"error": "task not found"}
        if error == "not_accepted":
            return 400, {
                "error": "task must be accepted before submitting a "
                "work result"
            }
        if error == "forbidden":
            return 403, {
                "error": "permission denied",
                "reason": "only the accepted worker can submit the "
                "work result",
            }

        self.audit_client.log(
            requester, "work.submit",
            resource_id=task_id,
            details={"app_id": self.app_id},
        )
        return 200, {
            "result": {"task": task},
            "evidence_id": str(uuid.uuid4()),
        }

    # -- P2P competitive negotiation (U6, RFC-0002 Offer/CounterOffer) --------
    #
    # Adoption decision: request_type dispatch, not a new REST surface.
    # ``schemas/offer.schema.json``/``schemas/counter-offer.schema.json``
    # exist as RFC-0002's wire bodies for `task.offer`/`task.counter`, but
    # nothing in this codebase emitted them before this unit. The existing
    # P2P envelope (`POST /p2p/request`, RFC-0003) already carries an
    # arbitrary `request_type` + `input` body between apps/agents -- exactly
    # the transport RFC-0002's message cycle needs -- so adding two more
    # entries to `_p2p_handlers` is a natural fit; there is no dedicated
    # negotiation transport elsewhere in this codebase to prefer instead. The
    # ``input`` object for each is validated as a REAL instance of the
    # corresponding schema (`jsonschema.validate`), so this literally is the
    # wire shape now, not a hand-rolled lookalike.
    #
    # Coexistence with bids[]/agent_reputation_note: the pre-existing
    # `submit.work_bid` mechanism ("I want to do this work, here are my
    # terms/reputation") and RFC-0002's Offer/CounterOffer ("here is my
    # public price for this work") answer different questions -- a bid is
    # about WHO does the work, an offer/counter is about WHAT it costs. Nothing
    # in the existing, must-pass test suite forces these into one shape (no
    # test ties a bid's acceptance to an offer or vice versa), so -- mirroring
    # the judgment call U5's agent made keeping the legacy skills[] and
    # capabilities[] Agent Card conventions both alive, writing into the SAME
    # underlying tables rather than collapsing them -- this unit lets both
    # mechanisms coexist, persisted in their own ``marketplace.offers``/
    # ``marketplace.counter_offers`` tables alongside ``marketplace.bids``.

    def _p2p_task_offer(self, payload):
        # type: (dict) -> Tuple[int, dict]
        """A provider agent quotes a public price for an open task
        (RFC-0002 §6.2, ``schemas/offer.schema.json``)."""
        p2p_input, err = self._p2p_input(payload)
        if err:
            return err
        try:
            jsonschema.validate(instance=p2p_input, schema=_OFFER_SCHEMA)
        except jsonschema.ValidationError as exc:
            return 422, {"error": "invalid task.offer payload: %s" % exc.message}

        provider = payload["requester_principal_id"]
        offer, error = self.repository.create_offer(
            p2p_input["task_id"], provider, p2p_input["price"],
            p2p_input.get("currency", "USD"), p2p_input.get("delivery"),
            p2p_input.get("terms"),
        )
        if error == "not_found":
            return 404, {"error": "task not found"}
        if error == "not_open":
            return 400, {"error": "task is not open for offers"}

        self.audit_client.log(
            provider, "work.offer",
            resource_id=p2p_input["task_id"],
            details={"app_id": self.app_id, "offer_id": offer["offer_id"]},
        )
        return 200, {
            "result": {"offer": offer},
            "evidence_id": str(uuid.uuid4()),
        }

    def _p2p_task_counter(self, payload):
        # type: (dict) -> Tuple[int, dict]
        """The requester (task author) proposes a lower price, once, per
        task (RFC-0002 §6.3/§6.1, ``schemas/counter-offer.schema.json``)."""
        p2p_input, err = self._p2p_input(payload)
        if err:
            return err
        try:
            jsonschema.validate(
                instance=p2p_input, schema=_COUNTER_OFFER_SCHEMA
            )
        except jsonschema.ValidationError as exc:
            return 422, {
                "error": "invalid task.counter payload: %s" % exc.message
            }

        task_id = p2p_input["task_id"]
        requester = payload["requester_principal_id"]
        task = self.repository.get_task(task_id)
        if task is None:
            return 404, {"error": "task not found"}
        if requester != task["author_principal"]:
            return 403, {
                "error": "permission denied",
                "reason": "only the task author (requester) can submit a "
                "counter-offer",
            }

        counter, error = self.repository.create_counter_offer(
            task_id, p2p_input["proposed_price"],
            p2p_input.get("currency", "USD"),
        )
        if error == "not_found":
            return 404, {"error": "task not found"}
        if error == "no_standing_offer":
            return 400, {"error": "no standing offer to counter"}
        if error == "already_countered":
            return 400, {
                "error": "task.counter already submitted for this task "
                "(single round only, RFC-0002 §6.1)"
            }

        self.audit_client.log(
            requester, "work.counter",
            resource_id=task_id,
            details={"app_id": self.app_id, "counter_id": counter["counter_id"]},
        )
        return 200, {
            "result": {"counter_offer": counter},
            "evidence_id": str(uuid.uuid4()),
        }

    def _check_p2p_permission(self, requester_principal_id, capability_id):
        # type: (str, str) -> Tuple[int, dict]
        """Ask the Registry for a P2P permission verdict (fail closed)."""
        try:
            resp = requests.post(
                "%s/p2p/permissions/check" % self.registry_url,
                json={
                    "requester_principal_id": requester_principal_id,
                    "target_app_id": self.app_id,
                    "capability_id": capability_id,
                },
                timeout=self.http_timeout,
            )
            if resp.status_code != 200:
                return 403, {
                    "error": "permission denied",
                    "reason": "registry permission check returned %d"
                    % resp.status_code,
                }
            return 200, resp.json()
        except (requests.RequestException, ValueError) as exc:
            return 502, {
                "error": "registry unreachable for permission check: %s" % exc
            }

    def register_with_registry(self, app_endpoint, p2p_endpoint=None):
        # type: (str, Optional[str]) -> bool
        """Register with the Registry and discover the ecosystem (U9).

        Called by ``main()`` at startup when ``--registry-url`` is set.
        Uses the federation client (RFC-0004): the registration response
        carries ``ecosystem_apps``, so joining and discovering every other
        registered app is one round-trip; the discovered app_ids are kept
        on ``self.discovered_ecosystem``. Tolerates the Registry being
        down: returns False, never raises.
        """
        if not self.registry_url:
            return False
        client = FederationClient(
            self.registry_url, timeout=self.http_timeout
        )
        try:
            result = client.register_app(
                self.app_id,
                app_endpoint,
                p2p_endpoint or app_endpoint,
                self.capabilities,
            )
        except FederationError:
            return False
        self.discovered_ecosystem = [
            app.get("app_id") for app in result.get("ecosystem_apps", [])
        ]
        print("Discovered ecosystem: %s" % self.discovered_ecosystem)
        return True

    def _record_reputation(self, principal_id, task_id, outcome):
        # type: (str, str, str) -> Tuple[int, dict]
        """Call registry to record reputation for completed task."""
        try:
            resp = requests.post(
                "%s/users/%s/reputation"
                % (self.registry_url, principal_id),
                json={
                    "task_id": task_id,
                    "verified": True,
                    "capability_id": "marketplace.tasks",
                },
                timeout=self.http_timeout,
            )
            if resp.status_code != 200:
                return (
                    502,
                    {
                        "error": "failed to record reputation: %s"
                        % resp.json().get("error", resp.status_code)
                    },
                )
            return 200, resp.json()
        except requests.RequestException as exc:
            return (
                502,
                {
                    "error": "registry unreachable: %s" % exc
                },
            )


class MarketplaceHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, service):
        # type: (tuple, TaskService) -> None
        self.service = service
        ThreadingHTTPServer.__init__(self, address, _RequestHandler)


class _RequestHandler(BaseHTTPRequestHandler):
    server_version = "AgentTrustMarketplace/0.1"
    protocol_version = "HTTP/1.1"

    @property
    def service(self):
        # type: () -> TaskService
        return self.server.service

    def log_message(self, format, *args):  # noqa: A002
        pass  # Keep test output quiet

    def _send_json(self, status, body):
        # type: (int, dict) -> None
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(data)

    def _read_json_body(self):
        # type: () -> Tuple[Optional[dict], bytes, Optional[str]]
        """Return ``(parsed_body, raw_bytes, error)``. The RAW bytes are the
        exact payload the client signed — U18 hands them to the authenticator
        unchanged."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None, b"", "invalid Content-Length"
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}, raw, None
        try:
            body = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None, raw, "request body is not valid JSON"
        if not isinstance(body, dict):
            return None, raw, "request body must be a JSON object"
        return body, raw, None

    def _get_reputation(self, principal_id):
        # Fetch federated reputation from registry if available
        if not self.service.registry_url:
            return {
                "tasks_verified": 0,
                "tasks_rejected": 0,
                "verification_rate": None
            }
        try:
            resp = requests.get(
                "%s/users/%s" % (self.service.registry_url, principal_id),
                timeout=2.0
            )
            if resp.status_code == 200:
                data = resp.json()
                records = data.get("reputation_records", [])
                if records:
                    # Aggregate across all capabilities: a principal may have
                    # reputation from several apps (marketplace, gig-board...).
                    verified = sum(
                        r.get("tasks_verified", 0) for r in records
                    )
                    rejected = sum(
                        r.get("tasks_rejected", 0) for r in records
                    )
                    total = verified + rejected
                    return {
                        "tasks_verified": verified,
                        "tasks_rejected": rejected,
                        "verification_rate": (
                            verified / total if total else None
                        )
                    }
            return {
                "tasks_verified": 0,
                "tasks_rejected": 0,
                "verification_rate": None
            }
        except Exception:
            return {
                "tasks_verified": 0,
                "tasks_rejected": 0,
                "verification_rate": None
            }

    def _bind_org_context(self):
        # type: () -> None
        """Bind this request's RLS org-context (U9) before any repository
        call runs, via an optional ``X-Organization-Id`` header (no existing
        marketplace endpoint accepts an organization in its body/query
        shape, R10). Unconditional -- even when the header is absent -- so a
        keep-alive connection reusing this thread never inherits a prior
        request's value. ``marketplace.tasks.organization_id`` IS
        RLS-protected as of this unit (migrations/0009_rls_policies.sql,
        NULL-permissive) -- nothing populates it on any write path yet
        (this unit's reality check, and R6's known gap), so today this only
        matters for a caller that both sends the header AND hand-crafts a
        row with a real organization_id outside the normal HTTP surface.
        """
        bind_organization_id(self.headers.get("X-Organization-Id"))

    def do_OPTIONS(self):
        # type: () -> None
        """Handle CORS preflight requests."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        self._bind_org_context()
        parts = urlsplit(self.path)
        segments = [unquote(s) for s in parts.path.split("/") if s]

        if segments == ["healthz"]:
            self._send_json(200, {"status": "ok"})
        elif segments == ["api", "tasks"]:
            # GET /api/tasks?skip=0&limit=50
            query = parse_qs(parts.query)
            try:
                skip = int(query.get("skip", ["0"])[0])
                limit = int(query.get("limit", ["50"])[0])
            except ValueError:
                self._send_json(
                    400, {"error": "skip and limit must be integers"}
                )
                return
            status, body = self.service.list_tasks(skip, limit)
            self._send_json(status, body)
        elif len(segments) == 3 and segments[0] == "api" and segments[1] == "tasks":
            # GET /api/tasks/{task_id}
            status, body = self.service.get_task(segments[2])
            self._send_json(status, body)
        elif (
            len(segments) == 4
            and segments[0] == "api"
            and segments[1] == "tasks"
            and segments[3] == "bids"
        ):
            # GET /api/tasks/{task_id}/bids (U10)
            status, body = self.service.list_bids(segments[2])
            self._send_json(status, body)
        elif (
            len(segments) == 3
            and segments[0] == "api"
            and segments[1] == "negotiations"
        ):
            # GET /api/negotiations/{task_id}[?skip=0&limit=1000] (U6:
            # skip/limit are optional and additive -- the pre-existing
            # unparameterized call still returns the full thread).
            query = parse_qs(parts.query)
            try:
                skip = int(query.get("skip", ["0"])[0])
                limit = int(query.get("limit", ["1000"])[0])
            except ValueError:
                self._send_json(
                    400, {"error": "skip and limit must be integers"}
                )
                return
            status, body = self.service.get_negotiations(
                segments[2], skip=skip, limit=limit
            )
            self._send_json(status, body)
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        self._bind_org_context()
        parts = urlsplit(self.path)
        segments = [unquote(s) for s in parts.path.split("/") if s]
        body, raw_body, error = self._read_json_body()
        if error:
            self._send_json(400, {"error": error})
            return

        if segments == ["api", "auth", "register"]:
            # POST /api/auth/register - Register and optionally sync to registry
            principal_id = body.get("principal_id")
            if not principal_id:
                self._send_json(422, {"error": "missing principal_id"})
                return
            # Register in central registry if configured
            if self.service.registry_url:
                try:
                    requests.post(
                        "%s/auth/register" % self.service.registry_url,
                        json={"principal_id": principal_id},
                        timeout=2.0
                    )
                except Exception:
                    pass  # Ignore registry sync errors during registration
            reputation = self._get_reputation(principal_id)
            self._send_json(200, {
                "principal_id": principal_id,
                "reputation": reputation
            })
        elif segments == ["api", "auth", "login"]:
            # POST /api/auth/login - Login and fetch federated reputation from registry
            principal_id = body.get("principal_id")
            if not principal_id:
                self._send_json(422, {"error": "missing principal_id"})
                return
            # Fetch reputation from registry if available
            reputation = self._get_reputation(principal_id)
            self._send_json(200, {
                "principal_id": principal_id,
                "reputation": reputation
            })
        elif segments == ["api", "tasks"]:
            # POST /api/tasks
            status, response = self.service.create_task(
                body.get("principal_id"),
                body.get("description"),
            )
            self._send_json(status, response)
        elif (
            len(segments) == 4
            and segments[0] == "api"
            and segments[1] == "tasks"
            and segments[3] == "accept"
        ):
            # POST /api/tasks/{task_id}/accept
            status, response = self.service.accept_task(
                segments[2],
                body.get("worker_principal"),
            )
            self._send_json(status, response)
        elif (
            len(segments) == 6
            and segments[0] == "api"
            and segments[1] == "tasks"
            and segments[3] == "bids"
            and segments[5] == "accept"
        ):
            # POST /api/tasks/{task_id}/bids/{bid_id}/accept (U10)
            status, response = self.service.accept_bid(
                segments[2],
                segments[4],
                body.get("author_principal"),
            )
            self._send_json(status, response)
        elif (
            len(segments) == 3
            and segments[0] == "api"
            and segments[1] == "negotiations"
        ):
            # POST /api/negotiations/{task_id}
            status, response = self.service.send_negotiation_message(
                segments[2],
                body.get("from_principal"),
                body.get("message"),
            )
            self._send_json(status, response)
        elif (
            len(segments) == 4
            and segments[0] == "api"
            and segments[1] == "negotiations"
            and segments[3] == "complete"
        ):
            # POST /api/negotiations/{task_id}/complete
            status, response = self.service.complete_task(
                segments[2],
                body.get("author_principal"),
                body.get("outcome"),
            )
            self._send_json(status, response)
        elif segments == ["p2p", "request"]:
            # POST /p2p/request - direct P2P request (U6, RFC-0003). The RAW
            # signed bytes + headers are handed through for U18 authentication.
            status, response = self.service.handle_p2p_request(
                body, raw_body=raw_body, headers=self.headers
            )
            self._send_json(status, response)
        else:
            self._send_json(404, {"error": "not found"})


def make_server(
    port=8001,
    host="127.0.0.1",
    registry_url=None,
    audit_url=None,
    require_signatures=False,
    public_key_resolver=None,
    db=None,
    repository=None,
):
    # type: (int, str, Optional[str], Optional[str], bool, object, object, Optional[MarketplaceRepository]) -> MarketplaceHTTPServer
    """Build the marketplace server. ``db``/``repository`` are injectable
    (unit U6) -- tests point a fresh server at a specific DSN, or at a fake
    repository entirely; omitted, ``TaskService`` builds its own
    ``Database()`` from the ``DATABASE_URL`` env var."""
    service = TaskService(
        registry_url=registry_url,
        audit_url=audit_url,
        require_signatures=require_signatures,
        public_key_resolver=public_key_resolver,
        db=db,
        repository=repository,
    )
    return MarketplaceHTTPServer((host, port), service)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="AgentTrust Task Marketplace"
    )
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--registry-url",
        default=None,
        help="Registry URL for recording reputation (optional).",
    )
    parser.add_argument(
        "--audit-url",
        default=None,
        help="Base URL of the central Audit service (U12). Emission is "
        "best-effort: a down audit service is never fatal.",
    )
    parser.add_argument(
        "--require-signatures",
        action="store_true",
        help="Enforce cryptographic authentication on P2P requests (U18, "
        "RFC-0005). Off by default (unsigned P2P is accepted).",
    )
    args = parser.parse_args(argv)

    server = make_server(
        port=args.port,
        host=args.host,
        registry_url=args.registry_url,
        audit_url=args.audit_url,
        require_signatures=args.require_signatures,
    )
    host, port = server.server_address[:2]
    print("AgentTrust Marketplace listening on http://%s:%d" % (host, port))
    if args.registry_url:
        print("(connected to registry: %s)" % args.registry_url)
        # Register this app's P2P endpoint with the Registry (tolerates the
        # registry being down; P2P discovery just won't find us until it is
        # up and we re-register on next restart).
        app_endpoint = "http://%s:%d" % (host, port)
        if server.service.register_with_registry(app_endpoint):
            print("(registered P2P endpoint with registry)")
        else:
            print("(warning: could not register P2P endpoint with registry)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()
