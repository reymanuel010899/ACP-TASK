"""Groupings that reference the canonical record and never copy it.

The requirement these protect (R9) fails quietly. Nothing crashes when a
membership row starts carrying a name: the list keeps working, the campaign
keeps sending, and the only symptom is that a renamed contact is one person
in the directory and a different person in the audience. So the tests assert
identity of the *record* -- one row in `contacts.contacts`, read twice -- and
assert that the membership tables hold nothing worth reading on their own.

The scoping tests are the other half. A list or a segment that resolves past
the requester's branch permissions is a way around the tree, and it is the way
around the tree that looks most like a feature.
"""

import pytest

from libs.contacts_consent import AUTHORITY_ADMINISTER, Actor
from libs.contacts_permissions import (
    BranchPermissionsRepository,
    ContactsAccess,
    DIMENSION_VIEW,
    GroupingNotFound,
    SegmentRuleInvalid,
)
from libs.contacts_repository import ContactsRepository, rule_hash
from tests.contacts.fake_postgres import (
    COLUMNS,
    FakeDatabase,
    FakeIntegrityError,
    FakeStore,
)


TENANT = "org:acme"
OTHER_TENANT = "org:globex"

ADMIN = Actor.human("principal:admin", [AUTHORITY_ADMINISTER])
ANALYST = "principal:analyst"


class Tree(object):
    def __init__(self, store=None, tenant=TENANT):
        self.tenant = tenant
        self.db = FakeDatabase(store)
        self.contacts = ContactsRepository(self.db)
        self.permissions = BranchPermissionsRepository(
            self.db, contacts=self.contacts,
        )
        self.access = ContactsAccess(
            self.db, contacts=self.contacts, permissions=self.permissions,
        )
        self.org = self._branch("Acme", "organization", None)
        self.sales = self._branch("Sales", "department", self.org)
        self.emea = self._branch("EMEA", "folder", self.sales)
        self.finance = self._branch("Finance", "department", self.org)

    def _branch(self, name, kind, parent):
        return self.contacts.create_branch(
            self.tenant, name, kind=kind, parent_branch_id=parent,
        )["branch_id"]

    def person(self, branch, name, **fields):
        return self.contacts.create_contact(self.tenant, branch, name, **fields)

    def everything_visible(self, principal=ANALYST):
        self.permissions.grant(
            self.tenant, self.org, principal, DIMENSION_VIEW, ADMIN,
        )
        return self.permissions.authorized_branches(
            self.tenant, principal, DIMENSION_VIEW,
        )


# -- one record, many groupings --------------------------------------------

def test_one_contact_appears_in_two_lists_without_a_second_record_existing():
    tree = Tree()
    ana = tree.person(tree.sales, "Ana Perez")
    vips = tree.contacts.create_list(TENANT, tree.sales, "VIPs")
    renewals = tree.contacts.create_list(TENANT, tree.sales, "Renewals")
    visible = tree.everything_visible()

    tree.contacts.add_to_list(TENANT, vips["list_id"], ana["contact_id"])
    tree.contacts.add_to_list(TENANT, renewals["list_id"], ana["contact_id"])

    in_vips = tree.contacts.list_members(TENANT, vips["list_id"], visible)
    in_renewals = tree.contacts.list_members(
        TENANT, renewals["list_id"], visible,
    )
    assert [row["contact_id"] for row in in_vips] == [ana["contact_id"]]
    assert in_vips == in_renewals
    # One canonical row, read twice. Not two rows that happen to agree today.
    assert len(tree.db.store.rows("contacts.contacts")) == 1
    assert len(tree.db.store.rows("contacts.contact_list_members")) == 2


def test_a_membership_row_carries_no_field_that_can_go_stale():
    tree = Tree()
    ana = tree.person(tree.sales, "Ana Perez")
    vips = tree.contacts.create_list(TENANT, tree.sales, "VIPs")
    tree.contacts.add_to_list(TENANT, vips["list_id"], ana["contact_id"])

    member = tree.db.store.rows("contacts.contact_list_members")[0]

    # Identifiers and provenance. Nothing that a rename could contradict --
    # which is the schema's half of "one canonical record".
    assert set(member) == {
        "tenant_id", "list_id", "contact_id", "added_by_principal_id",
        "added_at",
    }
    for copied in ("display_name", "address", "locale", "timezone"):
        assert copied not in COLUMNS["contacts.contact_list_members"]
        assert copied not in COLUMNS["contacts.contact_tag_assignments"]


