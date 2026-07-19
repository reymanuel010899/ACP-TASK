"""AgentTrust Reference Registry (unit U4).

A capability-search directory indexing Principals, their A2A Agent Cards,
and per-capability reputation summaries. Stdlib-only HTTP layer
(``http.server.ThreadingHTTPServer``); all core logic lives in
:class:`RegistryService` so tests can call it directly without HTTP.

API contract (the federatable surface, R5)
------------------------------------------
This contract — not this instance — is the unit of interoperability. Any
party can run a registry replicating these endpoints, and no agent may treat
one instance as the only valid directory; requesters SHOULD be pointable at
any registry (or several) that speaks this contract.

- ``POST /register`` — body ``{"agent_card": ..., "principal_id": ...,
  "api_key": ...}``. Requires a valid invite/API key issued by *this*
  registry (anti-Sybil friction, KTD8): 403 without one. The Agent Card must
  declare the AgentTrust extension (uri
  ``https://agenttrust.example/extensions/trust/v1`` in
  ``capabilities.extensions[]``): 422 otherwise. Each ``skills[].id`` on the
  card is indexed as a capability id.
- ``POST /admin/api-keys`` — mints and returns ``{"api_key": ...}``. This is
  how the first key gets bootstrapped (the demo runbook calls it). v1: an
  unauthenticated admin surface, acceptable at demo scale only; production
  would gate it behind operator auth. Keys can also be seeded from a JSON
  array file via ``--api-keys-file``.
- ``GET /search?capability=<id>[&min_reputation=<x>]`` — returns
  ``{"candidates": [{principal_id, agent_card, reputation_summary}]}``.
  ``reputation_summary`` is the (principal, capability) Reputation Record
  slice ``{capability_id, tasks_verified, tasks_rejected,
  verification_rate}``; per RFC-0001 §neutral-reputation it is
  ``0/0/null`` when there is no history. With ``min_reputation`` set,
  candidates whose ``verification_rate`` is null OR below the threshold are
  excluded — an explicit threshold is an opt-in to "proven only", so a
  no-history (neutral) agent does not pass it.
- ``GET /agents/{principal_id}`` — an agent Principal (U5) as
  ``{"agent": ..., "reputation": ...}``, falling back to the stored U4
  agent-card registration as ``{"registration": ...}``; 404 for neither.
- ``POST /agents/register`` — body ``{"agent_card": {name, description,
  capabilities: [str], pricing?}, "principal_id": ..., "created_by":
  <user principal_id>, "public_key"?: ...}``. Registers an agent as a
  first-class Principal (U5) with independent reputation. Per Decision 8
  only the PUBLIC side is registered — the Registry never receives private
  keys; ``public_key`` is optional, for future signature verification.
  Duplicate principal_id is 409; bad/missing fields are 422. Agent
  reputation flows through the SAME mechanism as users:
  ``POST /users/{principal_id}/reputation`` accepts agent principals.
- ``GET /agents?capability=<id>`` — agent Principals declaring that
  capability, ``{"agents": [...]}`` (empty list if none).
- ``GET /healthz`` — 200.

Reputation sourcing (integration decision)
------------------------------------------
Two mutually exclusive read paths, both implemented:

* **In-process**: inject a ``ReputationStore`` shared with a U3
  ``VerificationService`` — verdicts recorded there are visible to searches
  immediately, no sync step (used by tests and single-process demos).
* **HTTP**: pass ``--verification-url`` and the registry lazily fetches
  ``GET {url}/reputation/{principal_id}?capability_id=...`` per search
  candidate. If the verification service is down or answers garbage, the
  candidate's reputation is treated as unknown/neutral (null rate) rather
  than failing the search.

With neither configured, all reputation is neutral.

Run: ``python -m registry.app --port 8090 [--verification-url URL]
[--api-keys-file PATH] [--index-path PATH]``
"""

