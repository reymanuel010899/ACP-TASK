"""Four dimensions that are granted separately and enforced separately.

Every test here is written so that it would fail against the design this unit
replaces -- a single `role` column. A role can express "manager of /acme/sales"
and cannot express "may run a campaign to /acme/sales, may not read the names
in it", which is the pair the campaign flow actually needs.

The projection tests go one further: they assert on what is *absent*. A
preview that leaks a name or a destination still passes every count assertion
anyone would think to write, so the absences are asserted directly, against
the whole payload rather than against the fields a reader remembered to check.
"""

from datetime import datetime, timedelta, timezone

import pytest

from libs.contacts_consent import (
    AUTHORITY_ADMINISTER,
    Actor,
    ConsentEvidence,
    ContactsConsentRepository,
)
from libs.contacts_permissions import (
    AdministratorRequired,
    BranchPermissionsRepository,
    ContactsAccess,
    DIMENSIONS,
    DIMENSION_ADMINISTER,
    DIMENSION_CAMPAIGN_USE,
    DIMENSION_EDIT,
    DIMENSION_VIEW,
    HumanDecisionRequired,
    PermissionDenied,
    TenantScopeRequired,
    mask_destination,
)
from libs.contacts_repository import BranchNotFound, ContactsRepository
from tests.contacts.fake_postgres import FakeDatabase, FakeStore


TENANT = "org:acme"
OTHER_TENANT = "org:globex"

NOW = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)

ADMIN = Actor.human("principal:admin", [AUTHORITY_ADMINISTER])
MANAGER = Actor.human("principal:manager", ["manage_contacts"])
ROBOT = Actor.agent("agent:concierge", [AUTHORITY_ADMINISTER, "manage_contacts"])

ANALYST = "principal:analyst"


class Tree(object):
    """One account's tree, deep enough for inheritance to mean something."""

    def __init__(self, store=None, tenant=TENANT):
        self.tenant = tenant
        self.db = FakeDatabase(store)
        self.contacts = ContactsRepository(self.db)
        self.permissions = BranchPermissionsRepository(
            self.db, contacts=self.contacts,
        )
        self.consent = ContactsConsentRepository(self.db)
        self.access = ContactsAccess(
            self.db, contacts=self.contacts, permissions=self.permissions,
            consent=self.consent,
        )
        self.org = self._branch("Acme", "organization", None)
        self.sales = self._branch("Sales", "department", self.org)
        self.emea = self._branch("EMEA", "folder", self.sales)
        self.iberia = self._branch("Iberia", "folder", self.emea)
        self.finance = self._branch("Finance", "department", self.org)

    def _branch(self, name, kind, parent):
        return self.contacts.create_branch(
            self.tenant, name, kind=kind, parent_branch_id=parent,
        )["branch_id"]

    def person(self, branch, name, number=None, channel="sms"):
        contact = self.contacts.create_contact(self.tenant, branch, name)
        address = None
        if number is not None:
            address = self.contacts.add_address(
                self.tenant, contact["contact_id"], channel, number,
                is_primary=True,
            )
        return contact, address


def _evidence():
    return ConsentEvidence(
        capture_method="web_form",
        captured_at=NOW - timedelta(days=1),
        captured_at_local="2026-08-04T08:00:00-04:00",
        capture_timezone="America/Santo_Domingo",
        jurisdiction="DO",
        disclosure_text="I agree to receive marketing texts from Acme.",
        legal_basis="express_written",
        source="signup_form",
        default_unchecked=True,
    )


# -- inheritance ------------------------------------------------------------

def test_a_grant_on_a_branch_reaches_every_branch_beneath_it():
    tree = Tree()
    tree.permissions.grant(
        TENANT, tree.sales, ANALYST, DIMENSION_VIEW, ADMIN,
    )

    for branch in (tree.sales, tree.emea, tree.iberia):
        assert tree.permissions.holds(TENANT, ANALYST, branch, DIMENSION_VIEW)
    # And stops where the grant stops. A sibling department is not "under
    # sales" and never becomes so by being in the same account.
    assert not tree.permissions.holds(
        TENANT, ANALYST, tree.finance, DIMENSION_VIEW,
    )
    assert not tree.permissions.holds(
        TENANT, ANALYST, tree.org, DIMENSION_VIEW,
    )