def test_renaming_a_contact_shows_through_every_grouping_at_once():
    tree = Tree()
    ana = tree.person(tree.sales, "Ana Perez")
    vips = tree.contacts.create_list(TENANT, tree.sales, "VIPs")
    tag = tree.contacts.create_tag(TENANT, "VIP")
    tree.contacts.add_to_list(TENANT, vips["list_id"], ana["contact_id"])
    tree.contacts.assign_tag(TENANT, tag["tag_id"], ana["contact_id"])
    visible = tree.everything_visible()

    tree.db.store.rows("contacts.contacts")[0]["display_name"] = "Ana Perez-Gil"

    assert tree.contacts.list_members(TENANT, vips["list_id"], visible)[0][
        "display_name"
    ] == "Ana Perez-Gil"
    assert tree.contacts.tagged_contacts(TENANT, tag["tag_id"], visible)[0][
        "display_name"
    ] == "Ana Perez-Gil"


def test_adding_the_same_contact_to_a_list_twice_is_one_membership():
    tree = Tree()
    ana = tree.person(tree.sales, "Ana Perez")
    vips = tree.contacts.create_list(TENANT, tree.sales, "VIPs")

    tree.contacts.add_to_list(TENANT, vips["list_id"], ana["contact_id"])
    tree.contacts.add_to_list(TENANT, vips["list_id"], ana["contact_id"])

    assert len(tree.db.store.rows("contacts.contact_list_members")) == 1


def test_removing_a_contact_from_a_list_leaves_the_person_untouched():
    tree = Tree()
    ana = tree.person(tree.sales, "Ana Perez")
    vips = tree.contacts.create_list(TENANT, tree.sales, "VIPs")
    tree.contacts.add_to_list(TENANT, vips["list_id"], ana["contact_id"])

    assert tree.contacts.remove_from_list(
        TENANT, vips["list_id"], ana["contact_id"],
    )

    assert tree.contacts.get_contact(TENANT, ana["contact_id"]) is not None
    assert tree.contacts.list_members(
        TENANT, vips["list_id"], tree.everything_visible(),
    ) == []


def test_a_tag_is_a_label_on_the_record_and_reads_back_by_slug():
    tree = Tree()
    ana = tree.person(tree.sales, "Ana Perez")
    tag = tree.contacts.create_tag(TENANT, "Key Account")
    tree.contacts.assign_tag(TENANT, tag["tag_id"], ana["contact_id"])

    assert tag["slug"] == "key-account"
    assert tree.contacts.tag_slugs_for_contact(
        TENANT, ana["contact_id"],
    ) == ["key-account"]
    tree.contacts.unassign_tag(TENANT, tag["tag_id"], ana["contact_id"])
    assert tree.contacts.tag_slugs_for_contact(TENANT, ana["contact_id"]) == []


# -- permission scoping -----------------------------------------------------

def test_a_list_never_resolves_past_the_requesters_branch_permissions():
    tree = Tree()
    inside = tree.person(tree.sales, "Ana Perez")
    outside = tree.person(tree.finance, "Bruno Diaz")
    vips = tree.contacts.create_list(TENANT, tree.sales, "VIPs")
    tree.contacts.add_to_list(TENANT, vips["list_id"], inside["contact_id"])
    tree.contacts.add_to_list(TENANT, vips["list_id"], outside["contact_id"])
    tree.permissions.grant(TENANT, tree.sales, ANALYST, DIMENSION_VIEW, ADMIN)

    seen = tree.access.list_members(TENANT, ANALYST, vips["list_id"])

    assert [row["display_name"] for row in seen] == ["Ana Perez"]
    # The membership itself was not deleted -- the list still points at both.
    assert len(tree.db.store.rows("contacts.contact_list_members")) == 2


