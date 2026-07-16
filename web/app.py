"""AgentTrust MVP web console (unit W1).

The consumer-facing front end for the "Agent 1" (requester) idea: instead of a
CLI, a person opens a web page, says what they need, and their requester agent
discovers providers, negotiates competitively, gets the work done, and shows
the result with its independent verification verdict — ready to approve.

This module is the **operator's product surface**, not an independently-built
agent, so (unlike ``agents/requester``) it may wire the demo stack together: on
startup it boots the verification service, the registry, and a couple of demo
providers in-process, then serves the UI and drives ``RequesterAgent`` behind a
single HTTP endpoint. One command, open the browser, it works.

The requester is configured with the trusted verification URL (so the F3
portfolio check has a verifier it trusts), exactly as a real deployment would.

Run: ``python -m web.app [--port 8000]`` then open http://127.0.0.1:8000
"""

import argparse
import json
import os
import threading

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import List, Optional, Tuple

import requests

from agents.provider import agent as provider_agent
from agents.provider.config import PricingConfig
from agents.requester.agent import RequesterAgent
from agents.requester.config import RequesterConfig
from registry.app import make_server as make_registry_server
from services.verification.app import make_server as make_verification_server
from web.nl import parse_request
from web.page import PAGE_HTML

CAPABILITY_ID = "terraform.generate"

# Two demo providers with different prices, so the competitive negotiation has
# something to compete over. (name shown in the UI, list/reservation prices.)
DEMO_PROVIDERS = [
    {"name": "FastInfra", "list_price": 9.0, "min_price": 7.0},
    {"name": "BudgetInfra", "list_price": 4.0, "min_price": 2.0},
]


def _start(server):
    # type: (ThreadingHTTPServer) -> None
    threading.Thread(target=server.serve_forever, daemon=True).start()


def _base_url(server):
    # type: (ThreadingHTTPServer) -> str
    host, port = server.server_address[:2]
    return "http://%s:%d" % (host, port)


class DemoStack(object):
    """Boots verification + registry + demo providers in-process.

    Keeps a display name per provider principal so the UI can show *who* won,
    not just an opaque id.
    """

    def __init__(self, keys_root, provider_specs=DEMO_PROVIDERS, http_timeout=3.0):
        # type: (str, List[dict], float) -> None
        self.http_timeout = http_timeout
        self.verification = make_verification_server(port=0)
        _start(self.verification)
        self.verification_url = _base_url(self.verification)

        self.registry = make_registry_server(
            port=0, verification_url=self.verification_url
        )
        _start(self.registry)
        self.registry_url = _base_url(self.registry)

        self.api_key = requests.post(
            self.registry_url + "/admin/api-keys", timeout=5
        ).json()["api_key"]

        self.providers = []
        self.names = {}  # principal_id -> display name
        for index, spec in enumerate(provider_specs):
            server = provider_agent.make_server(
                port=0,
                verification_url=self.verification_url,
                registry_url=self.registry_url,
                api_key=self.api_key,
                keys_dir=os.path.join(keys_root, "provider-%d" % index),
                pricing=PricingConfig(
                    list_price=spec["list_price"], min_price=spec["min_price"]
                ),
            )
            server.agent.register_with_registry()
            _start(server)
            self.providers.append(server)
            self.names[server.agent.principal_id] = spec["name"]

        self._servers = [self.verification, self.registry] + self.providers

    def name_for(self, principal_id):
        # type: (Optional[str]) -> Optional[str]
        return self.names.get(principal_id, principal_id)

    def register_external(self, url):
        # type: (str) -> Tuple[int, dict]
        return _register_external(
            self.registry_url, self.http_timeout, url, self.names
        )

    def shutdown(self):
        # type: () -> None
        for server in reversed(self._servers):
            server.shutdown()
            server.server_close()


class WebServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, stack, provider_tokens=None):
        # type: (tuple, object, Optional[dict]) -> None
        self.stack = stack  # DemoStack (embedded) or ConnectedBackend
        self.provider_tokens = dict(provider_tokens or {})
        ThreadingHTTPServer.__init__(self, address, _Handler)


