"""What a request means when it cannot say which account it is acting for.

Two services resolved that case the same way and both were wrong in the same
direction: ``mapping.get(principal_id) or local_tenant``. A principal nobody
had mapped -- a rotated identifier, a fresh deployment, a typo in the
configured JSON -- landed in ``TESSERA_LOCAL_TENANT_ID`` and acted there as
if it belonged.

That was survivable while the only thing behind the boundary was conversation
state: the worst case was one operator's own draft messages showing up in one
operator's own console. It stops being survivable the moment a directory of
other people's names, phone numbers, and employers sits behind the same
boundary, because then the fallback is the leak.

Unmapped is now a refusal. It is deliberately not a permission error at the
edge: a caller who guessed at an identifier must not be able to tell the
difference between "that account is not yours" and "that account does not
exist", so the surfaces above translate this into a not-found-shaped response.
"""

from libs.repository_contract import TenantContextRequired


class UnmappedPrincipalError(RuntimeError):
    """No configured mapping binds this principal to an account.

    Raised by the tenant resolvers rather than returned, because a return
    value is something a caller can forget to check and a raise is not. The
    message names no tenant on purpose.
    """

    def __init__(self, message="principal is not bound to a tenant"):
        super(UnmappedPrincipalError, self).__init__(message)


class TenantScopeRequired(TenantContextRequired):
    """A repository call that would have run without a tenant predicate.

    The failure mode this exists for is not a caller passing the wrong
    tenant -- that one denies itself. It is a caller passing ``None``, where
    a predicate of ``tenant_id = null`` matches nothing on a good day and
    everything on the day someone rewrites it as an optional filter.
    """

    def __init__(self, message="a tenant is required for this query"):
        super(TenantScopeRequired, self).__init__(message)


class MembershipTenantResolver(object):
    """Resolve an account from explicit configuration or persisted identity.

    Static mappings remain the deliberate override for principals that belong
    to several organizations.  Ordinary users resolve from their persisted
    home organization or, for legacy rows, their single membership.  Missing
    and ambiguous membership are still refusals rather than unsafe defaults.
    """

    def __init__(self, mapping, identity_repository):
        self.mapping = dict(mapping or {})
        self.identity_repository = identity_repository

    def __call__(self, principal_id):
        configured = self.mapping.get(principal_id)
        if isinstance(configured, str) and configured:
            return configured
        principal = self.identity_repository.get_principal(principal_id)
        home = principal.get("home_organization_id") if principal else None
        if isinstance(home, str) and home:
            return home
        memberships = self.identity_repository.organizations_for_principal(
            principal_id
        )
        organizations = sorted({
            row.get("organization_id") for row in memberships
            if isinstance(row.get("organization_id"), str)
            and row.get("organization_id")
        })
        if len(organizations) == 1:
            return organizations[0]
        raise UnmappedPrincipalError()
