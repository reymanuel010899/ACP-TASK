import pytest

from libs.tenancy import MembershipTenantResolver, UnmappedPrincipalError


class Identity:
    def __init__(self, home=None, memberships=()):
        self.home = home
        self.memberships = list(memberships)

    def get_principal(self, principal_id):
        return {
            "principal_id": principal_id,
            "home_organization_id": self.home,
        }

    def organizations_for_principal(self, principal_id):
        return [
            {"principal_id": principal_id, "organization_id": organization_id}
            for organization_id in self.memberships
        ]


def test_persisted_home_organization_resolves_without_static_env_mapping():
    resolver = MembershipTenantResolver({}, Identity(home="org:local"))

    assert resolver("principal:new") == "org:local"


def test_single_persisted_membership_resolves_without_a_home_organization():
    resolver = MembershipTenantResolver(
        {}, Identity(memberships=["org:local"]),
    )

    assert resolver("principal:new") == "org:local"


def test_ambiguous_or_missing_membership_is_refused_without_explicit_mapping():
    for memberships in ([], ["org:a", "org:b"]):
        resolver = MembershipTenantResolver({}, Identity(memberships=memberships))
        with pytest.raises(UnmappedPrincipalError):
            resolver("principal:new")


def test_explicit_mapping_remains_the_override_for_multiple_memberships():
    resolver = MembershipTenantResolver(
        {"principal:new": "org:b"}, Identity(memberships=["org:a", "org:b"]),
    )

    assert resolver("principal:new") == "org:b"