def test_an_explicit_restriction_deeper_down_overrides_the_grant_above_it():
    tree = Tree()
    tree.permissions.grant(TENANT, tree.org, ANALYST, DIMENSION_VIEW, ADMIN)
    tree.permissions.restrict(
        TENANT, tree.emea, ANALYST, DIMENSION_VIEW, ADMIN,
        reason="works the Americas desk",
    )

    assert tree.permissions.holds(TENANT, ANALYST, tree.sales, DIMENSION_VIEW)
    assert not tree.permissions.holds(TENANT, ANALYST, tree.emea, DIMENSION_VIEW)
    # The restriction inherits too, which is the half that gets forgotten: a
    # folder inside a closed folder is closed.
    assert not tree.permissions.holds(
        TENANT, ANALYST, tree.iberia, DIMENSION_VIEW,
    )


def test_a_grant_below_a_restriction_reopens_only_that_subtree():
    tree = Tree()
    tree.permissions.grant(TENANT, tree.org, ANALYST, DIMENSION_VIEW, ADMIN)
    tree.permissions.restrict(TENANT, tree.emea, ANALYST, DIMENSION_VIEW, ADMIN)
    tree.permissions.grant(TENANT, tree.iberia, ANALYST, DIMENSION_VIEW, ADMIN)

    assert not tree.permissions.holds(TENANT, ANALYST, tree.emea, DIMENSION_VIEW)
    assert tree.permissions.holds(TENANT, ANALYST, tree.iberia, DIMENSION_VIEW)


def test_revoking_a_restriction_lets_the_inherited_grant_resume():
    tree = Tree()
    tree.permissions.grant(TENANT, tree.org, ANALYST, DIMENSION_VIEW, ADMIN)
    tree.permissions.restrict(TENANT, tree.emea, ANALYST, DIMENSION_VIEW, ADMIN)
    assert not tree.permissions.holds(TENANT, ANALYST, tree.emea, DIMENSION_VIEW)

    assert tree.permissions.revoke(
        TENANT, tree.emea, ANALYST, DIMENSION_VIEW, ADMIN,
    )

    assert tree.permissions.holds(TENANT, ANALYST, tree.emea, DIMENSION_VIEW)


def test_authorized_branches_does_not_hand_back_a_restricted_subtree():
    tree = Tree()
    tree.permissions.grant(TENANT, tree.org, ANALYST, DIMENSION_VIEW, ADMIN)
    tree.permissions.restrict(TENANT, tree.emea, ANALYST, DIMENSION_VIEW, ADMIN)

    allowed = tree.permissions.authorized_branches(
        TENANT, ANALYST, DIMENSION_VIEW,
    )

    assert tree.org in allowed and tree.sales in allowed
    assert tree.finance in allowed
    # The resolved set is already expanded. A caller that re-expanded it to
    # subtrees would walk straight back into these two.
    assert tree.emea not in allowed
    assert tree.iberia not in allowed


def test_moving_a_branch_re_derives_the_permissions_of_its_descendants():
    tree = Tree()
    tree.permissions.grant(TENANT, tree.sales, ANALYST, DIMENSION_VIEW, ADMIN)
    assert tree.permissions.holds(TENANT, ANALYST, tree.iberia, DIMENSION_VIEW)

    # EMEA and everything under it moves out from under Sales.
    tree.contacts.move_branch(TENANT, tree.emea, tree.finance)

    assert not tree.permissions.holds(TENANT, ANALYST, tree.emea, DIMENSION_VIEW)
    assert not tree.permissions.holds(
        TENANT, ANALYST, tree.iberia, DIMENSION_VIEW,
    )
    assert tree.permissions.authorized_branches(
        TENANT, ANALYST, DIMENSION_VIEW,
    ) == [tree.sales]


# -- four dimensions, not one ----------------------------------------------

def test_each_dimension_is_granted_alone_and_leaves_the_other_three_shut():
    tree = Tree()
    for dimension in DIMENSIONS:
        principal = "principal:only-%s" % dimension
        tree.permissions.grant(TENANT, tree.sales, principal, dimension, ADMIN)

        effective = tree.permissions.effective(TENANT, principal, tree.iberia)

        assert effective[dimension] is True
        assert [
            name for name in DIMENSIONS if effective[name]
        ] == [dimension]


def test_editing_and_viewing_move_independently_on_the_same_branch():
    tree = Tree()
    tree.permissions.grant(TENANT, tree.sales, ANALYST, DIMENSION_VIEW, ADMIN)
    tree.permissions.grant(TENANT, tree.sales, ANALYST, DIMENSION_EDIT, ADMIN)
    tree.permissions.restrict(
        TENANT, tree.emea, ANALYST, DIMENSION_EDIT, ADMIN,
    )

    effective = tree.permissions.effective(TENANT, ANALYST, tree.emea)

    assert effective[DIMENSION_VIEW] is True
    assert effective[DIMENSION_EDIT] is False