def _inspect_card(card):
    # type: (object) -> Tuple[Optional[str], list, Optional[str]]
    """Validate a fetched Agent Card for self-registration.

    Returns ``(principal_id, capability_ids, error)``. On any problem the
    principal_id is None and error carries a user-facing reason.
    """
    trust_uri = provider_agent.TRUST_EXTENSION_URI
    if not isinstance(card, dict):
        return None, [], "El Agent Card no es un objeto JSON válido."
    extensions = (card.get("capabilities") or {}).get("extensions") or []
    trust = next(
        (
            e
            for e in extensions
            if isinstance(e, dict) and e.get("uri") == trust_uri
        ),
        None,
    )
    if trust is None:
        return None, [], (
            "Tu Agent Card no declara la extensión de confianza de AgentTrust "
            "en capabilities.extensions[]."
        )
    principal_id = (trust.get("params") or {}).get("principal_id")
    if not principal_id:
        return None, [], (
            "Tu extensión de confianza no declara un principal_id en params."
        )
    capabilities = [
        s.get("id")
        for s in (card.get("skills") or [])
        if isinstance(s, dict) and s.get("id")
    ]
    if not capabilities:
        return None, [], "Tu Agent Card no declara ninguna skill/capacidad."
    return principal_id, capabilities, None


def _register_external(registry_url, http_timeout, url, names, admin_token=None):
    # type: (str, float, str, dict, Optional[str]) -> Tuple[int, dict]
    """Self-service registration by Agent Card URL — no CLI. Fetches the
    provider's published Agent Card, validates it, mints an invite key, and
    registers it with ``registry_url``. Shared by the embedded and connected
    backends. Returns ``(http_status, body)``."""
    if not isinstance(url, str) or not url.strip():
        return 400, {"error": "Pegá la URL de tu agente."}
    card_url = url.rstrip("/") + "/.well-known/agent-card.json"
    try:
        resp = requests.get(card_url, timeout=http_timeout)
        resp.raise_for_status()
        card = resp.json()
    except (requests.RequestException, ValueError):
        return 400, {
            "error": "No pude alcanzar tu agente en esa URL. ¿Está corriendo "
            "y sirve /.well-known/agent-card.json?"
        }

    principal_id, capabilities, reason = _inspect_card(card)
    if reason:
        return 400, {"error": reason}

    admin_headers = (
        {"Authorization": "Bearer %s" % admin_token} if admin_token else {}
    )
    try:
        api_key = requests.post(
            registry_url + "/admin/api-keys",
            headers=admin_headers,
            timeout=http_timeout,
        ).json()["api_key"]
        registered = requests.post(
            registry_url + "/register",
            json={
                "agent_card": card,
                "principal_id": principal_id,
                "api_key": api_key,
            },
            timeout=http_timeout,
        )
    except (requests.RequestException, ValueError, KeyError) as exc:
        return 502, {"error": "El registro no respondió bien: %s" % exc}
    if registered.status_code != 200:
        return 400, {
            "error": "El registro rechazó el agente: %s"
            % registered.json().get("error", registered.status_code)
        }

    names[principal_id] = card.get("name") or principal_id
    return 200, {
        "registered": True,
        "name": card.get("name"),
        "principal_id": principal_id,
        "capabilities": capabilities,
    }


class ConnectedBackend(object):
    """A backend that points at an EXTERNAL registry + verification service
    (real providers live there), instead of booting an embedded demo stack.

    Same surface the request handler uses: ``registry_url``,
    ``verification_url``, ``name_for``, ``register_external``, ``shutdown``.
    """

    def __init__(self, registry_url, verification_url, admin_token=None,
                 http_timeout=3.0):
        # type: (str, str, Optional[str], float) -> None
        self.registry_url = registry_url.rstrip("/")
        self.verification_url = verification_url.rstrip("/")
        self.admin_token = admin_token
        self.http_timeout = http_timeout
        self.names = {}

    def name_for(self, principal_id):
        # type: (Optional[str]) -> Optional[str]
        return self.names.get(principal_id, principal_id)

    def register_external(self, url):
        # type: (str) -> Tuple[int, dict]
        return _register_external(
            self.registry_url, self.http_timeout, url, self.names,
            admin_token=self.admin_token,
        )

    def shutdown(self):
        # type: () -> None
        pass  # nothing to tear down; the external stack is not ours


def _validate_task(payload):
    # type: (dict) -> Optional[str]
    if not isinstance(payload, dict):
        return "body must be a JSON object"
    containers = payload.get("containers")
    if isinstance(containers, bool) or not isinstance(containers, int):
        return "containers must be an integer"
    if containers < 1:
        return "containers must be >= 1"
    if payload.get("load_balancer") != "alb":
        return "load_balancer must be 'alb'"
    return None


