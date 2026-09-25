"""Branch authority, the groupings that reference it, and the masked view.

Three things live here because they are the same thing seen from three
distances, and splitting them would let them disagree.

**Authority is four independent dimensions.** Viewing, editing, administering,
and using contacts in campaigns are separately grantable (R11), which is only
meaningful if they are separately *enforced*. The dimension that keeps
tripping systems up is campaign-use without view: a campaign operator has to
fix an audience, see why people fell out of it, and authorise a send, and none
of that requires knowing anybody's name. A design where "may send to them"
implies "may read them" hands the entire directory to whoever runs campaigns.

**Inheritance is resolved, never stored.** A grant on '/acme/sales' is one
row. Every descendant gets it by walking ancestry at read time, and an
explicit restriction wins by sitting deeper on that same ancestry. The
alternative -- materialising the closure -- means a branch move has to rewrite
it, and a permission set that is stale for the length of one rewrite is a
permission set that is wrong. Because `contacts.branches.path` moves with the
subtree, a move re-derives for free and cannot be forgotten.

**The redacted projection is a read model, not a permission check.** This is
the distinction that makes the campaign flow possible at all. Asking "may this
principal see names?" and returning nothing when the answer is no leaves the
operator unable to do the job they *are* authorised for. So the projection
answers a different question -- how many, why were they excluded, and which
destinations are these -- with every destination masked and every name absent
unless view is separately held.

The mask is here rather than in a formatter because a formatter is skippable.
An approval preview that shows `+34 ••• ••• 123` for two different people
makes "the exact canonical contact" (R14) unverifiable by the human approving
it, so the mask carries enough to tell two rows apart -- country, trailing
digits, branch path, last-contacted, and a fingerprint -- while never carrying
the destination.
"""

import hashlib

from psycopg.rows import dict_row

from libs.contacts_consent import (
    AUTHORITY_ADMINISTER,
    Actor,
    AdministratorRequired,
    HumanDecisionRequired,
)
from libs.contacts_repository import (
    BranchNotFound,
    ContactsRepository,
    GroupingNotFound,
    SegmentRuleInvalid,
    normalize_channel_address,
)
from libs.tenancy import TenantScopeRequired
from libs.ulid import generate_ulid


__all__ = [
    "Actor",
    "AdministratorRequired",
    "BranchPermissionsRepository",
    "ContactsAccess",
    "GroupingNotFound",
    "SegmentRuleInvalid",
    "DIMENSIONS",
    "DIMENSION_ADMINISTER",
    "DIMENSION_CAMPAIGN_USE",
    "DIMENSION_EDIT",
    "DIMENSION_VIEW",
    "HumanDecisionRequired",
    "MaskedDestination",
    "PermissionDenied",
    "TenantScopeRequired",
    "mask_destination",
]


DIMENSION_VIEW = "view"
DIMENSION_EDIT = "edit"
#: Not a second spelling of 0018's authority -- the same object. Delegating
#: authority over a branch and lifting a suppression are the same bar, and
#: binding them at the name means a future change to one cannot loosen the
#: other while both keep looking correct.
DIMENSION_ADMINISTER = AUTHORITY_ADMINISTER
DIMENSION_CAMPAIGN_USE = "campaign_use"

#: The four, and only the four. Adding a fifth is a migration, not a string.
DIMENSIONS = (
    DIMENSION_VIEW, DIMENSION_EDIT, DIMENSION_ADMINISTER,
    DIMENSION_CAMPAIGN_USE,
)

EFFECTS = ("grant", "restrict")

_PERMISSION_COLUMNS = (
    "permission_id", "tenant_id", "branch_id", "principal_id", "dimension",
    "effect", "decided_by_principal_id", "decided_by_authority",
    "decided_by_actor_kind", "reason",
)

_PERMISSION_SELECT = ", ".join(_PERMISSION_COLUMNS)