def test_administering_a_branch_is_the_same_word_as_lifting_a_suppression():
    """The two systems agree on the bar, by sharing the constant.

    If this ever drifts, one of two things becomes possible: a branch
    administrator who cannot resume sending to somebody they blocked, or a
    contact manager who can.
    """
    assert DIMENSION_ADMINISTER == AUTHORITY_ADMINISTER

    tree = Tree()
    _contact, address = tree.person(tree.sales, "Ana Perez", "+18095550100")
    tree.consent.activate_address(TENANT, address["address_id"], ADMIN, now=NOW)
    tree.consent.suppress(
        TENANT, address["address_id"], "suppressed_by_admin", now=NOW,
    )

    # The same actor clears both bars.
    tree.permissions.restrict(TENANT, tree.emea, ANALYST, DIMENSION_VIEW, ADMIN)
    tree.consent.lift_suppression(
        TENANT, address["address_id"], ADMIN, now=NOW,
    )

    # And the contact manager clears neither.
    with pytest.raises(AdministratorRequired):
        tree.permissions.restrict(
            TENANT, tree.iberia, ANALYST, DIMENSION_VIEW, MANAGER,
        )
    tree.consent.suppress(
        TENANT, address["address_id"], "suppressed_by_admin", now=NOW,
    )
    with pytest.raises(AdministratorRequired):
        tree.consent.lift_suppression(
            TENANT, address["address_id"], MANAGER, now=NOW,
        )


# -- who may decide ---------------------------------------------------------

def test_an_agent_cannot_grant_a_permission_however_many_authorities_it_holds():
    tree = Tree()

    with pytest.raises(HumanDecisionRequired):
        tree.permissions.grant(
            TENANT, tree.sales, ANALYST, DIMENSION_VIEW, ROBOT,
        )

    assert tree.permissions.decisions_on_branch(TENANT, tree.sales) == []


def test_a_contact_manager_cannot_grant_or_revoke_authority():
    tree = Tree()

    with pytest.raises(AdministratorRequired):
        tree.permissions.grant(
            TENANT, tree.sales, ANALYST, DIMENSION_VIEW, MANAGER,
        )
    tree.permissions.grant(TENANT, tree.sales, ANALYST, DIMENSION_VIEW, ADMIN)
    with pytest.raises(AdministratorRequired):
        tree.permissions.revoke(
            TENANT, tree.sales, ANALYST, DIMENSION_VIEW, MANAGER,
        )

    assert tree.permissions.holds(TENANT, ANALYST, tree.sales, DIMENSION_VIEW)


def test_every_stored_decision_names_the_human_and_the_authority_they_held():
    tree = Tree()
    tree.permissions.grant(TENANT, tree.sales, ANALYST, DIMENSION_VIEW, ADMIN)

    decision = tree.permissions.decisions_on_branch(TENANT, tree.sales)[0]

    assert decision["decided_by_principal_id"] == ADMIN.principal_id
    assert decision["decided_by_authority"] == AUTHORITY_ADMINISTER
    assert decision["decided_by_actor_kind"] == "human"
    # The principal the authority is *about* is not the one who granted it.
    assert decision["principal_id"] == ANALYST


def test_a_permission_change_refuses_without_a_tenant():
    tree = Tree()

    with pytest.raises(TenantScopeRequired):
        tree.permissions.grant(None, tree.sales, ANALYST, DIMENSION_VIEW, ADMIN)
    with pytest.raises(TenantScopeRequired):
        tree.permissions.effective(None, ANALYST, tree.sales)


def test_an_unknown_dimension_is_refused_rather_than_stored():
    tree = Tree()

    with pytest.raises(ValueError):
        tree.permissions.grant(TENANT, tree.sales, ANALYST, "export", ADMIN)


# -- isolation --------------------------------------------------------------

def test_a_permission_over_another_accounts_branch_cannot_be_written():
    store = FakeStore()
    acme = Tree(store)
    globex = Tree(store, tenant=OTHER_TENANT)

    with pytest.raises(BranchNotFound):
        globex.permissions.grant(
            OTHER_TENANT, acme.sales, ANALYST, DIMENSION_VIEW, ADMIN,
        )