def test_a_tag_never_resolves_past_the_requesters_branch_permissions():
    tree = Tree()
    inside = tree.person(tree.sales, "Ana Perez")
    outside = tree.person(tree.finance, "Bruno Diaz")
    tag = tree.contacts.create_tag(TENANT, "VIP")
    tree.contacts.assign_tag(TENANT, tag["tag_id"], inside["contact_id"])
    tree.contacts.assign_tag(TENANT, tag["tag_id"], outside["contact_id"])
    tree.permissions.grant(TENANT, tree.sales, ANALYST, DIMENSION_VIEW, ADMIN)

    seen = tree.access.tagged_contacts(TENANT, ANALYST, tag["tag_id"])

    assert [row["display_name"] for row in seen] == ["Ana Perez"]


def test_resolving_a_grouping_without_a_branch_bound_is_not_expressible():
    """The signature is the guard, so forgetting is a TypeError."""
    tree = Tree()
    vips = tree.contacts.create_list(TENANT, tree.sales, "VIPs")

    with pytest.raises(TypeError):
        tree.contacts.list_members(TENANT, vips["list_id"])


def test_an_unknown_list_is_absence_rather_than_a_confirmed_identifier():
    tree = Tree()

    with pytest.raises(GroupingNotFound):
        tree.contacts.list_members(TENANT, "list:does-not-exist", [tree.sales])


# -- dynamic segments -------------------------------------------------------

def test_a_segment_is_a_stored_rule_and_not_a_stored_result():
    tree = Tree()
    rule = {"name_contains": "ana", "include_subtree": True}
    segment = tree.contacts.create_segment(
        TENANT, tree.sales, "Anas in sales", rule,
    )
    visible = tree.everything_visible()
    assert tree.contacts.resolve_segment(
        TENANT, segment["segment_id"], visible,
    ) == []

    # Somebody matching the rule arrives after the segment was written.
    tree.person(tree.emea, "Ana Perez")

    resolved = tree.contacts.resolve_segment(
        TENANT, segment["segment_id"], visible,
    )
    assert [row["display_name"] for row in resolved] == ["Ana Perez"]
    assert segment["definition"] == rule
    assert segment["rule_hash"] == rule_hash(rule)
    # No materialised membership anywhere -- which is what makes "expansion
    # invalidates authorization" checkable later.
    assert tree.db.store.rows("contacts.contact_list_members") == []


def test_the_rule_hash_moves_when_the_rule_does_and_not_otherwise():
    assert rule_hash({"a": 1, "b": 2}) == rule_hash({"b": 2, "a": 1})
    assert rule_hash({"name_contains": "ana"}) != rule_hash(
        {"name_contains": "anna"}
    )


def test_a_segment_resolves_only_within_branches_the_requester_may_view():
    tree = Tree()
    tree.person(tree.sales, "Ana Perez")
    tree.person(tree.emea, "Ana Restrepo")
    segment = tree.contacts.create_segment(
        TENANT, tree.sales, "Every Ana", {"name_contains": "ana"},
    )
    tree.permissions.grant(TENANT, tree.sales, ANALYST, DIMENSION_VIEW, ADMIN)
    tree.permissions.restrict(TENANT, tree.emea, ANALYST, DIMENSION_VIEW, ADMIN)

    resolved = tree.access.resolve_segment(
        TENANT, ANALYST, segment["segment_id"],
    )

    assert [row["display_name"] for row in resolved] == ["Ana Perez"]
    # The rule itself is unchanged and still reaches both when the account's
    # own administrator resolves it -- the narrowing is the permission.
    assert len(tree.contacts.resolve_segment(
        TENANT, segment["segment_id"], tree.everything_visible("principal:boss"),
    )) == 2


def test_a_segment_rule_cannot_reach_outside_the_branch_it_was_scoped_to():
    tree = Tree()
    tree.person(tree.finance, "Bruno Diaz")
    segment = tree.contacts.create_segment(
        TENANT, tree.sales, "Sneaky", {"branch_id": tree.finance},
    )

    with pytest.raises(SegmentRuleInvalid):
        tree.contacts.resolve_segment(
            TENANT, segment["segment_id"], tree.everything_visible(),
        )


