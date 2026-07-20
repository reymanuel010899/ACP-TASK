"""Client for the AgentTrust Agent Marketplace (unit U8).

Thin HTTP wrapper over the agent-marketplace API: capability/reputation
search, agent detail, hiring via scoped grants, listing hires (from the
agent's or the user's side), rating hired agents, and revoking hires.
"""

import json
from typing import List, Optional

import requests


class AgentMarketplaceClient:
    """HTTP client for the Agent Marketplace service.

    When constructed with a ``session`` (a :class:`libs.session.SessionContext`)
    the mutating routes (hire/revoke/rate) are signed automatically with the
    ``X-AT-*`` headers the marketplace verifies under ``require_signatures``.
    Without a session the client behaves EXACTLY as before (no headers), so it
    keeps working against unsigned marketplaces during a gradual migration.
    """

    def __init__(self, base_url, timeout=5.0, session=None):
        # type: (str, float, Optional[object]) -> None
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session

    # -- raw HTTP helper ---------------------------------------------------

    def _request(self, method, path, json_body=None, params=None):
        # type: (str, str, Optional[dict], Optional[dict]) -> dict
        if self.session is None:
            resp = requests.request(
                method,
                self.base_url + path,
                json=json_body,
                params=params,
                timeout=self.timeout,
            )
        else:
            # Sign the EXACT bytes we place on the wire so the server
            # reconstructs identical canonical bytes; gated routes carry no
            # query string, so the signature covers the path alone.
            body_bytes = (
                json.dumps(json_body).encode("utf-8")
                if json_body is not None else b""
            )
            headers = self.session.auth_headers(method, path, body_bytes)
            headers["Content-Type"] = "application/json"
            resp = requests.request(
                method,
                self.base_url + path,
                data=body_bytes,
                params=params,
                headers=headers,
                timeout=self.timeout,
            )
        resp.raise_for_status()
        return resp.json()

    # -- discovery ---------------------------------------------------------

    def search_agents(self, capability, min_reputation=None):
        # type: (str, Optional[float]) -> List[dict]
        """GET /marketplace/agents — agents by capability, best first."""
        params = {"capability": capability}
        if min_reputation is not None:
            params["min_reputation"] = min_reputation
        body = self._request(
            "GET", "/marketplace/agents", params=params
        )
        return body["agents"]

    def get_agent(self, principal_id):
        # type: (str) -> dict
        """GET /marketplace/agents/{id} — Registry data + local ratings."""
        return self._request(
            "GET", "/marketplace/agents/%s" % principal_id
        )

    # -- hiring ------------------------------------------------------------

    def hire_agent(self, agent_principal_id, user_principal_id,
                   scoped_capabilities, credential_scopes=None,
                   expires_at=None):
        # type: (str, str, List[str], Optional[List[dict]], Optional[str]) -> dict
        """POST /marketplace/hiring-grants — hire an agent; returns the grant."""
        body = {
            "agent_principal_id": agent_principal_id,
            "user_principal_id": user_principal_id,
            "scoped_capabilities": scoped_capabilities,
        }
        if credential_scopes is not None:
            body["credential_scopes"] = credential_scopes
        if expires_at is not None:
            body["expires_at"] = expires_at
        return self._request(
            "POST", "/marketplace/hiring-grants", json_body=body
        )["grant"]

    def list_hirings(self, agent_principal_id=None, user_principal_id=None):
        # type: (Optional[str], Optional[str]) -> List[dict]
        """GET /marketplace/hiring-grants — the agent's or the user's view."""
        params = {}
        if agent_principal_id is not None:
            params["agent_principal_id"] = agent_principal_id
        if user_principal_id is not None:
            params["user_principal_id"] = user_principal_id
        body = self._request(
            "GET", "/marketplace/hiring-grants", params=params
        )
        return body["grants"]

    def revoke_hiring(self, grant_id, user_principal_id):
        # type: (str, str) -> dict
        """DELETE /marketplace/hiring-grants/{id} — hiring user only."""
        return self._request(
            "DELETE",
            "/marketplace/hiring-grants/%s" % grant_id,
            json_body={"user_principal_id": user_principal_id},
        )

    # -- ratings -----------------------------------------------------------

    def rate_agent(self, agent_principal_id, user_principal_id, rating,
                   review_text=None):
        # type: (str, str, int, Optional[str]) -> dict
        """POST /marketplace/ratings — rate a hired agent (1-5)."""
        body = {
            "agent_principal_id": agent_principal_id,
            "user_principal_id": user_principal_id,
            "rating": rating,
        }
        if review_text is not None:
            body["review_text"] = review_text
        return self._request(
            "POST", "/marketplace/ratings", json_body=body
        )