def test_cross_tenant_permission_reads_return_nothing():
    store = FakeStore()
    acme = Tree(store)
    globex = Tree(store, tenant=OTHER_TENANT)
    acme.permissions.grant(TENANT, acme.org, ANALYST, DIMENSION_VIEW, ADMIN)

    # The same principal identifier, asking as the other account, about the
    # branch the grant was written on.
    assert globex.permissions.effective(OTHER_TENANT, ANALYST, acme.org) == {
        dimension: False for dimension in DIMENSIONS
    }
    assert globex.permissions.authorized_branches(
        OTHER_TENANT, ANALYST, DIMENSION_VIEW,
    ) == []
    assert globex.permissions.decisions_on_branch(OTHER_TENANT, acme.org) == []


def test_search_results_never_span_branches_the_principal_cannot_view():
    tree = Tree()
    tree.person(tree.sales, "Ana Perez")
    tree.person(tree.emea, "Ana Restrepo")
    tree.person(tree.finance, "Ana Villanueva")
    tree.permissions.grant(TENANT, tree.org, ANALYST, DIMENSION_VIEW, ADMIN)
    tree.permissions.restrict(TENANT, tree.emea, ANALYST, DIMENSION_VIEW, ADMIN)

    found = [
        row["display_name"] for row
        in tree.access.search(TENANT, ANALYST, "ana")
    ]

    assert found == ["Ana Perez", "Ana Villanueva"]
    # The account-wide search still finds all three, so the omission above is
    # the permission and not the query.
    assert len(tree.contacts.search_contacts(TENANT, "ana")) == 3


def test_a_principal_with_no_grants_at_all_searches_nothing():
    tree = Tree()
    tree.person(tree.sales, "Ana Perez")

    assert tree.access.search(TENANT, "principal:stranger", "ana") == []


# -- the masked destination -------------------------------------------------

def test_the_mask_distinguishes_two_numbers_that_share_their_last_four_digits():
    tree = Tree()
    _first, one = tree.person(tree.sales, "Ana Perez", "+34600555100")
    _second, two = tree.person(tree.sales, "Ana Restrepo", "+34611555100")

    left = mask_destination(
        "sms", one["address"], address_id=one["address_id"], tenant_id=TENANT,
        branch_path="/acme/sales",
    )
    right = mask_destination(
        "sms", two["address"], address_id=two["address_id"], tenant_id=TENANT,
        branch_path="/acme/sales",
    )

    # Same country, same trailing digits, same branch, neither contacted.
    assert left.country_code == right.country_code == "34"
    assert left.visible_tail == right.visible_tail == "5100"
    assert left.branch_path == right.branch_path
    # And still not the same destination, which is what makes "the exact
    # canonical contact" checkable by the human approving it.
    assert left.fingerprint != right.fingerprint
    assert left.text != right.text


def test_the_mask_never_carries_the_destination_it_is_masking():
    masked = mask_destination(
        "sms", "+34 600 555 100", address_id="address:01", tenant_id=TENANT,
        branch_path="/acme/sales", last_contacted_at=NOW,
    )

    rendered = masked.text
    assert "600555" not in rendered.replace(" ", "")
    assert "34600555100" not in rendered.replace(" ", "")
    assert rendered.startswith("+34 ")
    assert "5100" in rendered
    assert "•" in rendered
    assert masked.last_contacted_at == "2026-08-05"


def test_the_fingerprint_is_not_derived_from_the_digits():
    """Otherwise it hands back the number it withheld.

    A phone number is roughly ten billion values. Any hash of the digits --
    salted with an account identifier or anything else the reader also holds
    -- is brute-forced in seconds, which would make the mask decorative.
    """
    from_identifier = mask_destination(
        "sms", "+34600555100", address_id="address:01", tenant_id=TENANT,
    )
    same_number_other_address = mask_destination(
        "sms", "+34600555100", address_id="address:02", tenant_id=TENANT,
    )
    other_number_same_address = mask_destination(
        "sms", "+34999111222", address_id="address:01", tenant_id=TENANT,
    )

    assert from_identifier.fingerprint != same_number_other_address.fingerprint
    assert from_identifier.fingerprint == other_number_same_address.fingerprint


def test_an_email_destination_is_masked_down_to_its_shape():
    masked = mask_destination(
        "email", "Ana.Perez@Example.com", address_id="address:03",
        tenant_id=TENANT,
    )

    assert "ana.perez" not in masked.text.lower()
    assert "example" not in masked.text.lower()
    assert masked.text.startswith("a")
    assert ".com" in masked.text


