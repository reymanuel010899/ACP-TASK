"""Agent Marketplace service (Phase B, unit U8).

A standalone marketplace where agents advertise capabilities/pricing (via
their Registry agent cards), users search by capability/reputation, hire
agents through scoped hiring grants, rate them, and revoke hires.

Division of ownership:

* The **Registry** is the source of truth for agents and reputation — this
  service PULLS agent listings live (never caches or re-registers them).
* The **Vault** (U7) owns credential custody — when a hire carries
  ``credential_scopes`` and a Vault is wired in, this service orchestrates
  real Vault grants (and revokes them when the hire is revoked).
* This service owns **hiring grants** and **ratings** locally
  (``agent_marketplace.hiring.HiringStore``).

API endpoints:
- GET    /marketplace/agents?capability=<id>[&min_reputation=<x>]
         - live Registry pull, enriched with local avg_rating/rating_count,
           filtered by min_reputation (verification_rate >= x; no history
           counts as 0), sorted by (avg_rating desc, tasks_verified desc).
           502 when the Registry is unreachable.
- GET    /marketplace/agents/{principal_id}
         - Registry agent + reputation merged with local ratings/hirings.
- POST   /marketplace/hiring-grants          - hire an agent (scoped grant)
- GET    /marketplace/hiring-grants?agent_principal_id=<id>|user_principal_id=<id>
- DELETE /marketplace/hiring-grants/{grant_id}  - revoke (hiring user only)
- POST   /marketplace/ratings                - rate a hired agent (1-5)
- GET    /healthz

Run: python -m agent_marketplace.app [--port 8004] [--registry-url URL]
     [--vault-url URL]
"""

import argparse
import json

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional, Tuple
from urllib.parse import parse_qs, quote, unquote, urlsplit

import requests

from agent_marketplace.hiring import HiringStore, parse_expires_at

DEFAULT_HTTP_TIMEOUT = 3.0