class _Handler(BaseHTTPRequestHandler):
    server_version = "AgentTrustWeb/0.1"
    protocol_version = "HTTP/1.1"

    @property
    def stack(self):
        # type: () -> DemoStack
        return self.server.stack

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        pass

    def _send(self, status, body, content_type="application/json"):
        # type: (int, object, str) -> None
        if content_type == "application/json":
            data = json.dumps(body).encode("utf-8")
        else:
            data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, PAGE_HTML, content_type="text/html; charset=utf-8")
        elif self.path == "/healthz":
            self._send(200, {"status": "ok"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/api/register-provider":
            self._handle_register_provider()
            return
        if self.path != "/api/task":
            self._send(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send(400, {"error": "invalid Content-Length"})
            return
        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, UnicodeDecodeError):
            self._send(400, {"error": "invalid JSON"})
            return

        # Two ways in: free text ("necesito infra...") parsed by the NL
        # translator, or a structured {containers, load_balancer} body.
        interpretation = None
        if isinstance(payload, dict) and "text" in payload:
            task_input, message = parse_request(payload.get("text") or "")
            if task_input is None:
                self._send(400, {"error": message})
                return
            interpretation = message
        else:
            reason = _validate_task(payload)
            if reason:
                self._send(400, {"error": reason})
                return
            task_input = {
                "containers": payload["containers"],
                "load_balancer": payload["load_balancer"],
            }

        config = RequesterConfig(
            registry_url=self.stack.registry_url,
            capability=CAPABILITY_ID,
            task_input=task_input,
            # The requester trusts THIS verifier for portfolio checks (F3).
            verification_url=self.stack.verification_url,
            # Tokens to present to providers that require auth (U3).
            provider_tokens=self.server.provider_tokens,
        )
        outcome = RequesterAgent(config).run_competitive()
        # Enrich for the UI: friendly provider name + what the agent understood.
        outcome["provider_name"] = self.stack.name_for(
            outcome.get("provider_principal_id")
        )
        outcome["interpretation"] = interpretation
        self._send(200, outcome)

    def _handle_register_provider(self):
        # type: () -> None
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send(400, {"error": "invalid Content-Length"})
            return
        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, UnicodeDecodeError):
            self._send(400, {"error": "invalid JSON"})
            return
        status, body = self.stack.register_external(
            payload.get("url") if isinstance(payload, dict) else None
        )
        self._send(status, body)


def make_server(
    port=8000,
    host="127.0.0.1",
    keys_root=None,
    registry_url=None,
    verification_url=None,
    admin_token=None,
    provider_tokens=None,
):
    # type: (int, str, Optional[str], Optional[str], Optional[str], Optional[str], Optional[dict]) -> WebServer
    """Connected mode when both registry_url and verification_url are given
    (uses an external stack with real providers); embedded demo stack
    otherwise (default)."""
    if registry_url and verification_url:
        stack = ConnectedBackend(
            registry_url, verification_url, admin_token=admin_token
        )
    else:
        if keys_root is None:
            keys_root = os.path.join(os.path.dirname(__file__), "keys")
        stack = DemoStack(keys_root=keys_root)
    return WebServer((host, port), stack, provider_tokens=provider_tokens)


def main(argv=None):
    parser = argparse.ArgumentParser(description="AgentTrust MVP web console")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--registry-url",
        default=None,
        help="Connect to an external registry (with --verification-url) "
        "instead of booting the embedded demo stack.",
    )
    parser.add_argument("--verification-url", default=None)
    parser.add_argument(
        "--admin-token",
        default=None,
        help="Admin token to mint invite keys when the external registry is "
        "secured.",
    )
    parser.add_argument(
        "--provider-token",
        action="append",
        default=None,
        dest="provider_tokens",
        metavar="PRINCIPAL_ID=TOKEN",
        help="Bearer token to present to a provider that requires auth "
        "(repeatable).",
    )
    args = parser.parse_args(argv)

    provider_tokens = {}
    for entry in args.provider_tokens or []:
        principal, _, token = entry.partition("=")
        if principal and token:
            provider_tokens[principal] = token

    connected = bool(args.registry_url and args.verification_url)
    server = make_server(
        port=args.port,
        host=args.host,
        registry_url=args.registry_url,
        verification_url=args.verification_url,
        admin_token=args.admin_token,
        provider_tokens=provider_tokens,
    )
    host, port = server.server_address[:2]
    print("AgentTrust MVP console: open http://%s:%d" % (host, port))
    if connected:
        print("(connected to external stack: %s)" % args.registry_url)
    else:
        print("(embedded demo stack: verification + registry + 2 providers)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.stack.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
