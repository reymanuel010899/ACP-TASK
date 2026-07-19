"""Service Provider Directory & Booking (unit U4).

A federated gig board where users can register as service providers,
browse available providers, and hire them for gigs. Reputation is recorded
in the shared registry to prove federation across different domains.

API endpoints:
- POST   /api/services              # Register as service provider
- GET    /api/services              # List all providers/services
- GET    /api/services/{service_id} # Get provider details
- POST   /api/gigs                  # Create booking (hire provider)
- GET    /api/gigs                  # List my gigs
- POST   /api/gigs/{gig_id}/complete # Mark gig complete -> reputation
- POST   /p2p/request               # Direct P2P request from another
  app/agent (U6, RFC-0003): permission is checked with the Registry when
  configured; standalone mode (no --registry-url) processes without it.
  Request types (U10 adds the work-coordination types): ping,
  list.work_opportunities (discover offered services),
  register.service (an agent registers itself as a provider).

Run: python -m apps.gig_board.server.app [--port 8002] [--registry-url URL]
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

from libs.audit_client import make_audit_client
from libs.federation_client import FederationClient, FederationError


class GigBoardService:
    """Core gig board logic; in-memory storage."""

    APP_ID = "gig-board"
    P2P_CAPABILITIES = ["gig-board.gigs", "p2p.ping"]

    def __init__(self, registry_url=None, http_timeout=3.0, audit_url=None):
        # type: (Optional[str], float, Optional[str]) -> None
        self.registry_url = (
            registry_url.rstrip("/") if registry_url else None
        )
        self.http_timeout = http_timeout
        # Central audit emitter (U12): best-effort, fire-and-forget; a
        # NullAuditClient (no-op) when no audit_url is configured.
        self.audit_client = make_audit_client(audit_url)
        self.services = {}  # type: Dict[str, dict]
        self.gigs = {}  # type: Dict[str, dict]
        self.lock = threading.Lock()
        self.app_id = self.APP_ID
        self.capabilities = list(self.P2P_CAPABILITIES)
        # app_ids discovered at registration time (U9, RFC-0004).
        self.discovered_ecosystem = []  # type: list
        # request_type -> handler(payload); U10 plugs real work types in here.
        self._p2p_handlers = {
            "ping": self._p2p_ping,
            "list.work_opportunities": self._p2p_list_work_opportunities,
            "register.service": self._p2p_register_service,
        }

    def register_service(self, principal_id, service_name, description):
        # type: (str, str, str) -> Tuple[int, dict]
        """Register as a service provider."""
        if not isinstance(principal_id, str) or not principal_id:
            return 422, {"error": "missing or invalid 'principal_id'"}
        if not isinstance(service_name, str) or not service_name.strip():
            return 422, {"error": "missing or invalid 'service_name'"}
        if not isinstance(description, str) or not description.strip():
            return 422, {"error": "missing or invalid 'description'"}

        service_id = str(uuid.uuid4())
        service = {
            "id": service_id,
            "provider_principal": principal_id,
            "service_name": service_name.strip(),
            "description": description.strip(),
            "created_at": datetime.utcnow().isoformat(),
            "gigs_completed": 0,
            "rating": None,
        }

        with self.lock:
            self.services[service_id] = service

        return 200, {"service": service}

    def list_services(self, skip=0, limit=50):
        # type: (int, int) -> Tuple[int, dict]
        """List all service providers with pagination."""
        if not isinstance(skip, int) or skip < 0:
            return 400, {"error": "skip must be a non-negative integer"}
        if not isinstance(limit, int) or limit < 1 or limit > 100:
            return 400, {"error": "limit must be between 1 and 100"}

        with self.lock:
            all_services = list(self.services.values())

        # Sort by created_at descending
        all_services.sort(
            key=lambda s: s.get("created_at", ""), reverse=True
        )

        total = len(all_services)
        services = all_services[skip : skip + limit]

        return 200, {
            "services": services,
            "total": total,
            "skip": skip,
            "limit": limit,
        }

    def get_service(self, service_id):
        # type: (str) -> Tuple[int, dict]
        """Get a specific service by ID."""
        if not isinstance(service_id, str) or not service_id:
            return 422, {"error": "missing or invalid 'service_id'"}

        with self.lock:
            service = self.services.get(service_id)

        if service is None:
            return 404, {"error": "service not found"}

        return 200, {"service": service}

    def create_gig(self, service_id, buyer_principal, description):
        # type: (str, str, str) -> Tuple[int, dict]
        """Create a booking (hire a service provider)."""
        if not isinstance(service_id, str) or not service_id:
            return 422, {"error": "missing or invalid 'service_id'"}
        if not isinstance(buyer_principal, str) or not buyer_principal:
            return 422, {"error": "missing or invalid 'buyer_principal'"}
        if not isinstance(description, str) or not description.strip():
            return 422, {"error": "missing or invalid 'description'"}

        with self.lock:
            service = self.services.get(service_id)

        if service is None:
            return 404, {"error": "service not found"}

        # Can't hire yourself
        if service["provider_principal"] == buyer_principal:
            return 400, {"error": "cannot hire yourself"}

        gig_id = str(uuid.uuid4())
        gig = {
            "id": gig_id,
            "service_id": service_id,
            "provider_principal": service["provider_principal"],
            "buyer_principal": buyer_principal,
            "description": description.strip(),
            "status": "active",
            "created_at": datetime.utcnow().isoformat(),
            "completed_at": None,
            "outcome": None,
        }

        with self.lock:
            self.gigs[gig_id] = gig

        return 200, {"gig": gig}

    def list_gigs(self, principal_id, skip=0, limit=50):
        # type: (str, int, int) -> Tuple[int, dict]
        """List gigs for a user (as buyer or provider)."""
        if not isinstance(principal_id, str) or not principal_id:
            return 422, {"error": "missing or invalid 'principal_id'"}
        if not isinstance(skip, int) or skip < 0:
            return 400, {"error": "skip must be a non-negative integer"}
        if not isinstance(limit, int) or limit < 1 or limit > 100:
            return 400, {"error": "limit must be between 1 and 100"}

        with self.lock:
            all_gigs = [
                g
                for g in self.gigs.values()
                if g["provider_principal"] == principal_id
                or g["buyer_principal"] == principal_id
            ]

        # Sort by created_at descending
        all_gigs.sort(key=lambda g: g.get("created_at", ""), reverse=True)

        total = len(all_gigs)
        gigs = all_gigs[skip : skip + limit]

        return 200, {
            "gigs": gigs,
            "total": total,
            "skip": skip,
            "limit": limit,
        }

    def complete_gig(self, gig_id, buyer_principal, outcome):
        # type: (str, str, str) -> Tuple[int, dict]
        """Mark a gig as completed and record reputation."""
        if not isinstance(gig_id, str) or not gig_id:
            return 422, {"error": "missing or invalid 'gig_id'"}
        if not isinstance(buyer_principal, str) or not buyer_principal:
            return 422, {"error": "missing or invalid 'buyer_principal'"}
        if not isinstance(outcome, str) or not outcome.strip():
            return 422, {"error": "missing or invalid 'outcome'"}

        with self.lock:
            gig = self.gigs.get(gig_id)

        if gig is None:
            return 404, {"error": "gig not found"}

        # Only the buyer can complete
        if gig["buyer_principal"] != buyer_principal:
            return 403, {"error": "only gig buyer can complete"}

        if gig["status"] != "active":
            return 400, {"error": "gig must be active before completion"}

        # Record reputation for provider
        if self.registry_url:
            status, resp = self._record_reputation(
                gig["provider_principal"], gig_id, outcome
            )
            if status != 200:
                return status, resp

        with self.lock:
            gig["status"] = "completed"
            gig["outcome"] = outcome.strip()
            gig["completed_at"] = datetime.utcnow().isoformat()
            # Update service stats
            service = self.services.get(gig["service_id"])
            if service:
                service["gigs_completed"] = (
                    service.get("gigs_completed", 0) + 1
                )

        self.audit_client.log(
            gig["provider_principal"], "work.complete",
            resource_id=gig_id,
            details={"app_id": self.app_id,
                     "buyer_principal": buyer_principal},
        )
        return 200, {"gig": gig}

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
        """Available services (with provider info) an agent can discover,
        optionally filtered by capability. Services registered through the
        human API default to the 'gig-board.gigs' capability."""
        p2p_input, err = self._p2p_input(payload)
        if err:
            return err
        capability_filter = p2p_input.get("capability_id")
        if capability_filter is not None and not isinstance(
            capability_filter, str
        ):
            return 422, {"error": "'capability_id' must be a string"}

        with self.lock:
            all_services = list(self.services.values())
        all_services.sort(
            key=lambda s: s.get("created_at", ""), reverse=True
        )

        opportunities = []
        for service in all_services:
            capability = service.get("capability_id", "gig-board.gigs")
            if capability_filter and capability != capability_filter:
                continue
            opportunities.append(
                {
                    "id": service["id"],
                    "service_name": service["service_name"],
                    "description": service["description"],
                    "provider_principal": service["provider_principal"],
                    "created_at": service["created_at"],
                    "capability_id": capability,
                    "gigs_completed": service.get("gigs_completed", 0),
                }
            )

        return 200, {
            "result": {"opportunities": opportunities},
            "evidence_id": str(uuid.uuid4()),
        }

    def _p2p_register_service(self, payload):
        # type: (dict) -> Tuple[int, dict]
        """An agent registers ITSELF as a service provider (U10): the
        requesting principal becomes ``provider_principal``, so the normal
        buyer flow (create_gig -> complete_gig) then records the agent's
        reputation."""
        p2p_input, err = self._p2p_input(payload)
        if err:
            return err
        name = p2p_input.get("name")
        if not isinstance(name, str) or not name.strip():
            return 422, {"error": "missing or invalid 'name'"}
        description = p2p_input.get("description")
        if not isinstance(description, str) or not description.strip():
            return 422, {"error": "missing or invalid 'description'"}
        capability_id = p2p_input.get("capability_id")
        if capability_id is not None and (
            not isinstance(capability_id, str) or not capability_id
        ):
            return 422, {"error": "'capability_id' must be a string"}
        pricing = p2p_input.get("pricing")
        if pricing is not None and not isinstance(pricing, (str, dict)):
            return 422, {
                "error": "'pricing' must be a string or JSON object"
            }

        requester = payload["requester_principal_id"]
        status, response = self.register_service(requester, name, description)
        if status != 200:
            return status, response

        service = response["service"]
        with self.lock:
            service["capability_id"] = (
                capability_id if capability_id else "gig-board.gigs"
            )
            if pricing is not None:
                service["pricing"] = pricing

        # "service.register" extends the standard audit vocabulary (the
        # vocabulary is open by design): an agent registered ITSELF as a
        # gig-board service provider via P2P.
        self.audit_client.log(
            requester, "service.register",
            resource_id=service["id"],
            details={"app_id": self.app_id,
                     "capability_id": service["capability_id"]},
        )
        return 200, {
            "result": {"service": service},
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

    def _record_reputation(self, principal_id, gig_id, outcome):
        # type: (str, str, str) -> Tuple[int, dict]
        """Call registry to record reputation for completed gig."""
        try:
            resp = requests.post(
                "%s/users/%s/reputation"
                % (self.registry_url, principal_id),
                json={
                    "task_id": gig_id,
                    "verified": True,
                    "capability_id": "gig-board.gigs",
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


class GigBoardHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, service):
        # type: (tuple, GigBoardService) -> None
        self.service = service
        ThreadingHTTPServer.__init__(self, address, _RequestHandler)


class _RequestHandler(BaseHTTPRequestHandler):
    server_version = "AgentTrustGigBoard/0.1"
    protocol_version = "HTTP/1.1"

    @property
    def service(self):
        # type: () -> GigBoardService
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
        elif segments == ["api", "services"]:
            query = parse_qs(parts.query)
            try:
                skip = int(query.get("skip", ["0"])[0])
                limit = int(query.get("limit", ["50"])[0])
            except ValueError:
                self._send_json(
                    400, {"error": "skip and limit must be integers"}
                )
                return
            status, body = self.service.list_services(skip, limit)
            self._send_json(status, body)
        elif len(segments) == 3 and segments[0] == "api" and segments[1] == "services":
            status, body = self.service.get_service(segments[2])
            self._send_json(status, body)
        elif segments == ["api", "gigs"]:
            query = parse_qs(parts.query)
            principal_id = query.get("principal_id", [None])[0]
            if not principal_id:
                self._send_json(400, {"error": "principal_id query param required"})
                return
            try:
                skip = int(query.get("skip", ["0"])[0])
                limit = int(query.get("limit", ["50"])[0])
            except ValueError:
                self._send_json(
                    400, {"error": "skip and limit must be integers"}
                )
                return
            status, body = self.service.list_gigs(principal_id, skip, limit)
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
        elif segments == ["api", "services"]:
            status, response = self.service.register_service(
                body.get("principal_id"),
                body.get("service_name"),
                body.get("description"),
            )
            self._send_json(status, response)
        elif segments == ["api", "gigs"]:
            status, response = self.service.create_gig(
                body.get("service_id"),
                body.get("buyer_principal"),
                body.get("description"),
            )
            self._send_json(status, response)
        elif (
            len(segments) == 4
            and segments[0] == "api"
            and segments[1] == "gigs"
            and segments[3] == "complete"
        ):
            status, response = self.service.complete_gig(
                segments[2],
                body.get("buyer_principal"),
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
    port=8002,
    host="127.0.0.1",
    registry_url=None,
    audit_url=None,
):
    # type: (int, str, Optional[str], Optional[str]) -> GigBoardHTTPServer
    """Build the gig board server."""
    service = GigBoardService(registry_url=registry_url, audit_url=audit_url)
    return GigBoardHTTPServer((host, port), service)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="AgentTrust Gig Board"
    )
    parser.add_argument("--port", type=int, default=8002)
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
    args = parser.parse_args(argv)

    server = make_server(
        port=args.port,
        host=args.host,
        registry_url=args.registry_url,
        audit_url=args.audit_url,
    )
    host, port = server.server_address[:2]
    print("AgentTrust Gig Board listening on http://%s:%d" % (host, port))
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