#: What a masked telephone destination shows of the subscriber number. Four is
#: what a person can read back over the phone to confirm; the fingerprint is
#: what actually distinguishes two of them.
VISIBLE_TRAILING_DIGITS = 4

MASK_GLYPH = "•"

#: Length of the destination fingerprint in hex characters. Sixteen million
#: values against an audience of thousands: collisions are not the risk here.
FINGERPRINT_LENGTH = 8

#: E.164 country calling codes, longest match first. Not exhaustive, and
#: deliberately data rather than a parser -- an unlisted code yields a null
#: country, which is a worse mask but never a wrong one.
_CALLING_CODES_3 = (
    "212", "213", "216", "218", "220", "221", "222", "223", "224", "225",
    "226", "227", "228", "229", "230", "231", "232", "233", "234", "235",
    "236", "237", "238", "239", "240", "241", "242", "243", "244", "245",
    "246", "248", "249", "250", "251", "252", "253", "254", "255", "256",
    "257", "258", "260", "261", "262", "263", "264", "265", "266", "267",
    "268", "269", "290", "291", "297", "298", "299", "350", "351", "352",
    "353", "354", "355", "356", "357", "358", "359", "370", "371", "372",
    "373", "374", "375", "376", "377", "378", "380", "381", "382", "383",
    "385", "386", "387", "389", "420", "421", "423", "500", "501", "502",
    "503", "504", "505", "506", "507", "508", "509", "590", "591", "592",
    "593", "594", "595", "596", "597", "598", "599", "670", "672", "673",
    "674", "675", "676", "677", "678", "679", "680", "681", "682", "683",
    "685", "686", "687", "688", "689", "690", "691", "692", "850", "852",
    "853", "855", "856", "880", "886", "960", "961", "962", "963", "964",
    "965", "966", "967", "968", "970", "971", "972", "973", "974", "975",
    "976", "977", "992", "993", "994", "995", "996", "998",
)
_CALLING_CODES_2 = (
    "20", "27", "30", "31", "32", "33", "34", "36", "39", "40", "41", "43",
    "44", "45", "46", "47", "48", "49", "51", "52", "53", "54", "55", "56",
    "57", "58", "60", "61", "62", "63", "64", "65", "66", "81", "82", "84",
    "86", "90", "91", "92", "93", "94", "95", "98",
)
_CALLING_CODES_1 = ("1", "7")


class PermissionDenied(PermissionError):
    """This principal does not hold this dimension over this branch.

    Raised rather than returned empty when the caller named a branch on
    purpose -- "you asked to target /acme/sales and you may not" is
    actionable, whereas an empty audience looks like a rule that matched
    nobody and sends an operator to fix the wrong thing.

    Reads that were not aimed at a named branch do the opposite: a search
    silently omits what the principal may not see, because a refusal there
    would confirm that the hidden branch exists.
    """

    def __init__(self, dimension=None, message=None):
        self.dimension = dimension
        super(PermissionDenied, self).__init__(
            message or "not permitted on this branch"
        )


# -- the mask ---------------------------------------------------------------