class MarketplaceService(object):
    """Core agent-marketplace logic; callable directly from tests."""

    def __init__(self, registry_url=None, vault_url=None,
                 http_timeout=DEFAULT_HTTP_TIMEOUT, hiring_store=None):
        # type: (Optional[str], Optional[str], float, Optional[HiringStore]) -> None
        self.registry_url = (
            registry_url.rstrip("/") if registry_url else None
        )
        self.vault_url = vault_url.rstrip("/") if vault_url else None
        self.http_timeout = http_timeout
        self.hiring = (
            hiring_store if hiring_store is not None else HiringStore()
        )
        self._vault_client = None
        if self.vault_url:
            from libs.vault_client import VaultClient

            self._vault_client = VaultClient(
                self.vault_url, timeout=http_timeout
            )

    # -- Registry pulls (live; never cached) --------------------------------

    def _registry_get(self, path):
        # type: (str) -> Tuple[Optional[int], Optional[dict]]
        """GET from the Registry; (None, None) means unreachable/garbage."""
        if self.registry_url is None:
            return None, None
        try:
            resp = requests.get(
                self.registry_url + path, timeout=self.http_timeout
            )
            return resp.status_code, resp.json()
        except (requests.RequestException, ValueError):
            return None, None

    def _fetch_agent(self, principal_id):
        # type: (str) -> Tuple[Optional[int], Optional[dict]]
        return self._registry_get(
            "/agents/%s" % quote(principal_id, safe="")
        )

    # -- discovery ----------------------------------------------------------

    def search_agents(self, capability, min_reputation=None):
        # type: (str, Optional[float]) -> Tuple[int, dict]
        if not isinstance(capability, str) or not capability:
            return 400, {"error": "missing 'capability' query parameter"}

        status, body = self._registry_get(
            "/agents?capability=%s" % quote(capability, safe="")
        )
        if status is None:
            return 502, {"error": "registry unreachable"}
        if status != 200:
            return 502, {
                "error": "registry answered %d for agent listing" % status
            }

        results = []
        for agent in body.get("agents", []):
            principal_id = agent.get("principal_id")
            reputation = self._agent_reputation(principal_id)
            if min_reputation is not None:
                rate = reputation.get("verification_rate")
                # No history counts as 0 for filtering purposes.
                if (rate if rate is not None else 0.0) < min_reputation:
                    continue
            avg_rating, rating_count = self.hiring.rating_summary(
                principal_id
            )
            results.append(
                {
                    "principal_id": principal_id,
                    "agent_card": agent.get("agent_card"),
                    "created_by": agent.get("created_by"),
                    "reputation": reputation,
                    "avg_rating": avg_rating,
                    "rating_count": rating_count,
                }
            )

        results.sort(
            key=lambda a: (
                a["avg_rating"] if a["avg_rating"] is not None else -1.0,
                a["reputation"].get("tasks_verified") or 0,
            ),
            reverse=True,
        )
        return 200, {"capability": capability, "agents": results}

    def _agent_reputation(self, principal_id):
        # type: (Optional[str]) -> dict
        """Reputation via the Registry; unknown/unreachable is neutral."""
        neutral = {
            "tasks_verified": 0,
            "tasks_rejected": 0,
            "verification_rate": None,
        }
        if not principal_id:
            return neutral
        status, body = self._fetch_agent(principal_id)
        if status != 200 or not isinstance(body, dict):
            return neutral
        reputation = body.get("reputation")
        return reputation if isinstance(reputation, dict) else neutral

    def get_agent(self, principal_id):
        # type: (str) -> Tuple[int, dict]
        status, body = self._fetch_agent(principal_id)
        if status is None:
            return 502, {"error": "registry unreachable"}
        if status == 404:
            return 404, {"error": "no agent with that principal_id"}
        if status != 200:
            return 502, {
                "error": "registry answered %d for agent lookup" % status
            }
        if not isinstance(body, dict) or "agent" not in body:
            # e.g. a legacy U4 card registration — not a hireable Principal.
            return 404, {"error": "no agent with that principal_id"}

        avg_rating, rating_count = self.hiring.rating_summary(principal_id)
        return 200, {
            "agent": body["agent"],
            "reputation": body.get("reputation"),
            "avg_rating": avg_rating,
            "rating_count": rating_count,
            "reviews": self.hiring.reviews(principal_id),
            "active_hirings": self.hiring.active_hirings_count(
                principal_id
            ),
        }

    # -- hiring -------------------------------------------------------------

    def create_hiring_grant(self, payload):
        # type: (dict) -> Tuple[int, dict]
        if not isinstance(payload, dict):
            return 422, {"error": "request body must be a JSON object"}

        agent_principal_id = payload.get("agent_principal_id")
        if not isinstance(agent_principal_id, str) or not agent_principal_id:
            return 422, {
                "error": "missing or non-string 'agent_principal_id'"
            }
        user_principal_id = payload.get("user_principal_id")
        if not isinstance(user_principal_id, str) or not user_principal_id:
            return 422, {
                "error": "missing or non-string 'user_principal_id'"
            }

        scoped_capabilities = payload.get("scoped_capabilities")
        if (
            not isinstance(scoped_capabilities, list)
            or not scoped_capabilities
            or not all(
                isinstance(c, str) and c for c in scoped_capabilities
            )
        ):
            return 422, {
                "error": "'scoped_capabilities' must be a non-empty list "
                "of non-empty strings"
            }

        credential_scopes = payload.get("credential_scopes") or []
        if not isinstance(credential_scopes, list):
            return 422, {"error": "'credential_scopes' must be a list"}
        for scope in credential_scopes:
            if (
                not isinstance(scope, dict)
                or not isinstance(scope.get("credential_id"), str)
                or not scope.get("credential_id")
                or not isinstance(scope.get("scope"), str)
                or not scope.get("scope")
            ):
                return 422, {
                    "error": "each credential_scope must be an object with "
                    "non-empty 'credential_id' and 'scope' strings"
                }

        expires_at = payload.get("expires_at")
        if expires_at is not None:
            try:
                parse_expires_at(expires_at)
            except ValueError:
                return 422, {
                    "error": "'expires_at' must be an ISO-8601 timestamp"
                }

        # The Registry is the source of truth: no such agent, no hire.
        status, body = self._fetch_agent(agent_principal_id)
        if status is None:
            return 502, {"error": "registry unreachable"}
        if status == 404:
            return 404, {"error": "no agent with that principal_id"}
        if status != 200:
            return 502, {
                "error": "registry answered %d for agent lookup" % status
            }
        if not isinstance(body, dict) or "agent" not in body:
            return 404, {"error": "no agent with that principal_id"}

        # Orchestrate Vault credential grants BEFORE recording the hire, so
        # a Vault failure never leaves a hire that claims access it lacks.
        if credential_scopes and self._vault_client is not None:
            try:
                for scope in credential_scopes:
                    self._vault_client.grant_access(
                        scope["credential_id"],
                        agent_principal_id,
                        scope["scope"],
                        granted_by=user_principal_id,
                    )
            except requests.RequestException as exc:
                return 502, {
                    "error": "vault grant failed: %s" % exc,
                }

        grant = self.hiring.create_grant(
            agent_principal_id,
            user_principal_id,
            scoped_capabilities,
            credential_scopes=credential_scopes,
            expires_at=expires_at,
        )
        return 200, {"grant": grant}

    def list_hiring_grants(self, agent_principal_id=None,
                           user_principal_id=None):
        # type: (Optional[str], Optional[str]) -> Tuple[int, dict]
        if not agent_principal_id and not user_principal_id:
            return 400, {
                "error": "provide 'agent_principal_id' or "
                "'user_principal_id' as a query parameter"
            }
        grants = self.hiring.list_grants(
            agent_principal_id=agent_principal_id or None,
            user_principal_id=user_principal_id or None,
        )
        return 200, {"grants": grants}

    def revoke_hiring_grant(self, grant_id, user_principal_id):
        # type: (str, Optional[str]) -> Tuple[int, dict]
        if not isinstance(user_principal_id, str) or not user_principal_id:
            return 422, {
                "error": "missing or non-string 'user_principal_id'"
            }
        grant = self.hiring.get_grant(grant_id)
        if grant is None:
            return 404, {"error": "no hiring grant with that grant_id"}
        if grant["user_principal_id"] != user_principal_id:
            return 403, {
                "error": "only the hiring user can revoke this grant"
            }

        revoked = self.hiring.revoke_grant(grant_id)

        # Best-effort Vault revocation: the hire is revoked either way, and
        # revoke is idempotent from the marketplace's point of view.
        if self._vault_client is not None:
            for scope in revoked.get("credential_scopes", []):
                try:
                    self._vault_client.revoke_access(
                        scope["credential_id"],
                        revoked["agent_principal_id"],
                    )
                except requests.RequestException:
                    pass

        return 200, {"grant": revoked}

    # -- ratings ------------------------------------------------------------

    def rate_agent(self, payload):
        # type: (dict) -> Tuple[int, dict]
        if not isinstance(payload, dict):
            return 422, {"error": "request body must be a JSON object"}

        agent_principal_id = payload.get("agent_principal_id")
        if not isinstance(agent_principal_id, str) or not agent_principal_id:
            return 422, {
                "error": "missing or non-string 'agent_principal_id'"
            }
        user_principal_id = payload.get("user_principal_id")
        if not isinstance(user_principal_id, str) or not user_principal_id:
            return 422, {
                "error": "missing or non-string 'user_principal_id'"
            }

        rating = payload.get("rating")
        if (
            isinstance(rating, bool)
            or not isinstance(rating, int)
            or rating < 1
            or rating > 5
        ):
            return 422, {"error": "'rating' must be an integer from 1 to 5"}

        review_text = payload.get("review_text")
        if review_text is not None and not isinstance(review_text, str):
            return 422, {
                "error": "'review_text' must be a string if provided"
            }

        # Only users who actually hired the agent (non-revoked grant —
        # expired still counts, the work happened) may rate it.
        if not self.hiring.has_hiring(user_principal_id, agent_principal_id):
            return 403, {
                "error": "only users with a hiring grant for this agent "
                "can rate it"
            }

        self.hiring.set_rating(
            agent_principal_id, user_principal_id, rating,
            review_text=review_text,
        )
        avg_rating, rating_count = self.hiring.rating_summary(
            agent_principal_id
        )
        return 200, {
            "agent_principal_id": agent_principal_id,
            "avg_rating": avg_rating,
            "rating_count": rating_count,
        }


