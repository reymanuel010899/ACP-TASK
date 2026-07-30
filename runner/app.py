"""AgentTrust agent runner service (U1/U3).

Control-plane backend the console talks to for the agent lifecycle: manages
agent DEFINITIONS (``runner/store.py``) and supervises their PROCESSES
(``runner/supervisor.py``). The runner is the lifecycle source of truth
(KTD3); running agents self-register into the registry for discovery.

API (all JSON; binds to 127.0.0.1 only, dev-only):
- ``GET  /healthz``                       -> ``{"status": "ok"}``
- ``POST /agents``                        -> create a definition (stopped)
- ``GET  /agents``                        -> ``{"agents": [{...def, runtime}]}``
- ``GET  /agents/{id}``                   -> one agent (def + runtime) or 404
- ``DELETE /agents/{id}``                 -> stop + remove definition
- ``POST /agents/{id}/start|stop|restart``-> lifecycle action -> runtime
- ``GET  /agents/{id}/logs[?tail=N]``     -> ``{"logs": [...]}``

Run: ``python -m runner.app --port 8110 --registry-url http://127.0.0.1:8090
--verification-url http://127.0.0.1:8080 --data-dir ./.runner-data``
"""

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from runner.connect import (
    ConnectError, ensure_trust_extension, health_check, inspect, merge_skills,
    register_external,
)
from runner.store import DefinitionStore
from runner.supervisor import Supervisor
from runner.templates import get_template


def _owner_of(payload):
    # type: (dict) -> object
    """The requesting user's principal_id from a create/connect payload."""
    owner = (payload or {}).get("owner_principal_id")
    return owner.strip() if isinstance(owner, str) and owner.strip() else None