import argparse
import hmac
import json

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional, Tuple
from urllib.parse import parse_qs, quote, unquote, urlsplit

from registry.agent_index import AgentIndex
from registry.index_store import IndexStore, card_capability_ids
from registry.user_index import UserIndex

TRUST_EXTENSION_URI = "https://agenttrust.example/extensions/trust/v1"

DEFAULT_HTTP_TIMEOUT = 3.0


def neutral_summary(capability_id):
    # type: (str) -> dict
    """RFC-0001 §neutral-reputation: no data is null, never 0.0."""
    return {
        "capability_id": capability_id,
        "tasks_verified": 0,
        "tasks_rejected": 0,
        "verification_rate": None,
    }


def card_declares_trust_extension(agent_card):
    # type: (dict) -> bool
    capabilities = agent_card.get("capabilities")
    if not isinstance(capabilities, dict):
        return False
    extensions = capabilities.get("extensions")
    if not isinstance(extensions, list):
        return False
    return any(
        isinstance(ext, dict) and ext.get("uri") == TRUST_EXTENSION_URI
        for ext in extensions
    )


class RegistryService(object):
    """Core registry logic; callable directly from tests (no HTTP)."""

    def __init__(
        self,
        index,
        reputation_store=None,
        verification_url=None,
        admin_token=None,
        http_timeout=DEFAULT_HTTP_TIMEOUT,
        user_index=None,
        agent_index=None,
    ):
        # type: (IndexStore, Optional[object], Optional[str], Optional[str], float, Optional[UserIndex], Optional[AgentIndex]) -> None
        self.index = index
        self.reputation_store = reputation_store
        self.verification_url = (
            verification_url.rstrip("/") if verification_url else None
        )
        # Optional admin bearer token gating POST /admin/api-keys (KTD-A5).
        # None = open (demo default). Never serialized.
        self.admin_token = admin_token
        self.http_timeout = http_timeout
        self.user_index = user_index if user_index is not None else UserIndex()
        self.agent_index = (
            agent_index if agent_index is not None else AgentIndex()
        )

    def admin_ok(self, token):
        # type: (Optional[str]) -> bool
        """True when admin access is allowed: no token configured (open), or
        the presented token matches (constant-time) the configured one."""
        if self.admin_token is None:
            return True
        return token is not None and hmac.compare_digest(token, self.admin_token)

    # -- API keys ----------------------------------------------------------------

    def create_api_key(self):
        # type: () -> str
        return self.index.issue_api_key()

    # -- registration -------------------------------------------------------------

    def register(self, payload):
        # type: (dict) -> Tuple[int, dict]
        """Returns ``(http_status, response_body)``."""
        if not isinstance(payload, dict):
            return 422, {"error": "request body must be a JSON object"}

        # (1) Anti-Sybil gate first: no valid invite key, no registration.
        if not self.index.is_valid_api_key(payload.get("api_key")):
            return 403, {
                "error": "a valid registry-issued api_key is required to "
                "register (mint one via POST /admin/api-keys)"
            }

        principal_id = payload.get("principal_id")
        if not isinstance(principal_id, str) or not principal_id:
            return 422, {"error": "missing or non-string 'principal_id'"}
        agent_card = payload.get("agent_card")
        if not isinstance(agent_card, dict):
            return 422, {"error": "missing or non-object 'agent_card'"}

        # (2) The card must opt in to the trust layer.
        if not card_declares_trust_extension(agent_card):
            return 422, {
                "error": "agent_card does not declare the AgentTrust "
                "extension (%s) in capabilities.extensions[]"
                % TRUST_EXTENSION_URI
            }

        registration = self.index.register(principal_id, agent_card)
        return 200, {
            "registration": registration,
            "capability_ids": card_capability_ids(agent_card),
        }

    # -- search ----------------------------------------------------------------

    def search(self, capability_id, min_reputation=None):
        # type: (str, Optional[float]) -> Tuple[int, dict]
        if not isinstance(capability_id, str) or not capability_id:
            return 400, {"error": "missing 'capability' parameter"}
        candidates = []
        for registration in self.index.find_by_capability(capability_id):
            summary = self._reputation_summary(
                registration["principal_id"], capability_id
            )
            if min_reputation is not None:
                rate = summary.get("verification_rate")
                # Neutral/unknown (null) does not pass an explicit threshold.
                if rate is None or rate < min_reputation:
                    continue
            candidates.append(
                {
                    "principal_id": registration["principal_id"],
                    "agent_card": registration["agent_card"],
                    "reputation_summary": summary,
                }
            )
        return 200, {"capability": capability_id, "candidates": candidates}

    def get_agent(self, principal_id):
        # type: (str) -> Tuple[int, dict]
        # Agent Principals (U5) first; legacy agent-card registrations (U4)
        # as a fallback so the pre-existing lookup contract keeps working.
        agent = self.agent_index.get_agent(principal_id)
        if agent is not None:
            return 200, {
                "agent": agent,
                "reputation": self.user_index.get_aggregated_reputation(
                    principal_id
                ),
            }
        registration = self.index.get(principal_id)
        if registration is None:
            return 404, {"error": "no registration for that principal_id"}
        return 200, {"registration": registration}

    # -- agent principal endpoints (U5) ----------------------------------------

    def register_agent(self, payload):
        # type: (dict) -> Tuple[int, dict]
        """Register an agent as a first-class Principal.

        Key custody (Decision 8): only the PUBLIC side is registered
        (``principal_id`` + optional ``public_key``); the Registry never
        receives private keys. Returns ``(http_status, response_body)``.
        """
        if not isinstance(payload, dict):
            return 422, {"error": "request body must be a JSON object"}

        principal_id = payload.get("principal_id")
        if not isinstance(principal_id, str) or not principal_id:
            return 422, {"error": "missing or non-string 'principal_id'"}

        created_by = payload.get("created_by")
        if not isinstance(created_by, str) or not created_by:
            return 422, {"error": "missing or non-string 'created_by'"}

        agent_card = payload.get("agent_card")
        if not isinstance(agent_card, dict):
            return 422, {"error": "missing or non-object 'agent_card'"}

        capabilities = agent_card.get("capabilities")
        if (
            not isinstance(capabilities, list)
            or not capabilities
            or not all(
                isinstance(c, str) and c for c in capabilities
            )
        ):
            return 422, {
                "error": "'agent_card.capabilities' must be a non-empty "
                "list of non-empty strings"
            }

        public_key = payload.get("public_key")
        if public_key is not None and not isinstance(public_key, str):
            return 422, {"error": "'public_key' must be a string if provided"}

        try:
            agent = self.agent_index.register_agent(
                principal_id, agent_card, created_by, public_key=public_key
            )
        except ValueError:
            return 409, {"error": "agent principal already registered"}

        return 200, {"agent": agent}

    def list_agents(self, capability_id):
        # type: (str) -> Tuple[int, dict]
        """Agents declaring ``capability_id`` (empty list when none match)."""
        if not isinstance(capability_id, str) or not capability_id:
            return 400, {"error": "missing 'capability' parameter"}
        agents = self.agent_index.find_by_capability(capability_id)
        return 200, {"capability": capability_id, "agents": agents}

    # -- user endpoints (U1) ---------------------------------------------------

    def register_user(self, payload):
        # type: (dict) -> Tuple[int, dict]
        """Register a new user Principal. Returns (http_status, response_body)."""
        if not isinstance(payload, dict):
            return 422, {"error": "request body must be a JSON object"}

        principal_id = payload.get("principal_id")
        if not isinstance(principal_id, str) or not principal_id:
            return 422, {"error": "missing or non-string 'principal_id'"}

        # Check for duplicate
        if self.user_index.user_exists(principal_id):
            return 409, {"error": "principal already registered"}

        username = payload.get("username")
        if username is not None and not isinstance(username, str):
            return 422, {"error": "'username' must be a string if provided"}

        # Create user
        user = self.user_index.create_user(principal_id, username=username)
        reputation = self.user_index.get_aggregated_reputation(principal_id)

        return 200, {
            "status": "registered",
            "principal_id": principal_id,
            "reputation": reputation,
            "user": user,
        }

    def login_user(self, payload):
        # type: (dict) -> Tuple[int, dict]
        """Log in a user Principal. Returns (http_status, response_body)."""
        if not isinstance(payload, dict):
            return 422, {"error": "request body must be a JSON object"}

        principal_id = payload.get("principal_id")
        if not isinstance(principal_id, str) or not principal_id:
            return 422, {"error": "missing or non-string 'principal_id'"}

        # Check if user exists
        user = self.user_index.get_user(principal_id)
        if user is None:
            return 404, {"error": "principal not found"}

        # Update last_active
        self.user_index.update_last_active(principal_id)

        reputation = self.user_index.get_aggregated_reputation(principal_id)

        return 200, {
            "status": "ok",
            "principal_id": principal_id,
            "reputation": reputation,
            "user": user,
        }

    def get_user(self, principal_id):
        # type: (str) -> Tuple[int, dict]
        """Get user reputation records. Returns (http_status, response_body)."""
        if not isinstance(principal_id, str) or not principal_id:
            return 422, {"error": "missing or non-string 'principal_id'"}

        user = self.user_index.get_user(principal_id)
        if user is None:
            return 404, {"error": "principal not found"}

        reputation_records = self.user_index.get_reputation_records(
            principal_id
        )

        return 200, {
            "principal_id": principal_id,
            "reputation_records": reputation_records,
            "created_at": user.get("created_at"),
            "last_active": user.get("last_active"),
            "username": user.get("username"),
        }

    def update_user_reputation(self, principal_id, payload):
        # type: (str, dict) -> Tuple[int, dict]
        """Record a reputation event for a principal (user OR agent — agents
        are principals too, U5; both share the same reputation records).
        Returns (http_status, response_body)."""
        if not isinstance(principal_id, str) or not principal_id:
            return 422, {"error": "missing or non-string 'principal_id'"}

        if not isinstance(payload, dict):
            return 422, {"error": "request body must be a JSON object"}

        # Check the principal exists (as a user or an agent)
        if not self.user_index.user_exists(
            principal_id
        ) and not self.agent_index.agent_exists(principal_id):
            return 404, {"error": "principal not found"}

        # Validate required fields
        task_id = payload.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            return 422, {"error": "missing or non-string 'task_id'"}

        verified = payload.get("verified")
        if not isinstance(verified, bool):
            return 422, {"error": "'verified' must be a boolean"}

        capability_id = payload.get("capability_id")
        if not isinstance(capability_id, str) or not capability_id:
            return 422, {"error": "missing or non-string 'capability_id'"}

        # Record the reputation
        record = self.user_index.record_reputation(
            principal_id, capability_id, task_id, verified
        )

        return 200, {
            "task_id": task_id,
            "verified": verified,
            "capability_id": capability_id,
            "reputation_summary": {
                "capability_id": capability_id,
                "tasks_verified": record.get("tasks_verified", 0),
                "tasks_rejected": record.get("tasks_rejected", 0),
                "verification_rate": record.get("verification_rate"),
            },
        }

    # -- reputation sourcing -----------------------------------------------------

    def _reputation_summary(self, principal_id, capability_id):
        # type: (str, str) -> dict
        record = None
        if self.reputation_store is not None:
            records = self.reputation_store.get_reputation(
                principal_id, capability_id=capability_id
            )
            record = records[0] if records else None
        elif self.verification_url is not None:
            record = self._fetch_reputation_http(principal_id, capability_id)
        if record is None:
            return neutral_summary(capability_id)
        return {
            "capability_id": capability_id,
            "tasks_verified": record.get("tasks_verified", 0),
            "tasks_rejected": record.get("tasks_rejected", 0),
            "verification_rate": record.get("verification_rate"),
        }

    def _fetch_reputation_http(self, principal_id, capability_id):
        # type: (str, str) -> Optional[dict]
        """Lazy per-search fetch; any failure means unknown (neutral)."""
        import requests

        url = "%s/reputation/%s" % (
            self.verification_url,
            quote(principal_id, safe=""),
        )
        try:
            resp = requests.get(
                url,
                params={"capability_id": capability_id},
                timeout=self.http_timeout,
            )
            if resp.status_code != 200:
                return None
            records = resp.json().get("reputation_records")
        except (requests.RequestException, ValueError):
            return None
        if not isinstance(records, list) or not records:
            return None
        return records[0] if isinstance(records[0], dict) else None