class MaskedDestination(object):
    """A destination an operator can tell apart but cannot read.

    The fingerprint is derived from the address *identifier*, never from the
    digits, and that is not a stylistic choice. A phone number lives in a
    space of about ten billion values; a hash of the number itself, salted
    with anything an attacker also holds -- an account id, a tenant slug --
    is recoverable by brute force in seconds, which would hand back exactly
    the destination the mask just withheld. The address identifier is a
    random ULID, so the same fingerprint is stable for the same address and
    reveals nothing about what the address is.
    """

    __slots__ = (
        "channel", "country_code", "digit_count", "visible_tail",
        "fingerprint", "branch_path", "last_contacted_at", "text",
    )

    def __init__(
        self, channel, text, country_code=None, digit_count=None,
        visible_tail=None, fingerprint=None, branch_path=None,
        last_contacted_at=None,
    ):
        self.channel = channel
        self.text = text
        self.country_code = country_code
        self.digit_count = digit_count
        self.visible_tail = visible_tail
        self.fingerprint = fingerprint
        self.branch_path = branch_path
        self.last_contacted_at = last_contacted_at

    def as_dict(self):
        return {
            "channel": self.channel,
            "text": self.text,
            "country_code": self.country_code,
            "digit_count": self.digit_count,
            "visible_tail": self.visible_tail,
            "fingerprint": self.fingerprint,
            "branch_path": self.branch_path,
            "last_contacted_at": self.last_contacted_at,
        }

    def __eq__(self, other):
        return isinstance(other, MaskedDestination) and \
            self.as_dict() == other.as_dict()

    def __hash__(self):
        return hash(tuple(sorted(self.as_dict().items(), key=lambda i: i[0])))

    def __repr__(self):
        return "MaskedDestination(%r)" % (self.text,)


def mask_destination(
    channel, address, address_id=None, tenant_id=None, branch_path=None,
    last_contacted_at=None,
):
    """Withhold the destination and still say which one it is.

    Every field here answers the question "is this the person I meant?"
    without answering "what is their number":

    * the country calling code, because reaching the wrong country is the
      mistake with the largest bill attached;
    * the trailing digits, because that is what a person recognises;
    * the branch path, because two people who share trailing digits almost
      never share a department;
    * when they were last contacted, because that is what distinguishes a
      live record from a stale duplicate;
    * and the fingerprint, which distinguishes the remaining pairs that all
      four of the above cannot.
    """
    normalized = normalize_channel_address(channel, address)
    fingerprint = _fingerprint(tenant_id, address_id, normalized)
    stamp = _stamp(last_contacted_at)
    if channel == "email":
        masked = _mask_email(normalized)
        tail = normalized.rsplit(".", 1)[-1] if "." in normalized else None
        country_code, digits = None, None
    else:
        masked, country_code, tail, digits = _mask_telephone(normalized)
    return MaskedDestination(
        channel=channel,
        text=_compose(masked, fingerprint, branch_path, stamp),
        country_code=country_code,
        digit_count=digits,
        visible_tail=tail,
        fingerprint=fingerprint,
        branch_path=branch_path,
        last_contacted_at=stamp,
    )


def _compose(masked, fingerprint, branch_path, stamp):
    parts = [masked, fingerprint]
    if branch_path:
        parts.append(branch_path)
    parts.append("last contacted %s" % stamp if stamp else "never contacted")
    return " · ".join(part for part in parts if part)


def _fingerprint(tenant_id, address_id, normalized):
    # Falls back to the normalized address only when no identifier was
    # supplied, and then it is salted per tenant and truncated -- worse than
    # the identifier path, which is why the identifier path exists.
    material = "%s|%s" % (tenant_id or "", address_id or ("addr:" + normalized))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[
        :FINGERPRINT_LENGTH
    ]


def _stamp(moment):
    if moment is None:
        return None
    if hasattr(moment, "date"):
        # Day granularity. The hour somebody was last called is a behavioural
        # detail the preview has no use for.
        return moment.date().isoformat()
    return str(moment)[:10]


def calling_code(normalized):
    """The country calling code, or ``None`` where the prefix is unlisted."""
    digits = (normalized or "").lstrip("+")
    for table in (_CALLING_CODES_3, _CALLING_CODES_2, _CALLING_CODES_1):
        width = len(table[0])
        if digits[:width] in table:
            return digits[:width]
    return None


def _mask_telephone(normalized):
    digits = (normalized or "").lstrip("+")
    code = calling_code(normalized)
    rest = digits[len(code):] if code else digits
    # Never show the whole subscriber number, however short it is: at least
    # two digits stay hidden.
    keep = min(VISIBLE_TRAILING_DIGITS, max(0, len(rest) - 2))
    tail = rest[len(rest) - keep:] if keep else ""
    hidden = _bullets(len(rest) - keep)
    shown = " ".join(part for part in (hidden, tail) if part)
    prefix = ("+%s " % code) if code else ""
    return (prefix + shown).strip(), code, (tail or None), len(digits)


