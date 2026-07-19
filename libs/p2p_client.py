"""Shared P2P client for direct app-to-app communication (U6, RFC-0003).

The Registry is a signaling hub, never a proxy: this client discovers a
target app's ``p2p_endpoint`` via ``GET {registry}/apps/{app_id}``, then
POSTs the P2P request DIRECTLY to the app at ``{p2p_endpoint}/p2p/request``.

Usage::

    from libs.p2p_client import P2PClient

    client = P2PClient("http://127.0.0.1:8090")
    response = client.p2p_request(
        target_app_id="marketplace",
        requester_principal_id="user:alice",
        request_type="ping",
        capability_id="p2p.ping",
        input={},
    )
    # response == {"result": {"pong": True, "app_id": "marketplace"},
    #              "evidence_id": "..."}

Errors are raised as :class:`P2PError` subclasses: :class:`AppNotFound`
when the target app is not registered, :class:`P2PPermissionDenied`
(carrying the Registry's ``reason``) when the target app returns 403.
"""

from typing import Optional

import requests

DEFAULT_TIMEOUT = 5.0


class P2PError(Exception):
    """Base error for P2P discovery/request failures."""


class AppNotFound(P2PError):
    """The target app_id is not registered with the Registry."""


class P2PPermissionDenied(P2PError):
    """The target app denied the request (403) after its Registry check."""

    def __init__(self, message, reason=None):
        # type: (str, Optional[str]) -> None
        P2PError.__init__(self, message)
        self.reason = reason


class P2PClient(object):
    """Discover apps via the Registry, then talk to them directly."""

    def __init__(self, registry_url, timeout=DEFAULT_TIMEOUT):
        # type: (str, float) -> None
        if not registry_url:
            raise ValueError("registry_url is required")
        self.registry_url = registry_url.rstrip("/")
        self.timeout = timeout

    # -- discovery ------------------------------------------------------------

    def discover_app(self, app_id):
        # type: (str) -> dict
        """Fetch an app's record (``GET /apps/{app_id}``).

        Returns the app dict (``app_id``, ``app_endpoint``,
        ``p2p_endpoint``, ``capabilities``, timestamps). Raises
        :class:`AppNotFound` for an unknown app_id, :class:`P2PError` on
        registry/network failures.
        """
        try:
            resp = requests.get(
                "%s/apps/%s" % (self.registry_url, app_id),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise P2PError("registry unreachable: %s" % exc)
        if resp.status_code == 404:
            raise AppNotFound("app not registered: %s" % app_id)
        if resp.status_code != 200:
            raise P2PError(
                "registry app lookup failed (%d): %s"
                % (resp.status_code, resp.text)
            )
        app = self._parse_json(resp).get("app")
        if not isinstance(app, dict):
            raise P2PError("registry returned a malformed app record")
        return app

    # -- permission check -----------------------------------------------------

    def check_permission(
        self, requester_principal_id, target_app_id, capability_id
    ):
        # type: (str, str, str) -> dict
        """Ask the Registry for a permission verdict without sending the
        request; returns ``{"allowed": bool, "reason": str}``."""
        try:
            resp = requests.post(
                "%s/p2p/permissions/check" % self.registry_url,
                json={
                    "requester_principal_id": requester_principal_id,
                    "target_app_id": target_app_id,
                    "capability_id": capability_id,
                },
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise P2PError("registry unreachable: %s" % exc)
        if resp.status_code != 200:
            raise P2PError(
                "permission check failed (%d): %s"
                % (resp.status_code, resp.text)
            )
        return self._parse_json(resp)

    # -- direct P2P request ---------------------------------------------------

    def p2p_request(
        self,
        target_app_id,
        requester_principal_id,
        request_type,
        capability_id,
        input=None,  # noqa: A002 - RFC-0003 field name
        session_id=None,
    ):
        # type: (str, str, str, str, Optional[dict], Optional[str]) -> dict
        """Discover the target's p2p_endpoint, then POST the request to the
        app DIRECTLY (``{p2p_endpoint}/p2p/request``).

        Returns the app's response body (``{"result": ..., "evidence_id":
        ...}``). Raises :class:`P2PPermissionDenied` on 403 (with the
        Registry's reason), :class:`AppNotFound`/:class:`P2PError`
        otherwise.
        """
        app = self.discover_app(target_app_id)
        endpoint = app.get("p2p_endpoint")
        if not isinstance(endpoint, str) or not endpoint:
            raise P2PError(
                "app '%s' has no p2p_endpoint registered" % target_app_id
            )

        payload = {
            "requester_principal_id": requester_principal_id,
            "request_type": request_type,
            "capability_id": capability_id,
            "input": input if input is not None else {},
        }
        if session_id is not None:
            payload["session_id"] = session_id

        try:
            resp = requests.post(
                "%s/p2p/request" % endpoint.rstrip("/"),
                json=payload,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise P2PError(
                "target app '%s' unreachable at %s: %s"
                % (target_app_id, endpoint, exc)
            )

        if resp.status_code == 403:
            body = self._parse_json(resp, lenient=True)
            raise P2PPermissionDenied(
                "permission denied by app '%s': %s"
                % (target_app_id, body.get("reason", "no reason given")),
                reason=body.get("reason"),
            )
        if resp.status_code != 200:
            raise P2PError(
                "p2p request to '%s' failed (%d): %s"
                % (target_app_id, resp.status_code, resp.text)
            )
        return self._parse_json(resp)

    # -- helpers --------------------------------------------------------------

    @staticmethod
    def _parse_json(resp, lenient=False):
        # type: (requests.Response, bool) -> dict
        try:
            body = resp.json()
        except ValueError:
            if lenient:
                return {}
            raise P2PError("response is not valid JSON: %s" % resp.text)
        if not isinstance(body, dict):
            if lenient:
                return {}
            raise P2PError("response is not a JSON object")
        return body