# ---------------------------------------------------------------------------
# HTTP layer (thin wrapper over MarketplaceService)
# ---------------------------------------------------------------------------


class AgentMarketplaceHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, service):
        # type: (tuple, MarketplaceService) -> None
        self.service = service
        ThreadingHTTPServer.__init__(self, address, _RequestHandler)


class _RequestHandler(BaseHTTPRequestHandler):
    server_version = "AgentTrustAgentMarketplace/0.1"
    protocol_version = "HTTP/1.1"

    @property
    def service(self):
        # type: () -> MarketplaceService
        return self.server.service

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        pass  # keep test output quiet

    def _send_json(self, status, body):
        # type: (int, dict) -> None
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header(
            "Access-Control-Allow-Methods",
            "GET, POST, PUT, DELETE, OPTIONS",
        )
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

    def do_OPTIONS(self):
        # type: () -> None
        """Handle CORS preflight requests."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header(
            "Access-Control-Allow-Methods",
            "GET, POST, PUT, DELETE, OPTIONS",
        )
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parts = urlsplit(self.path)
        segments = [unquote(s) for s in parts.path.split("/") if s]
        query = parse_qs(parts.query)

        if segments == ["healthz"]:
            self._send_json(200, {"status": "ok"})
        elif segments == ["marketplace", "agents"]:
            capability = query.get("capability", [None])[0]
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
            status, body = self.service.search_agents(
                capability, min_reputation=min_reputation
            )
            self._send_json(status, body)
        elif len(segments) == 3 and segments[:2] == ["marketplace", "agents"]:
            status, body = self.service.get_agent(segments[2])
            self._send_json(status, body)
        elif segments == ["marketplace", "hiring-grants"]:
            status, body = self.service.list_hiring_grants(
                agent_principal_id=query.get("agent_principal_id", [None])[0],
                user_principal_id=query.get("user_principal_id", [None])[0],
            )
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

        if segments == ["marketplace", "hiring-grants"]:
            status, response = self.service.create_hiring_grant(body)
            self._send_json(status, response)
        elif segments == ["marketplace", "ratings"]:
            status, response = self.service.rate_agent(body)
            self._send_json(status, response)
        else:
            self._send_json(404, {"error": "not found"})

    def do_DELETE(self):
        parts = urlsplit(self.path)
        segments = [unquote(s) for s in parts.path.split("/") if s]
        query = parse_qs(parts.query)
        body, error = self._read_json_body()
        if error:
            self._send_json(400, {"error": error})
            return

        if len(segments) == 3 and segments[:2] == [
            "marketplace", "hiring-grants",
        ]:
            # user_principal_id may come in the body or the query string.
            user_principal_id = body.get("user_principal_id") or query.get(
                "user_principal_id", [None]
            )[0]
            status, response = self.service.revoke_hiring_grant(
                segments[2], user_principal_id
            )
            self._send_json(status, response)
        else:
            self._send_json(404, {"error": "not found"})


def make_server(port=8004, host="127.0.0.1", registry_url=None,
                vault_url=None):
    # type: (int, str, Optional[str], Optional[str]) -> AgentMarketplaceHTTPServer
    """Build the agent-marketplace server; ``port=0`` picks a free port."""
    service = MarketplaceService(
        registry_url=registry_url, vault_url=vault_url
    )
    return AgentMarketplaceHTTPServer((host, port), service)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="AgentTrust Agent Marketplace"
    )
    parser.add_argument("--port", type=int, default=8004)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--registry-url",
        default=None,
        help="Base URL of the Registry (source of truth for agents + "
        "reputation). Discovery answers 502 without it.",
    )
    parser.add_argument(
        "--vault-url",
        default=None,
        help="Base URL of the Vault (U7). When set, credential_scopes in "
        "hires become real Vault grants (revoked with the hire).",
    )
    args = parser.parse_args(argv)

    server = make_server(
        port=args.port,
        host=args.host,
        registry_url=args.registry_url,
        vault_url=args.vault_url,
    )
    host, port = server.server_address[:2]
    print(
        "AgentTrust Agent Marketplace listening on http://%s:%d"
        % (host, port)
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()