def test_a_short_number_still_keeps_digits_hidden():
    masked = mask_destination("sms", "+3412345", address_id="address:04")

    assert masked.visible_tail == "345"
    assert "12345" not in masked.text.replace(" ", "")


# -- the redacted audience projection --------------------------------------

def _audience(tree):
    """Three people on one branch: eligible, unapproved, and unreachable."""
    ready, ready_address = tree.person(
        tree.emea, "Ana Perez", "+34600555100",
    )
    tree.consent.activate_address(
        TENANT, ready_address["address_id"], ADMIN, now=NOW,
    )
    tree.consent.grant_consent(
        TENANT, ready_address["address_id"], "marketing", _evidence(), ADMIN,
        now=NOW,
    )
    unapproved, _address = tree.person(
        tree.emea, "Bruno Diaz", "+34611555100",
    )
    nobody, _none = tree.person(tree.emea, "Carla Ruiz")
    return ready, unapproved, nobody


def test_campaign_use_without_view_returns_counts_reasons_and_no_names():
    tree = Tree()
    ready, unapproved, nobody = _audience(tree)
    tree.permissions.grant(
        TENANT, tree.emea, ANALYST, DIMENSION_CAMPAIGN_USE, ADMIN,
    )

    preview = tree.access.audience_preview(
        TENANT, ANALYST, "sms", "marketing", branch_id=tree.emea, now=NOW,
    )

    assert preview["total"] == 3
    assert preview["eligible"] == 1
    assert preview["excluded"] == 2
    assert preview["exclusion_reasons"] == {
        "address_not_usable": 1, "no_address": 1,
    }
    assert preview["redacted"] is True
    # Every name the operator is not entitled to is absent, not null: a key
    # that is sometimes a name and sometimes None invites a renderer to print
    # the hole and a reader to believe the field was empty.
    for entry in preview["entries"]:
        assert "display_name" not in entry
        assert entry["redacted"] is True
    rendered = repr(preview)
    for name in (ready["display_name"], unapproved["display_name"],
                 nobody["display_name"]):
        assert name not in rendered


def test_no_projection_entry_carries_an_unmasked_destination():
    tree = Tree()
    _audience(tree)
    tree.permissions.grant(
        TENANT, tree.emea, ANALYST, DIMENSION_CAMPAIGN_USE, ADMIN,
    )
    tree.permissions.grant(TENANT, tree.emea, ANALYST, DIMENSION_VIEW, ADMIN)

    preview = tree.access.audience_preview(
        TENANT, ANALYST, "sms", "marketing", branch_id=tree.emea, now=NOW,
    )

    # Asserted against the whole payload, including the path where the
    # principal *does* hold view -- "no permission path returns an unmasked
    # destination" is not conditional on the permission.
    rendered = repr(preview).replace(" ", "")
    assert "34600555100" not in rendered
    assert "34611555100" not in rendered
    assert preview["redacted"] is False
    assert [entry["display_name"] for entry in preview["entries"]] == [
        "Ana Perez", "Bruno Diaz", "Carla Ruiz",
    ]


def test_a_principal_with_view_but_not_campaign_use_cannot_target_that_branch():
    tree = Tree()
    _audience(tree)
    tree.permissions.grant(TENANT, tree.emea, ANALYST, DIMENSION_VIEW, ADMIN)

    with pytest.raises(PermissionDenied) as refused:
        tree.access.audience_preview(
            TENANT, ANALYST, "sms", "marketing", branch_id=tree.emea, now=NOW,
        )

    assert refused.value.dimension == DIMENSION_CAMPAIGN_USE
    # Refused rather than returned empty: an empty audience reads as a rule
    # that matched nobody, and sends the operator to fix the wrong thing.
    assert tree.access.search(TENANT, ANALYST, "ana")


def test_a_restriction_inside_the_targeted_subtree_removes_those_people():
    tree = Tree()
    _audience(tree)
    tree.person(tree.iberia, "Diego Sanz", "+34622555100")
    tree.permissions.grant(
        TENANT, tree.sales, ANALYST, DIMENSION_CAMPAIGN_USE, ADMIN,
    )
    tree.permissions.restrict(
        TENANT, tree.iberia, ANALYST, DIMENSION_CAMPAIGN_USE, ADMIN,
    )

    preview = tree.access.audience_preview(
        TENANT, ANALYST, "sms", "marketing", branch_id=tree.sales, now=NOW,
    )

    assert preview["total"] == 3
    assert all(
        entry["branch_path"] != "/acme/sales/emea/iberia"
        for entry in preview["entries"]
    )