class RunnerService(object):
    def __init__(self, store, supervisor):
        # type: (DefinitionStore, Supervisor) -> None
        self.store = store
        self.supervisor = supervisor

    # -- definitions ----------------------------------------------------------

    def create_agent(self, payload):
        # type: (dict) -> tuple
        if not isinstance(payload, dict):
            return 422, {"error": "request body must be a JSON object"}
        name = payload.get("name")
        if not isinstance(name, str) or not name.strip():
            return 422, {"error": "missing or empty 'name'"}
        template = payload.get("template")
        if get_template(template) is None:
            return 422, {"error": "unknown template: %r" % template}
        capabilities = payload.get("capabilities")
        if (not isinstance(capabilities, list) or not capabilities
                or not all(isinstance(c, str) and c for c in capabilities)):
            return 422, {"error": "'capabilities' must be a non-empty list of strings"}
        list_price = payload.get("list_price")
        min_price = payload.get("min_price")
        for value, field in ((list_price, "list_price"), (min_price, "min_price")):
            if value is not None and (isinstance(value, bool)
                                      or not isinstance(value, (int, float))
                                      or value < 0):
                return 422, {"error": "%s must be a non-negative number" % field}
        if (isinstance(list_price, (int, float)) and isinstance(min_price, (int, float))
                and min_price > list_price):
            return 422, {"error": "min_price must not exceed list_price"}

        definition = self.store.create(
            name=name.strip(),
            template=template,
            capabilities=capabilities,
            description=payload.get("description", "") or "",
            version=payload.get("version", "0.1.0") or "0.1.0",
            list_price=list_price,
            min_price=min_price,
            owner=_owner_of(payload),
        )
        return 200, self._with_runtime(definition)

    # -- connect existing (BYO) agents ---------------------------------------

    def verify_connect(self, payload):
        # type: (dict) -> tuple
        """Dry-run: fetch + validate an external agent card, return detected
        fields (no registration, no stored definition)."""
        url = (payload or {}).get("endpoint_url")
        if not isinstance(url, str) or not url.strip():
            return 422, {"error": "missing 'endpoint_url'"}
        try:
            detected = inspect(url.strip())
        except ConnectError as exc:
            return 422, {"error": str(exc)}
        return 200, {
            "name": detected["name"], "url": detected["url"],
            "principal_id": detected["principal_id"],
            "trust_tier": detected["trust_tier"], "proof": detected["proof"],
            "capabilities": detected["capabilities"], "version": detected["version"],
        }

    def connect_agent(self, payload):
        # type: (dict) -> tuple
        """Connect an externally hosted agent by URL: validate its card,
        register it into the registry (discoverable), and track it."""
        url = (payload or {}).get("endpoint_url")
        if not isinstance(url, str) or not url.strip():
            return 422, {"error": "missing 'endpoint_url'"}
        try:
            detected = inspect(url.strip())
        except ConnectError as exc:
            return 422, {"error": str(exc)}

        # The operator may declare which catalog capabilities this agent offers
        # (external agents often don't publish skills in our vocabulary). What
        # they declare wins; otherwise fall back to what the card declared.
        declared = payload.get("capabilities")
        if declared is not None:
            if (not isinstance(declared, list)
                    or not all(isinstance(c, str) and c.strip() for c in declared)):
                return 422, {"error": "'capabilities' must be a list of non-empty strings"}
            capabilities = [c.strip() for c in declared]
        else:
            capabilities = detected["capabilities"]
        if not capabilities:
            return 422, {
                "error": "this agent declares no capabilities — select at least one "
                         "so requesters can discover it"
            }

        # Publish the declared capabilities IN the card, since the registry
        # indexes discovery off skills[].id. Then guarantee the card declares a
        # trust extension: a plain A2A agent gets a marketplace-attested
        # identity (tier "basic"), recorded as such in the published card.
        card = merge_skills(detected["card"], capabilities)
        card = ensure_trust_extension(
            card, detected["principal_id"],
            attested=(detected["trust_tier"] != "verified"),
        )
        try:
            api_key = self.supervisor.mint_api_key()
            register_external(self.supervisor.registry_url, card,
                              detected["principal_id"], api_key)
        except ConnectError as exc:
            return 502, {"error": str(exc)}
        except Exception as exc:
            return 502, {"error": "could not register the agent: %s" % exc}
        definition = self.store.create_connected(
            name=(payload.get("name") or detected["name"]),
            endpoint_url=detected["url"], capabilities=capabilities,
            principal_id=detected["principal_id"],
            description=detected["description"], version=detected["version"],
            trust_tier=detected["trust_tier"], card_url=detected["card_url"],
            owner=_owner_of(payload),
        )
        return 200, self._with_runtime(definition)

    def stats(self, window_days=14, change_window_days=30):
        # type: (int, int) -> tuple
        """Dashboard stats over the WHOLE fleet, computed from real data:

        - ``total`` and status counts (online/stopped/error) right now;
        - ``trend``: cumulative agent count per day for the last
          ``window_days`` — a real growth line derived from each agent's
          ``created_at`` (not a placeholder);
        - ``change_pct``: growth vs ``change_window_days`` ago.
        """
        agents = [self._with_runtime(d) for d in self.store.all()]
        total = len(agents)

        def created_date(agent):
            raw = agent.get("created_at") or ""
            try:
                return datetime.strptime(raw[:10], "%Y-%m-%d").date()
            except ValueError:
                return None

        dates = [d for d in (created_date(a) for a in agents) if d is not None]
        today = datetime.now(timezone.utc).date()

        trend = []
        for i in range(window_days - 1, -1, -1):
            day = today - timedelta(days=i)
            trend.append({
                "date": day.isoformat(),
                "count": sum(1 for d in dates if d <= day),
            })

        past = today - timedelta(days=change_window_days)
        base = sum(1 for d in dates if d <= past)
        if base > 0:
            change_pct = round((total - base) / base * 100.0, 1)
        else:
            change_pct = 100.0 if total > 0 else 0.0

        return 200, {
            "total": total,
            "online": sum(1 for a in agents if a["runtime"]["status"] == "online"),
            "stopped": sum(1 for a in agents if a["runtime"]["status"] == "stopped"),
            "error": sum(1 for a in agents if a["runtime"]["status"] == "error"),
            "trend": trend,
            "change_pct": change_pct,
        }

    def list_agents(self, page=None, page_size=None, q=None):
        # type: (object, object, object) -> tuple
        """List agents. Without params: the full legacy shape
        ``{"agents": [...]}`` (existing consumers — concierge, client
        console — keep working unchanged). With ``page``/``page_size``/``q``:
        SERVER-side search + pagination, returning one page plus ``total``,
        ``page``, ``page_size``, ``total_pages`` and fleet-wide ``stats`` so
        the console never has to load every agent to render one page."""
        agents = [self._with_runtime(d) for d in self.store.all()]
        if page is None and page_size is None and q is None:
            return 200, {"agents": agents}

        stats = {
            "total": len(agents),
            "online": sum(1 for a in agents if a["runtime"]["status"] == "online"),
            "stopped": sum(1 for a in agents if a["runtime"]["status"] == "stopped"),
            "error": sum(1 for a in agents if a["runtime"]["status"] == "error"),
        }
        needle = (q or "").strip().lower()
        if needle:
            agents = [
                a for a in agents
                if needle in (a.get("name") or "").lower()
                or any(needle in (c or "").lower()
                       for c in a.get("capabilities") or [])
            ]
        total = len(agents)
        try:
            size = max(1, min(int(page_size or 10), 100))
        except (TypeError, ValueError):
            size = 10
        total_pages = max(1, -(-total // size))  # ceil division
        try:
            current = max(1, min(int(page or 1), total_pages))
        except (TypeError, ValueError):
            current = 1
        start = (current - 1) * size
        return 200, {
            "agents": agents[start:start + size],
            "total": total,
            "page": current,
            "page_size": size,
            "total_pages": total_pages,
            "stats": stats,
        }

    def get_agent(self, agent_id):
        # type: (str) -> tuple
        definition = self.store.get(agent_id)
        if definition is None:
            return 404, {"error": "no such agent"}
        return 200, self._with_runtime(definition)

    @staticmethod
    def _ownership_block(definition, requester):
        # type: (dict, object) -> object
        """Ownership gate for MUTATING actions. An agent added by a user
        belongs to that user: only its owner may start/stop/restart/
        disconnect it. Enforced HERE (the backend), not in the UI — hiding a
        button is cosmetics, a 403 is authorization.

        A signed-in user (``requester`` present) may only mutate agents they
        OWN — including unclaimed legacy agents (no owner), which are NOT
        theirs until claimed. Calls with no requester (internal/scripts, and
        tests) are unaffected, preserving backward compatibility.
        """
        if requester is None:
            return None
        owner = definition.get("owner_principal_id")
        if owner != requester:
            if not owner:
                return 403, {
                    "error": "this agent has no owner yet — claim it first to "
                             "manage it",
                    "claimable": True,
                }
            return 403, {
                "error": "only the owner of this agent can perform this "
                         "action"
            }
        return None

    def claim_agent(self, agent_id, requester=None):
        # type: (str, object) -> tuple
        """Take ownership of an UNCLAIMED agent (legacy, no owner). Only a
        signed-in user may claim, and only when the agent has no owner yet."""
        definition = self.store.get(agent_id)
        if definition is None:
            return 404, {"error": "no such agent"}
        if not requester:
            return 401, {"error": "sign in to claim an agent"}
        owner = definition.get("owner_principal_id")
        if owner:
            if owner == requester:
                return 200, self._with_runtime(definition)
            return 403, {"error": "this agent already belongs to someone else"}
        updated = self.store.set_owner(agent_id, requester)
        return 200, self._with_runtime(updated)

    def delete_agent(self, agent_id, requester=None):
        # type: (str, object) -> tuple
        definition = self.store.get(agent_id)
        if definition is None:
            return 404, {"error": "no such agent"}
        blocked = self._ownership_block(definition, requester)
        if blocked:
            return blocked
        self.supervisor.stop(agent_id)
        self.store.delete(agent_id)
        return 200, {"deleted": agent_id}

    # -- lifecycle ------------------------------------------------------------

    def start_agent(self, agent_id, requester=None):
        # type: (str, object) -> tuple
        definition = self.store.get(agent_id)
        if definition is None:
            return 404, {"error": "no such agent"}
        blocked = self._ownership_block(definition, requester)
        if blocked:
            return blocked
        if definition.get("kind") == "connected":
            return 400, {"error": "connected agents run externally; they can't be started here"}
        try:
            runtime = self.supervisor.start(definition)
        except ValueError as exc:
            return 422, {"error": str(exc)}
        except Exception as exc:  # registry unreachable, spawn error, etc.
            return 502, {"error": "could not start agent: %s" % exc}
        return 200, {"id": agent_id, "runtime": runtime}

    def stop_agent(self, agent_id, requester=None):
        # type: (str, object) -> tuple
        definition = self.store.get(agent_id)
        if definition is None:
            return 404, {"error": "no such agent"}
        blocked = self._ownership_block(definition, requester)
        if blocked:
            return blocked
        return 200, {"id": agent_id, "runtime": self.supervisor.stop(agent_id)}

    def restart_agent(self, agent_id, requester=None):
        # type: (str, object) -> tuple
        definition = self.store.get(agent_id)
        if definition is None:
            return 404, {"error": "no such agent"}
        blocked = self._ownership_block(definition, requester)
        if blocked:
            return blocked
        try:
            runtime = self.supervisor.restart(definition)
        except Exception as exc:
            return 502, {"error": "could not restart agent: %s" % exc}
        return 200, {"id": agent_id, "runtime": runtime}

    def logs(self, agent_id, tail):
        # type: (str, int) -> tuple
        definition = self.store.get(agent_id)
        if definition is None:
            return 404, {"error": "no such agent"}
        return 200, {"id": agent_id, "logs": self.supervisor.logs(definition, tail=tail)}

    # -- helpers --------------------------------------------------------------

    def _with_runtime(self, definition):
        # type: (dict) -> dict
        item = dict(definition)
        # keys_dir/log_path are server-internal paths; don't leak them.
        item.pop("keys_dir", None)
        item.pop("log_path", None)
        if definition.get("kind") == "connected":
            # externally hosted -> status is a health-check to its own endpoint;
            # the runner runs no process for it.
            ok = health_check(definition.get("card_url") or definition["endpoint_url"])
            item["runtime"] = {
                "status": "online" if ok else "offline",
                "pid": None, "port": None,
                "url": definition["endpoint_url"],
                "principal_id": definition.get("principal_id"),
                "error": None,
            }
        else:
            item["runtime"] = self.supervisor.runtime(definition["id"])
        return item


# ---------------------------------------------------------------------------
# HTTP layer
# ---------------------------------------------------------------------------


def make_handler(service):
    # type: (RunnerService) -> type
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # quiet
            pass

        def _send(self, status, body):
            payload = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _read_json(self):
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            if not raw:
                return {}
            return json.loads(raw.decode("utf-8"))

        def do_GET(self):
            parts = urlparse(self.path)
            segs = [s for s in parts.path.split("/") if s]
            if segs == ["healthz"]:
                return self._send(200, {"status": "ok"})
            if segs == ["agents"]:
                query = parse_qs(parts.query)
                return self._send(*service.list_agents(
                    page=query.get("page", [None])[0],
                    page_size=query.get("page_size", [None])[0],
                    q=query.get("q", [None])[0],
                ))
            if segs == ["agents", "stats"]:
                return self._send(*service.stats())
            if len(segs) == 2 and segs[0] == "agents":
                return self._send(*service.get_agent(segs[1]))
            if len(segs) == 3 and segs[0] == "agents" and segs[2] == "logs":
                tail = int((parse_qs(parts.query).get("tail", ["200"])[0]) or 200)
                return self._send(*service.logs(segs[1], tail))
            return self._send(404, {"error": "not found"})

        def do_POST(self):
            segs = [s for s in urlparse(self.path).path.split("/") if s]
            try:
                if segs == ["agents"]:
                    return self._send(*service.create_agent(self._read_json()))
                if segs == ["agents", "connect"]:
                    return self._send(*service.connect_agent(self._read_json()))
                if segs == ["agents", "verify-connect"]:
                    return self._send(*service.verify_connect(self._read_json()))
                if len(segs) == 3 and segs[0] == "agents":
                    action = segs[2]
                    requester = self.headers.get("X-Owner-Principal") or None
                    if action == "start":
                        return self._send(*service.start_agent(segs[1], requester))
                    if action == "stop":
                        return self._send(*service.stop_agent(segs[1], requester))
                    if action == "restart":
                        return self._send(*service.restart_agent(segs[1], requester))
                    if action == "claim":
                        return self._send(*service.claim_agent(segs[1], requester))
            except ValueError as exc:
                return self._send(400, {"error": "invalid JSON: %s" % exc})
            return self._send(404, {"error": "not found"})

        def do_DELETE(self):
            segs = [s for s in urlparse(self.path).path.split("/") if s]
            if len(segs) == 2 and segs[0] == "agents":
                requester = self.headers.get("X-Owner-Principal") or None
                return self._send(*service.delete_agent(segs[1], requester))
            return self._send(404, {"error": "not found"})

    return Handler


def build_service(registry_url, verification_url, data_dir):
    # type: (str, str, str) -> RunnerService
    store = DefinitionStore(data_dir)
    supervisor = Supervisor(registry_url, verification_url)
    return RunnerService(store, supervisor)


def main():
    parser = argparse.ArgumentParser(description="AgentTrust agent runner")
    parser.add_argument("--port", type=int, default=8110)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--registry-url", default="http://127.0.0.1:8090")
    parser.add_argument("--verification-url", default="http://127.0.0.1:8080")
    parser.add_argument("--data-dir", default=os.path.join(os.getcwd(), ".runner-data"))
    args = parser.parse_args()

    service = build_service(args.registry_url, args.verification_url, args.data_dir)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(service))
    print("runner listening on http://%s:%d (data-dir %s)" % (
        args.host, args.port, args.data_dir))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        service.supervisor.shutdown_all()


if __name__ == "__main__":
    main()