def test_a_rule_term_the_evaluator_does_not_implement_is_refused():
    """Refused, not ignored. A skipped term silently widens the audience."""
    tree = Tree()

    with pytest.raises(SegmentRuleInvalid):
        tree.contacts.create_segment(
            TENANT, tree.sales, "Spanish opt-ins",
            {"name_contains": "ana", "opted_in": True},
        )


def test_a_segment_filters_on_tags_locale_and_channel_together():
    tree = Tree()
    matching = tree.person(tree.sales, "Ana Perez", locale="es-ES")
    wrong_locale = tree.person(tree.sales, "Ana Restrepo", locale="en-GB")
    no_channel = tree.person(tree.sales, "Ana Villanueva", locale="es-ES")
    tag = tree.contacts.create_tag(TENANT, "VIP")
    for person in (matching, wrong_locale, no_channel):
        tree.contacts.assign_tag(TENANT, tag["tag_id"], person["contact_id"])
    for offset, person in enumerate((matching, wrong_locale)):
        tree.contacts.add_address(
            TENANT, person["contact_id"], "sms", "+3460055010%d" % offset,
        )
    segment = tree.contacts.create_segment(
        TENANT, tree.sales, "Spanish VIPs on SMS",
        {"locale": "es-ES", "has_channel": "sms", "tag_slugs": ["vip"]},
    )

    resolved = tree.contacts.resolve_segment(
        TENANT, segment["segment_id"], tree.everything_visible(),
    )

    assert [row["display_name"] for row in resolved] == ["Ana Perez"]


def test_a_segment_can_stay_on_one_branch_instead_of_its_subtree():
    tree = Tree()
    tree.person(tree.sales, "Ana Perez")
    tree.person(tree.emea, "Ana Restrepo")
    segment = tree.contacts.create_segment(
        TENANT, tree.sales, "Sales desk only",
        {"name_contains": "ana", "include_subtree": False},
    )

    resolved = tree.contacts.resolve_segment(
        TENANT, segment["segment_id"], tree.everything_visible(),
    )

    assert [row["display_name"] for row in resolved] == ["Ana Perez"]


# -- isolation --------------------------------------------------------------

def test_a_list_cannot_be_pointed_at_another_accounts_contact():
    store = FakeStore()
    acme = Tree(store)
    globex = Tree(store, tenant=OTHER_TENANT)
    ana = acme.person(acme.sales, "Ana Perez")
    theirs = globex.contacts.create_list(OTHER_TENANT, globex.sales, "Targets")

    with pytest.raises(FakeIntegrityError):
        globex.contacts.add_to_list(
            OTHER_TENANT, theirs["list_id"], ana["contact_id"],
        )


def test_a_list_from_another_account_reads_as_absent():
    store = FakeStore()
    acme = Tree(store)
    globex = Tree(store, tenant=OTHER_TENANT)
    ana = acme.person(acme.sales, "Ana Perez")
    vips = acme.contacts.create_list(TENANT, acme.sales, "VIPs")
    acme.contacts.add_to_list(TENANT, vips["list_id"], ana["contact_id"])

    assert globex.contacts.get_list(OTHER_TENANT, vips["list_id"]) is None
    with pytest.raises(GroupingNotFound):
        globex.contacts.list_members(
            OTHER_TENANT, vips["list_id"], [acme.sales, globex.sales],
        )


def test_a_segment_from_another_account_resolves_to_nothing():
    store = FakeStore()
    acme = Tree(store)
    globex = Tree(store, tenant=OTHER_TENANT)
    acme.person(acme.sales, "Ana Perez")
    segment = acme.contacts.create_segment(
        TENANT, acme.sales, "Every Ana", {"name_contains": "ana"},
    )

    assert globex.contacts.get_segment(OTHER_TENANT, segment["segment_id"]) \
        is None
    with pytest.raises(GroupingNotFound):
        globex.contacts.resolve_segment(
            OTHER_TENANT, segment["segment_id"], [acme.sales],
        )
