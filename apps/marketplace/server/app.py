"""Task Marketplace Backend (unit U3).

A federated task marketplace where users post tasks, accept them, negotiate
outcomes, and earn reputation through the registry.

API endpoints:
- POST /api/tasks - Create new task
- GET /api/tasks - List all tasks (with pagination/filters)
- GET /api/tasks/{task_id} - Get task details
- POST /api/tasks/{task_id}/accept - Accept task (user becomes worker)
- POST /api/negotiations/{task_id} - Send negotiation message
- GET /api/negotiations/{task_id} - Get negotiation thread
- POST /api/negotiations/{task_id}/complete - Mark task complete with outcome
- POST /p2p/request - Direct P2P request from another app/agent (U6,
  RFC-0003): permission is checked with the Registry when configured;
  standalone mode (no --registry-url) processes without the check.

Run: python -m apps.marketplace.server.app [--port 8001] [--registry-url URL]
"""

import argparse
import json
import threading
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlsplit

import requests

from libs.federation_client import FederationClient, FederationError


class TaskService:
    """Core task marketplace logic; in-memory storage."""

    APP_ID = "marketplace"
    P2P_CAPABILITIES = ["marketplace.tasks", "p2p.ping"]

    def __init__(self, registry_url=None, http_timeout=3.0):
        # type: (Optional[str], float) -> None
        self.registry_url = (
            registry_url.rstrip("/") if registry_url else None
        )
        self.http_timeout = http_timeout
        self.tasks = {}  # type: Dict[str, dict]
        self.lock = threading.Lock()
        self.app_id = self.APP_ID
        self.capabilities = list(self.P2P_CAPABILITIES)
        # app_ids discovered at registration time (U9, RFC-0004).
        self.discovered_ecosystem = []  # type: list
        # request_type -> handler(payload); U10 plugs real work types in here.
        self._p2p_handlers = {"ping": self._p2p_ping}

    def create_task(self, principal_id, description):
        # type: (str, str) -> Tuple[int, dict]
        """Create a new task."""
        if not isinstance(principal_id, str) or not principal_id:
            return 422, {"error": "missing or invalid 'principal_id'"}
        if not isinstance(description, str) or not description.strip():
            return 422, {"error": "missing or invalid 'description'"}

        task_id = str(uuid.uuid4())
        task = {
            "id": task_id,
            "author_principal": principal_id,
            "description": description.strip(),
            "status": "open",
            "created_at": datetime.utcnow().isoformat(),
            "worker_principal": None,
            "negotiations": [],
            "outcome": None,
        }

        with self.lock:
            self.tasks[task_id] = task

        return 200, {"task": task}

    def list_tasks(self, skip=0, limit=50):
        # type: (int, int) -> Tuple[int, dict]
        """List all tasks with pagination."""
        if not isinstance(skip, int) or skip < 0:
            return 400, {"error": "skip must be a non-negative integer"}
        if not isinstance(limit, int) or limit < 1 or limit > 100:
            return 400, {"error": "limit must be between 1 and 100"}

        with self.lock:
            all_tasks = list(self.tasks.values())

        # Sort by created_at descending
        all_tasks.sort(
            key=lambda t: t.get("created_at", ""), reverse=True
        )

        total = len(all_tasks)
        tasks = all_tasks[skip : skip + limit]

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

        with self.lock:
            task = self.tasks.get(task_id)

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

        with self.lock:
            task = self.tasks.get(task_id)

        if task is None:
            return 404, {"error": "task not found"}

        if task["status"] != "open":
            return 400, {"error": "task is not open for acceptance"}

        if task["author_principal"] == worker_principal:
            return 400, {"error": "cannot accept your own task"}

        with self.lock:
            task["status"] = "accepted"
            task["worker_principal"] = worker_principal

        return 200, {"task": task}

    def send_negotiation_message(self, task_id, from_principal, message):
        # type: (str, str, str) -> Tuple[int, dict]
        """Send a negotiation message for a task."""
        if not isinstance(task_id, str) or not task_id:
            return 422, {"error": "missing or invalid 'task_id'"}
        if not isinstance(from_principal, str) or not from_principal:
            return 422, {"error": "missing or invalid 'from_principal'"}
        if not isinstance(message, str) or not message.strip():
            return 422, {"error": "missing or invalid 'message'"}

        with self.lock:
            task = self.tasks.get(task_id)

        if task is None:
            return 404, {"error": "task not found"}

        # Only author and worker can negotiate
        if (
            from_principal != task["author_principal"]
            and from_principal != task["worker_principal"]
        ):
            return 403, {"error": "not authorized to negotiate this task"}

        msg_obj = {
            "from": from_principal,
            "message": message.strip(),
            "timestamp": datetime.utcnow().isoformat(),
        }

        with self.lock:
            task["negotiations"].append(msg_obj)

        return 200, {"message": msg_obj, "task": task}

    def get_negotiations(self, task_id):
        # type: (str) -> Tuple[int, dict]
        """Get all negotiation messages for a task."""
        if not isinstance(task_id, str) or not task_id:
            return 422, {"error": "missing or invalid 'task_id'"}

        with self.lock:
            task = self.tasks.get(task_id)

        if task is None:
            return 404, {"error": "task not found"}

        return 200, {
            "task_id": task_id,
            "negotiations": task["negotiations"],
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

        with self.lock:
            task = self.tasks.get(task_id)

        if task is None:
            return 404, {"error": "task not found"}

        # Only the task author can complete
        if task["author_principal"] != author_principal:
            return 403, {"error": "only task author can complete"}

        if task["status"] != "accepted":
            return 400, {"error": "task must be accepted before completion"}

        if not task["worker_principal"]:
            return 400, {"error": "task has no worker assigned"}

        # Record reputation for worker
        if self.registry_url:
            status, resp = self._record_reputation(
                task["worker_principal"], task_id, outcome
            )
            if status != 200:
                return status, resp

        with self.lock:
            task["status"] = "completed"
            task["outcome"] = outcome.strip()

        return 200, {"task": task}

    # -- P2P (U6, RFC-0003) ---------------------------------------------------

    def handle_p2p_request(self, payload):
        # type: (dict) -> Tuple[int, dict]
        """Process a direct P2P request from another app or agent.

        Flow: validate required fields (422) → check permission with the
        Registry when one is configured (403 on denial, 502 if the Registry
        is unreachable — fail closed) → dispatch on ``request_type``
        (400 for unknown types). New request types plug into
        ``self._p2p_handlers``.
        """
        if not isinstance(payload, dict):
            return 422, {"error": "request body must be a JSON object"}

        for field in (
            "requester_principal_id", "request_type", "capability_id"
        ):
            value = payload.get(field)
            if not isinstance(value, str) or not value:
                return 422, {"error": "missing or invalid '%s'" % field}

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
        # type: () -> Tuple[Optional[dict], Optional[str]]
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None, "invalid Content-Length"
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}, None
        try:
            body = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None, "request body is not valid JSON"
        if not isinstance(body, dict):
            return None, "request body must be a JSON object"
        return body, None

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
                    latest = records[-1]
                    return {
                        "tasks_verified": latest.get("tasks_verified", 0),
                        "tasks_rejected": latest.get("tasks_rejected", 0),
                        "verification_rate": latest.get("verification_rate")
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

    def do_OPTIONS(self):
        # type: () -> None
        """Handle CORS preflight requests."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
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
            len(segments) == 3
            and segments[0] == "api"
            and segments[1] == "negotiations"
        ):
            # GET /api/negotiations/{task_id}
            status, body = self.service.get_negotiations(segments[2])
            self._send_json(status, body)
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        parts = urlsplit(self.path)
        segments = [unquote(s) for s in parts.path.split("/") if s]
        body, error = self._read_json_body()
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
            # POST /p2p/request - direct P2P request (U6, RFC-0003)
            status, response = self.service.handle_p2p_request(body)
            self._send_json(status, response)
        else:
            self._send_json(404, {"error": "not found"})


def make_server(
    port=8001,
    host="127.0.0.1",
    registry_url=None,
):
    # type: (int, str, Optional[str]) -> MarketplaceHTTPServer
    """Build the marketplace server."""
    service = TaskService(registry_url=registry_url)
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
    args = parser.parse_args(argv)

    server = make_server(
        port=args.port,
        host=args.host,
        registry_url=args.registry_url,
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