def _mask_email(normalized):
    local, _, domain = (normalized or "").partition("@")
    masked_local = (local[:1] + _glyphs(max(0, len(local) - 1))) or _glyphs(3)
    labels = domain.split(".") if domain else []
    if len(labels) > 1:
        masked_domain = ".".join(
            [label[:1] + _glyphs(max(0, len(label) - 1)) for label in labels[:-1]]
            + [labels[-1]]
        )
    else:
        masked_domain = _glyphs(3)
    return "%s@%s" % (masked_local, masked_domain)


def _glyphs(count):
    return MASK_GLYPH * count


def _bullets(count):
    """Hidden digits, grouped in threes, so the shape stays readable."""
    groups, remaining = [], count
    while remaining > 0:
        take = min(3, remaining)
        groups.append(MASK_GLYPH * take)
        remaining -= take
    return " ".join(groups)


# -- authority --------------------------------------------------------------

class BranchPermissionsRepository(object):
    """The four dimensions, granted on branches and resolved down subtrees.

    ``db`` is a :class:`libs.db.Database`. Reads bind ``app.current_org_id``
    on their own connection, the same habit `ContactsRepository` keeps and for
    the same reason: the policy and the predicate must be incapable of
    disagreeing about which account is asking.
    """

    def __init__(self, db, contacts=None):
        self.db = db
        self.contacts = contacts or ContactsRepository(db)

    # -- writing ----------------------------------------------------------

    def grant(
        self, tenant_id, branch_id, principal_id, dimension, actor,
        reason=None, permission_id=None,
    ):
        """Open one dimension on one branch, and everything under it."""
        return self._decide(
            tenant_id, branch_id, principal_id, dimension, "grant", actor,
            reason, permission_id,
        )

    def restrict(
        self, tenant_id, branch_id, principal_id, dimension, actor,
        reason=None, permission_id=None,
    ):
        """Close one dimension on one subtree, against any grant above it.

        This is R11's "unless an authorized administrator applies an explicit
        restriction", and the explicitness is the whole of it: nothing infers
        a restriction, and nothing but an administrator writes one.
        """
        return self._decide(
            tenant_id, branch_id, principal_id, dimension, "restrict", actor,
            reason, permission_id,
        )

    def revoke(self, tenant_id, branch_id, principal_id, dimension, actor):
        """Remove the decision at this branch. Inheritance resumes.

        Deleting rather than writing a third effect, because absence already
        has a meaning here -- inherit from above, and at a root, no -- and a
        'revoked' row would be a second spelling of it that resolution would
        have to keep agreeing with.
        """
        self._require_tenant(tenant_id)
        _require_dimension(dimension)
        self._require_administrator(actor)
        with self._write(tenant_id) as conn:
            removed = conn.execute(
                "delete from contacts.branch_permissions "
                "where tenant_id = %s and branch_id = %s "
                "and principal_id = %s and dimension = %s "
                "returning " + _PERMISSION_SELECT,
                (tenant_id, branch_id, principal_id, dimension),
            ).fetchall()
        return len(removed) > 0

    def _decide(
        self, tenant_id, branch_id, principal_id, dimension, effect, actor,
        reason, permission_id,
    ):
        self._require_tenant(tenant_id)
        _require_dimension(dimension)
        if effect not in EFFECTS:
            raise ValueError("unknown permission effect: %r" % (effect,))
        if not principal_id:
            raise ValueError("a permission needs a principal")
        self._require_administrator(actor)
        with self._write(tenant_id) as conn:
            # Checked rather than left to the foreign key so a permission over
            # another account's branch gets the same answer as one over a
            # branch that never existed. Row-level security has already
            # filtered this select to the bound account, so "another
            # account's" and "nobody's" are the same query result.
            known = conn.execute(
                "select branch_id from contacts.branches "
                "where tenant_id = %s and branch_id = %s",
                (tenant_id, branch_id),
            ).fetchone()
            if known is None:
                raise BranchNotFound()
            existing = conn.execute(
                "select " + _PERMISSION_SELECT
                + " from contacts.branch_permissions "
                "where tenant_id = %s and branch_id = %s "
                "and principal_id = %s and dimension = %s",
                (tenant_id, branch_id, principal_id, dimension),
            ).fetchone()
            if existing is not None:
                row = conn.execute(
                    "update contacts.branch_permissions set effect = %s, "
                    "decided_by_principal_id = %s, decided_by_authority = %s, "
                    "decided_by_actor_kind = %s, reason = %s, "
                    "updated_at = now() "
                    "where tenant_id = %s and permission_id = %s "
                    "returning " + _PERMISSION_SELECT,
                    (
                        effect, actor.principal_id, AUTHORITY_ADMINISTER,
                        actor.kind, reason, tenant_id,
                        existing["permission_id"],
                    ),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    insert into contacts.branch_permissions(
                        permission_id, tenant_id, branch_id, principal_id,
                        dimension, effect, decided_by_principal_id,
                        decided_by_authority, decided_by_actor_kind, reason
                    ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    returning """ + _PERMISSION_SELECT,
                    (
                        permission_id or "perm:%s" % generate_ulid(),
                        tenant_id,
                        branch_id,
                        principal_id,
                        dimension,
                        effect,
                        actor.principal_id,
                        AUTHORITY_ADMINISTER,
                        actor.kind,
                        reason,
                    ),
                ).fetchone()
        return _record(row, _PERMISSION_COLUMNS)

    # -- reading -----------------------------------------------------------

    def decisions_on_branch(self, tenant_id, branch_id):
        """The rows written *at* this branch. Not what it inherits."""
        self._require_tenant(tenant_id)
        with self._read(tenant_id) as conn:
            rows = conn.execute(
                "select " + _PERMISSION_SELECT
                + " from contacts.branch_permissions "
                "where tenant_id = %s and branch_id = %s "
                "order by dimension",
                (tenant_id, branch_id),
            ).fetchall()
        return [_record(row, _PERMISSION_COLUMNS) for row in rows]

    def effective(self, tenant_id, principal_id, branch_id):
        """The four answers for this principal on this branch.

        Resolved by walking the ancestry deepest-first and taking the first
        decision found per dimension, so a restriction on a subtree beats a
        grant on its parent by construction rather than by an ordering rule
        somebody has to remember.

        An identifier from another account resolves to no branch and therefore
        to four falses -- absence, not refusal, exactly as `get_contact` does.
        """
        self._require_tenant(tenant_id)
        if not principal_id:
            return {dimension: False for dimension in DIMENSIONS}
        chain = self._ancestry(tenant_id, branch_id)
        if not chain:
            return {dimension: False for dimension in DIMENSIONS}
        with self._read(tenant_id) as conn:
            rows = conn.execute(
                "select " + _PERMISSION_SELECT
                + " from contacts.branch_permissions "
                "where tenant_id = %s and principal_id = %s "
                "and branch_id = any(%s)",
                (
                    tenant_id, principal_id,
                    [branch["branch_id"] for branch in chain],
                ),
            ).fetchall()
        by_branch = {}
        for row in rows:
            by_branch.setdefault(row["branch_id"], {})[row["dimension"]] = \
                row["effect"]
        effective = {}
        for dimension in DIMENSIONS:
            effective[dimension] = False
            for branch in reversed(chain):
                effect = by_branch.get(branch["branch_id"], {}).get(dimension)
                if effect is not None:
                    effective[dimension] = effect == "grant"
                    break
        return effective

    def holds(self, tenant_id, principal_id, branch_id, dimension):
        _require_dimension(dimension)
        return self.effective(tenant_id, principal_id, branch_id)[dimension]

    def require(self, tenant_id, principal_id, branch_id, dimension):
        """Raise unless the principal holds this dimension here."""
        if not self.holds(tenant_id, principal_id, branch_id, dimension):
            raise PermissionDenied(dimension)
        return True

    def authorized_branches(self, tenant_id, principal_id, dimension):
        """Every branch where this principal effectively holds ``dimension``.

        Returned already expanded, which is why callers must never expand it
        again: re-expanding a permitted set to subtrees would quietly restore
        the descendants an explicit restriction removed.
        """
        self._require_tenant(tenant_id)
        _require_dimension(dimension)
        if not principal_id:
            return []
        with self._read(tenant_id) as conn:
            rows = conn.execute(
                "select " + _PERMISSION_SELECT
                + " from contacts.branch_permissions "
                "where tenant_id = %s and principal_id = %s "
                "and dimension = %s",
                (tenant_id, principal_id, dimension),
            ).fetchall()
        if not rows:
            return []
        decisions, candidates = {}, {}
        for row in rows:
            try:
                subtree = self.contacts.subtree(tenant_id, row["branch_id"])
            except LookupError:
                continue
            decisions[subtree[0]["path"]] = row["effect"]
            for branch in subtree:
                candidates[branch["branch_id"]] = branch["path"]
        allowed = []
        for branch_id, path in candidates.items():
            nearest = _nearest_decision(path, decisions)
            if nearest == "grant":
                allowed.append(branch_id)
        return sorted(allowed)

    # -- internals ---------------------------------------------------------

    def _ancestry(self, tenant_id, branch_id):
        branch = self.contacts.get_branch(tenant_id, branch_id)
        if branch is None:
            return []
        return self.contacts.ancestors(tenant_id, branch_id) + [branch]

    @staticmethod
    def _require_tenant(tenant_id):
        if not tenant_id or not isinstance(tenant_id, str):
            raise TenantScopeRequired()
        return tenant_id

    @staticmethod
    def _require_administrator(actor):
        """R12 and R11 in one gate, in that order.

        Human first, because an agent holding every authority in the set is
        still not a decider, and the message an agent should get says so.
        """
        if actor is None or actor.kind != "human":
            raise HumanDecisionRequired(
                "a permission change requires a human decision"
            )
        if not actor.holds(AUTHORITY_ADMINISTER):
            raise AdministratorRequired(
                "granting or restricting authority requires an administrator"
            )
        return actor

    def _read(self, tenant_id):
        return _BoundConnection(self.db, tenant_id, write=False)

    def _write(self, tenant_id):
        return _BoundConnection(self.db, tenant_id, write=True)


def _nearest_decision(path, decisions):
    """The decision on the longest ancestor path, restriction winning ties."""
    best, best_length = None, -1
    for decision_path, effect in decisions.items():
        if path == decision_path or path.startswith(decision_path + "/"):
            length = len(decision_path)
            if length > best_length or (
                length == best_length and effect == "restrict"
            ):
                best, best_length = effect, length
    return best


# -- the directory as one principal may see it ------------------------------

class ContactsAccess(object):
    """Lists, tags, segments, and the audience preview, bounded by authority.

    Every resolution here starts from `authorized_branches`, so a grouping is
    a way of naming people the principal may already reach and never a way
    around the tree. That is enforced by the signatures underneath: the
    repository's resolution methods take an explicit set of branch
    identifiers with no default, so forgetting to bound a query is a
    ``TypeError`` rather than a disclosure.
    """

    def __init__(self, db, contacts=None, permissions=None, consent=None):
        self.db = db
        self.contacts = contacts or ContactsRepository(db)
        self.permissions = permissions or BranchPermissionsRepository(
            db, contacts=self.contacts,
        )
        #: A `ContactsConsentRepository`, optional. Without it the preview
        #: still counts and still masks; it simply has no eligibility axis to
        #: report, and says so by leaving the histogram empty.
        self.consent = consent

    # -- scoped reads ------------------------------------------------------

    def visible_branch_ids(self, tenant_id, principal_id):
        return self.permissions.authorized_branches(
            tenant_id, principal_id, DIMENSION_VIEW,
        )

    def targetable_branch_ids(self, tenant_id, principal_id):
        return self.permissions.authorized_branches(
            tenant_id, principal_id, DIMENSION_CAMPAIGN_USE,
        )

    def search(self, tenant_id, principal_id, query, limit=200):
        """Search, bounded to what this principal may view.

        Silently bounded. A principal who searches a common surname is told
        about the matches in their own branches and nothing about whether
        there are others, because "3 results you may not see" is itself the
        disclosure.
        """
        visible = self.visible_branch_ids(tenant_id, principal_id)
        if not visible:
            return []
        return self.contacts.search_contacts(
            tenant_id, query, branch_ids=visible, limit=limit,
            expand_subtrees=False,
        )

    def list_members(self, tenant_id, principal_id, list_id):
        """The canonical records in a list, minus any the principal may not see."""
        return self.contacts.list_members(
            tenant_id, list_id,
            self.visible_branch_ids(tenant_id, principal_id),
        )

    def tagged_contacts(self, tenant_id, principal_id, tag_id):
        return self.contacts.tagged_contacts(
            tenant_id, tag_id,
            self.visible_branch_ids(tenant_id, principal_id),
        )

    def resolve_segment(self, tenant_id, principal_id, segment_id):
        return self.contacts.resolve_segment(
            tenant_id, segment_id,
            self.visible_branch_ids(tenant_id, principal_id),
        )

    # -- the redacted audience projection ----------------------------------

    def audience_preview(
        self, tenant_id, principal_id, channel, purpose, branch_id=None,
        list_id=None, segment_id=None, now=None, limit=500,
    ):
        """Review an audience without being able to read it.

        R15 says an operator fixes and authorises the audience before a
        campaign may run without per-effect approval, and R11 says campaign-use
        is grantable without view. Both hold only if there is a shape of the
        audience that carries no names: counts, why people fell out, and
        destinations masked well enough to tell apart (R14).

        Names appear per entry, and only where this principal separately holds
        view over that contact's branch -- so an operator who holds both sees
        a useful preview, and one who holds only campaign-use sees the same
        counts and the same exclusions with the identities absent rather than
        the rows absent.
        """
        targetable = self.targetable_branch_ids(tenant_id, principal_id)
        if branch_id is not None and branch_id not in targetable:
            # Named on purpose, refused on purpose. An empty audience here
            # would read as "the rule matched nobody".
            raise PermissionDenied(DIMENSION_CAMPAIGN_USE)
        if not targetable:
            raise PermissionDenied(DIMENSION_CAMPAIGN_USE)
        viewable = set(self.visible_branch_ids(tenant_id, principal_id))
        members = self._audience_members(
            tenant_id, targetable, branch_id, list_id, segment_id, limit,
        )
        branches, entries, reasons = {}, [], {}
        eligible = 0
        for contact in members:
            branch = branches.get(contact["primary_branch_id"])
            if branch is None:
                branch = self.contacts.get_branch(
                    tenant_id, contact["primary_branch_id"],
                ) or {}
                branches[contact["primary_branch_id"]] = branch
            address = self._destination(tenant_id, contact, channel)
            reason = self._exclusion_reason(
                tenant_id, address, channel, purpose, now,
            )
            entry = {
                "contact_id": contact["contact_id"],
                "branch_path": branch.get("path"),
                "excluded_reason": reason,
                "destination": None if address is None else mask_destination(
                    channel,
                    address["address"],
                    address_id=address["address_id"],
                    tenant_id=tenant_id,
                    branch_path=branch.get("path"),
                    last_contacted_at=address.get("last_contacted_at"),
                ).as_dict(),
            }
            if contact["primary_branch_id"] in viewable:
                entry["display_name"] = contact["display_name"]
            else:
                # Not null-and-present: absent. A key that is sometimes a name
                # and sometimes None invites a renderer to print "None" where
                # a name would go, and invites a reader to believe the field
                # was empty rather than withheld.
                entry["redacted"] = True
            if reason is None:
                eligible += 1
            else:
                reasons[reason] = reasons.get(reason, 0) + 1
            entries.append(entry)
        return {
            "total": len(entries),
            "eligible": eligible,
            "excluded": len(entries) - eligible,
            "exclusion_reasons": reasons,
            "entries": entries,
            "channel": channel,
            "purpose": purpose,
            # True when at least one entry is withheld, so a surface can say
            # "you are seeing a redacted audience" without recomputing it.
            "redacted": any("display_name" not in entry for entry in entries),
        }

    def _audience_members(
        self, tenant_id, targetable, branch_id, list_id, segment_id, limit,
    ):
        named = [
            value for value in (branch_id, list_id, segment_id)
            if value is not None
        ]
        if len(named) != 1:
            raise ValueError(
                "an audience is exactly one of a branch, a list, or a segment"
            )
        if list_id is not None:
            return self.contacts.list_members(tenant_id, list_id, targetable)
        if segment_id is not None:
            return self.contacts.resolve_segment(
                tenant_id, segment_id, targetable,
            )
        # A branch audience means the subtree, intersected with what may be
        # targeted -- so a restriction inside the subtree removes those people
        # from the campaign rather than merely from the operator's view.
        try:
            subtree = self.contacts.subtree(tenant_id, branch_id)
        except LookupError:
            return []
        permitted = set(targetable)
        scoped = [
            branch["branch_id"] for branch in subtree
            if branch["branch_id"] in permitted
        ]
        if not scoped:
            return []
        return self.contacts.search_contacts(
            tenant_id, "", branch_ids=scoped, limit=limit,
            expand_subtrees=False,
        )

    def _destination(self, tenant_id, contact, channel):
        addresses = [
            address for address
            in self.contacts.addresses(tenant_id, contact["contact_id"])
            if address["channel"] == channel
        ]
        if not addresses:
            return None
        for address in addresses:
            if address.get("is_primary"):
                return address
        return addresses[0]

    def _exclusion_reason(self, tenant_id, address, channel, purpose, now):
        if address is None:
            return "no_address"
        if self.consent is None:
            return None
        decision = self.consent.evaluate_eligibility(
            tenant_id, address["address_id"], channel, purpose, now=now,
        )
        return None if decision.eligible else decision.reason


class _BoundConnection(object):
    """`app.current_org_id` bound from the same argument the predicate uses."""

    def __init__(self, db, tenant_id, write):
        self.db = db
        self.tenant_id = tenant_id
        self._context = db.transaction() if write else db.connection()

    def __enter__(self):
        conn = self._context.__enter__()
        self._connection = conn
        self._previous_row_factory = getattr(conn, "row_factory", None)
        if self._previous_row_factory is not None:
            conn.row_factory = dict_row
        self.db.set_org_context(conn, self.tenant_id)
        return conn

    def __exit__(self, *exc_info):
        if self._previous_row_factory is not None:
            self._connection.row_factory = self._previous_row_factory
        return self._context.__exit__(*exc_info)


def _require_dimension(dimension):
    if dimension not in DIMENSIONS:
        raise ValueError("unknown permission dimension: %r" % (dimension,))
    return dimension


def _record(row, columns):
    if row is None:
        return None
    if isinstance(row, dict):
        return {name: row.get(name) for name in columns}
    return dict(zip(columns, row))
