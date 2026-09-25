"""Shared contracts for repositories that own tenant-private state.

Public catalog repositories may operate without a tenant. A repository method
that reads or mutates tenant-owned data must call :func:`require_tenant_context`
before issuing SQL so callers receive a clear application error in addition to
PostgreSQL's fail-closed RLS boundary.
"""

from typing import Optional

from libs.db import current_organization_id


class TenantContextRequired(ValueError):
    """No non-empty organization is bound to the current request."""

    def __init__(self, message="tenant membership is required"):
        super(TenantContextRequired, self).__init__(message)


def normalize_tenant_id(value: Optional[str]) -> Optional[str]:
    """Return a normalized tenant identifier, or ``None`` when unusable."""
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def require_tenant_context() -> str:
    """Return the current organization or raise a stable typed failure."""
    organization_id = normalize_tenant_id(current_organization_id())
    if organization_id is None:
        raise TenantContextRequired()
    return organization_id