# ---------------------------------------------------------------------------
# HTTP layer (thin wrapper over RegistryService)
# ---------------------------------------------------------------------------


class RegistryHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, service, rate_limiter=None):
        # type: (tuple, RegistryService, object) -> None
        self.service = service
        self.rate_limiter = rate_limiter
        ThreadingHTTPServer.__init__(self, address, _RequestHandler)


class _RequestHandler(BaseHTTPRequestHandler):
    server_version = "AgentTrustRegistry/0.1"
    protocol_version = "HTTP/1.1"

    @property
    def service(self):
        # type: () -> RegistryService
        return self.server.service

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        pass  # keep test output quiet; demo-scale service

    def _send_json(self, status, body):
        # type: (int, dict) -> None
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _bearer_token(self):
        # type: () -> Optional[str]
        # Auth-scheme is case-insensitive per RFC 9110 §11.1.
        parts = self.headers.get("Authorization", "").split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip()
        return None

    def _rate_ok(self):
        # type: () -> bool
        limiter = getattr(self.server, "rate_limiter", None)
        if limiter is None or limiter.allow(self.client_address[0]):
            return True
        # Close: this early reply hasn't read the request body, so reusing the
        # keep-alive connection would desync it.
        self.close_connection = True
        self._send_json(429, {"error": "rate limit exceeded"})
        return False

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

    def do_GET(self):
        if not self._rate_ok():
            return
        parts = urlsplit(self.path)
        segments = [unquote(s) for s in parts.path.split("/") if s]

        if segments == ["healthz"]:
            self._send_json(200, {"status": "ok"})
        elif segments == ["search"]:
            query = parse_qs(parts.query)
            capability = query.get("capability", [None])[0]
            if not capability:
                self._send_json(
                    400, {"error": "missing 'capability' query parameter"}
                )
                return
            raw_min = query.get("min_reputation", [None])[0]
            min_reputation = None
            if raw_min is not None:
                try:
                    min_reputation = float(raw_min)
                except ValueError:
                    self._send_json(
                        400, {"error": "min_reputation must be a number"}
                    )
                    return
            status, body = self.service.search(
                capability, min_reputation=min_reputation
            )
            self._send_json(status, body)
        elif segments == ["agents"]:
            # GET /agents?capability=<id> — agent principals by capability
            query = parse_qs(parts.query)
            capability = query.get("capability", [None])[0]
            if not capability:
                self._send_json(
                    400, {"error": "missing 'capability' query parameter"}
                )
                return
            status, body = self.service.list_agents(capability)
            self._send_json(status, body)
        elif len(segments) == 2 and segments[0] == "agents":
            status, body = self.service.get_agent(segments[1])
            self._send_json(status, body)
        elif len(segments) == 2 and segments[0] == "users":
            # GET /users/{principal_id}
            status, body = self.service.get_user(segments[1])
            self._send_json(status, body)
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if not self._rate_ok():
            return
        parts = urlsplit(self.path)
        segments = [unquote(s) for s in parts.path.split("/") if s]
        body, error = self._read_json_body()
        if error:
            self._send_json(400, {"error": error})
            return

        if segments == ["register"]:
            status, response = self.service.register(body)
            self._send_json(status, response)
        elif segments == ["admin", "api-keys"]:
            # Gated by an admin bearer token when one is configured (KTD-A5);
            # open (demo default) when none is set.
            if not self.service.admin_ok(self._bearer_token()):
                self.send_response(401)
                self.send_header("WWW-Authenticate", "Bearer")
                self.send_header("Content-Type", "application/json")
                data = json.dumps(
                    {"error": "admin authentication required"}
                ).encode("utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            self._send_json(200, {"api_key": self.service.create_api_key()})
        elif segments == ["agents", "register"]:
            # POST /agents/register — agent Principal registration (U5)
            status, response = self.service.register_agent(body)
            self._send_json(status, response)
        elif segments == ["auth", "register"]:
            # POST /auth/register — user registration
            status, response = self.service.register_user(body)
            self._send_json(status, response)
        elif segments == ["auth", "login"]:
            # POST /auth/login — user login
            status, response = self.service.login_user(body)
            self._send_json(status, response)
        elif len(segments) == 3 and segments[0] == "users" and segments[2] == "reputation":
            # POST /users/{principal_id}/reputation — record reputation
            status, response = self.service.update_user_reputation(
                segments[1], body
            )
            self._send_json(status, response)
        else:
            self._send_json(404, {"error": "not found"})


def make_server(
    port=0,
    host="127.0.0.1",
    index=None,
    service=None,
    reputation_store=None,
    verification_url=None,
    admin_token=None,
    rate_limiter=None,
):
    # type: (int, str, Optional[IndexStore], Optional[RegistryService], Optional[object], Optional[str], Optional[str], object) -> RegistryHTTPServer
    """Build a (threading) HTTP server; ``port=0`` picks a free port."""
    if service is None:
        service = RegistryService(
            index if index is not None else IndexStore(),
            reputation_store=reputation_store,
            verification_url=verification_url,
            admin_token=admin_token,
        )
    return RegistryHTTPServer((host, port), service, rate_limiter=rate_limiter)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="AgentTrust Reference Registry"
    )
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--verification-url",
        default=None,
        help="Base URL of a Verification Service; reputation summaries are "
        "fetched lazily per search (down service = neutral reputation).",
    )
    parser.add_argument(
        "--api-keys-file",
        default=None,
        help="Optional JSON file (array of strings) seeding valid API keys.",
    )
    parser.add_argument(
        "--index-path",
        default=None,
        help="Optional JSON file for persisting registrations.",
    )
    parser.add_argument(
        "--admin-token",
        default=None,
        help="If set, POST /admin/api-keys requires this bearer token. "
        "Omit to leave the admin surface open (demo default).",
    )
    parser.add_argument(
        "--rate-limit",
        type=int,
        default=0,
        help="Max requests per IP per 60s window (0 = off).",
    )
    parser.add_argument(
        "--user-index-path",
        default=None,
        help="Optional JSON file for persisting user principals and reputation records.",
    )
    args = parser.parse_args(argv)

    index = IndexStore(path=args.index_path, api_keys_path=args.api_keys_file)
    user_index = UserIndex(path=args.user_index_path)
    service = RegistryService(
        index,
        verification_url=args.verification_url,
        admin_token=args.admin_token,
        user_index=user_index,
    )
    rate_limiter = None
    if args.rate_limit > 0:
        from common.ratelimit import RateLimiter

        rate_limiter = RateLimiter(
            max_requests=args.rate_limit, window_seconds=60
        )
    server = make_server(
        port=args.port, host=args.host, service=service,
        rate_limiter=rate_limiter,
    )
    print(
        "AgentTrust registry listening on http://%s:%d"
        % server.server_address[:2]
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()
