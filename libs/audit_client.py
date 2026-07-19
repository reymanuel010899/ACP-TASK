"""Best-effort client for the central Audit & Compliance service (U12).

Emitting audit entries must NEVER break the calling service: ``log`` is
fire-and-forget — every network/HTTP/parse error is swallowed silently.
Services that are configured without an audit URL use ``NullAuditClient``
(a pure no-op), so instrumented code paths are identical either way:

    self.audit_client = make_audit_client(audit_url)
    ...
    self.audit_client.log(principal_id, "work.complete", resource_id=task_id)
"""

from typing import Optional

import requests

DEFAULT_TIMEOUT = 2.0


class AuditClient:
    """HTTP client for the central audit service."""

    def __init__(self, audit_url, timeout=DEFAULT_TIMEOUT):
        # type: (str, float) -> None
        self.audit_url = audit_url.rstrip("/")
        self.timeout = timeout

    def log(self, principal_id, activity_type, resource_id=None,
            status="ok", details=None):
        # type: (str, str, Optional[str], str, Optional[dict]) -> None
        """Emit one audit entry, best-effort.

        Swallows ALL errors (connection refused, timeouts, bad responses):
        audit is an observability side channel, never a dependency.
        """
        body = {
            "principal_id": principal_id,
            "activity_type": activity_type,
            "status": status,
        }
        if resource_id is not None:
            body["resource_id"] = resource_id
        if details is not None:
            body["details"] = details
        try:
            requests.post(
                "%s/audit" % self.audit_url, json=body, timeout=self.timeout
            )
        except Exception:
            # Best-effort by contract: a dead/slow/broken audit service
            # must never surface as an error in the calling service.
            pass
        return None

    def query(self, principal_id=None, activity_type=None, resource_id=None,
              start_time=None, end_time=None, limit=None):
        # type: (Optional[str], Optional[str], Optional[str], Optional[str], Optional[str], Optional[int]) -> dict
        """Query entries; ``{"entries": [...], "total_matched": n}``.

        Unlike ``log``, reads raise normally (requests exceptions) — a
        caller asking questions of the audit trail wants real answers.
        """
        params = {}
        if principal_id is not None:
            params["principal_id"] = principal_id
        if activity_type is not None:
            params["activity_type"] = activity_type
        if resource_id is not None:
            params["resource_id"] = resource_id
        if start_time is not None:
            params["start_time"] = start_time
        if end_time is not None:
            params["end_time"] = end_time
        if limit is not None:
            params["limit"] = limit
        resp = requests.get(
            "%s/audit" % self.audit_url, params=params, timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()


class NullAuditClient:
    """No-op stand-in used when no audit service is configured."""

    def log(self, principal_id, activity_type, resource_id=None,
            status="ok", details=None):
        # type: (str, str, Optional[str], str, Optional[dict]) -> None
        return None

    def query(self, principal_id=None, activity_type=None, resource_id=None,
              start_time=None, end_time=None, limit=None):
        # type: (Optional[str], Optional[str], Optional[str], Optional[str], Optional[str], Optional[int]) -> dict
        return {"entries": [], "total_matched": 0}


def make_audit_client(audit_url, timeout=DEFAULT_TIMEOUT):
    # type: (Optional[str], float) -> object
    """AuditClient when a URL is configured, NullAuditClient otherwise."""
    if audit_url:
        return AuditClient(audit_url, timeout=timeout)
    return NullAuditClient()
