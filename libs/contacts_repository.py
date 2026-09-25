"""The tenant-bound way in to the contacts directory.

Nothing else reads `contacts.*`. The orchestrator does not join against it,
the planner does not query it, and no capability touches it except through
here (KTD11). That is not a layering preference: a join written somewhere
else is a predicate written somewhere else, and this is the one table set
where a missing predicate is a disclosure of somebody's phone number rather
than a wrong row count.

Three habits make that hold, and each one is here because dropping it would
be silent:

**A tenant is an argument, never a default.** Every method takes one first
and refuses without it. A `None` tenant does not mean "all tenants" and does
not mean "the local one" -- it means the caller lost track, and the call
stops there rather than at whatever `tenant_id = null` happens to match.

**The org context is bound on every connection this module opens.** Not once
per request somewhere upstream, where a keep-alive thread can carry the last
request's value into the next one. Bound here, from the same argument the
predicate uses, so the row-level-security policy and the `where` clause can
never disagree about which account is asking.

**A foreign identifier is absence, not refusal.** `get_contact` on another
account's contact id returns `None`, exactly as it would for an id that never
existed. A 403 would confirm the row is real, which is most of what an
attacker enumerating identifiers wants to know.
"""

import hashlib
import json
import re

from psycopg.rows import dict_row

from libs.tenancy import TenantScopeRequired
from libs.ulid import generate_ulid


__all__ = [
    "ContactsRepository",
    "TenantScopeRequired",
    "BranchNotFound",
    "ContactNotFound",
    "CyclicBranchMove",
    "GroupingNotFound",
    "InvalidBranchPlacement",
    "SegmentRuleInvalid",
    "SEGMENT_RULE_TERMS",
    "EDITABLE_CONTACT_FIELDS",
    "normalize_channel_address",
    "rule_hash",
    "slugify",
    "validate_segment_rule",
]


#: Where a branch may sit. An organization is a root, a department hangs off
#: an organization, and a folder nests inside anything -- which is what "and
#: freely nested subfolders" means in R8. The database holds the same rules as
#: check constraints; these are here so the caller gets a sentence instead of
#: a constraint name.
BRANCH_KINDS = ("organization", "department", "folder")

CHANNELS = ("sms", "whatsapp", "voice", "email")

CONTACT_STATUSES = ("active", "archived", "merged")

#: Identity fields a human correcting a record may write. `status`,
#: `primary_branch_id`, `merged_into_contact_id` and `source` are absent
#: deliberately: relocating a record is `move_contact`, and the other three are
#: lifecycle facts a form has no business overwriting. Destinations, consent
#: and permissions are absent for a stronger reason -- each has its own ledger
#: and its own authority gate (R12), and an edit path that could reach them
#: would be a second, quieter way to grant something.
EDITABLE_CONTACT_FIELDS = (
    "display_name", "given_name", "family_name", "locale", "timezone",
    "company_name", "job_title", "external_reference",
)

_BRANCH_COLUMNS = (
    "branch_id", "tenant_id", "parent_branch_id", "parent_kind", "kind",
    "name", "slug", "path", "depth", "owner_principal_id",
)

_CONTACT_COLUMNS = (
    "contact_id", "tenant_id", "primary_branch_id", "display_name",
    "given_name", "family_name", "locale", "timezone", "company_name",
    "job_title", "status", "merged_into_contact_id", "external_reference",
    "source",
)

_ADDRESS_COLUMNS = (
    "address_id", "tenant_id", "contact_id", "channel", "address",
    "address_normalized", "label", "is_primary", "verified_at",
    # When this destination was last reached. Read by the masked preview
    # (R14), where "last contacted in March" is often the only thing telling
    # a live record apart from a stale duplicate of the same person.
    "last_contacted_at",
)

_LIST_COLUMNS = (
    "list_id", "tenant_id", "branch_id", "name", "slug", "description",
    "created_by_principal_id",
)

_MEMBER_COLUMNS = (
    "tenant_id", "list_id", "contact_id", "added_by_principal_id",
)

_TAG_COLUMNS = (
    "tag_id", "tenant_id", "name", "slug", "created_by_principal_id",
)

_TAG_ASSIGNMENT_COLUMNS = (
    "tenant_id", "tag_id", "contact_id", "assigned_by_principal_id",
)

_SEGMENT_COLUMNS = (
    "segment_id", "tenant_id", "scope_branch_id", "name", "slug",
    "definition", "rule_hash", "created_by_principal_id",
)

_BRANCH_SELECT = ", ".join(_BRANCH_COLUMNS)
_CONTACT_SELECT = ", ".join(_CONTACT_COLUMNS)
_ADDRESS_SELECT = ", ".join(_ADDRESS_COLUMNS)
_LIST_SELECT = ", ".join(_LIST_COLUMNS)
_MEMBER_SELECT = ", ".join(_MEMBER_COLUMNS)
_TAG_SELECT = ", ".join(_TAG_COLUMNS)
_TAG_ASSIGNMENT_SELECT = ", ".join(_TAG_ASSIGNMENT_COLUMNS)
_SEGMENT_SELECT = ", ".join(_SEGMENT_COLUMNS)

#: Every term a stored segment rule may use. Closed on purpose: a rule
#: carrying a term this evaluator does not implement is refused rather than
#: partially applied, because the partial application of "in Spain and opted
#: in" is "everybody", and a silently wider audience is the one failure a
#: campaign preview cannot show you.
SEGMENT_RULE_TERMS = (
    "branch_id", "include_subtree", "name_contains", "status", "locale",
    "has_channel", "tag_slugs",
)

#: A tree deeper than this is a loop somebody has not noticed yet. The
#: database trigger uses the same bound.
MAX_BRANCH_DEPTH = 128


class BranchNotFound(LookupError):
    """No branch by that identifier in this account.

    Deliberately the same answer for "does not exist" and "belongs to someone
    else", and the message carries no identifier, so neither the response nor
    the log distinguishes them.
    """

    def __init__(self, message="branch not found"):
        super(BranchNotFound, self).__init__(message)


class ContactNotFound(LookupError):
    """No contact by that identifier in this account. See `BranchNotFound`."""

    def __init__(self, message="contact not found"):
        super(ContactNotFound, self).__init__(message)


class CyclicBranchMove(ValueError):
    """A move that would put a branch inside its own subtree.

    The damage is not a crash. The subtree keeps its rows and loses every
    path to a root, so it is readable by identifier and invisible to
    navigation, search, and any permission granted over a parent -- which
    means it also stops being covered by whoever was supposed to see it.
    """

    def __init__(self, message="move would create cyclic branch ancestry"):
        super(CyclicBranchMove, self).__init__(message)


class InvalidBranchPlacement(ValueError):
    """A parent whose kind cannot hold this kind of child."""


class GroupingNotFound(LookupError):
    """No list, tag, or segment by that identifier in this account.

    One error for all three, and the same answer for "belongs to another
    account", for the reason `BranchNotFound` gives.
    """

    def __init__(self, message="grouping not found"):
        super(GroupingNotFound, self).__init__(message)


class SegmentRuleInvalid(ValueError):
    """A stored rule carrying a term the evaluator does not implement."""


def rule_hash(definition):
    """A stable fingerprint of a segment rule.

    Bound into a campaign envelope alongside its cohort snapshot (KTD7), so
    "the audience rule changed after you authorised it" is a comparison rather
    than an argument. Sorted keys and separatorless JSON, so re-serialising
    the same rule cannot produce a different hash.
    """
    return hashlib.sha256(_canonical_rule(definition).encode("utf-8")).hexdigest()


def _canonical_rule(definition):
    return json.dumps(definition or {}, sort_keys=True, separators=(",", ":"))


def record_version(contact, addresses):
    """A content fingerprint standing in for a version column.

    ``contacts.contacts`` carries no version, so this is derived from the
    record itself: every stored field of the canonical record, plus the
    identity and shape of its addresses. Any edit to either changes it, which
    is what lets an approval discover that the record it was bound to is no
    longer the record in front of it.

    Consent, suppression and usability are deliberately absent. Those change
    lawfully between resolution and dispatch (KTD3), and folding them in would
    make an ordinary consent expiry indistinguishable from somebody editing
    the record behind a pending approval.
    """
    payload = {
        "contact": {
            key: contact.get(key) for key in sorted(contact or {})
            if key != "tenant_id"
        },
        "addresses": sorted(
            [
                address.get("address_id"),
                address.get("channel"),
                address.get("address_normalized"),
                address.get("label"),
                bool(address.get("is_primary")),
            ]
            for address in (addresses or ())
        ),
    }
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def slugify(value):
    """A path segment: lowercase, ASCII-ish, one hyphen between words."""
    text = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower())
    return text.strip("-") or "branch"


def normalize_channel_address(channel, address):
    """The form uniqueness and lookup run on.

    '+1 809 555-0100' and '+18095550100' are one phone number, and
    'Ana@Example.com' and 'ana@example.com' are one mailbox. Storing only the
    normalized form would lose how the account wrote it, which matters when a
    human is checking whether the right person is about to be messaged, so
    both are kept and only this one is indexed.
    """
    text = (address or "").strip()
    if channel == "email":
        return text.lower()
    kept = "".join(
        character for character in text
        if character.isdigit() or character == "+"
    )
    return kept


class ContactsRepository(object):
    """Postgres-backed contacts, bound to one account per call.

    ``db`` is a :class:`libs.db.Database`: it supplies ``connection()``,
    ``transaction()``, and ``set_org_context()``.
    """

    def __init__(self, db):
        self.db = db

    # -- tenant binding ----------------------------------------------------

    @staticmethod
    def _require_tenant(tenant_id):
        if not tenant_id or not isinstance(tenant_id, str):
            raise TenantScopeRequired()
        return tenant_id

    def _read(self, tenant_id):
        return _BoundConnection(self.db, tenant_id, write=False)

    def _write(self, tenant_id):
        return _BoundConnection(self.db, tenant_id, write=True)

    # -- hierarchy ---------------------------------------------------------

    def create_branch(
        self, tenant_id, name, kind="folder", parent_branch_id=None,
        slug=None, branch_id=None, owner_principal_id=None,
    ):
        """Add one node to this account's tree."""
        self._require_tenant(tenant_id)
        if kind not in BRANCH_KINDS:
            raise InvalidBranchPlacement("unknown branch kind: %r" % (kind,))
        segment = slugify(slug or name)
        with self._write(tenant_id) as conn:
            parent = None
            if parent_branch_id is not None:
                parent = self._fetch_branch(conn, tenant_id, parent_branch_id)
                if parent is None:
                    raise BranchNotFound()
            _check_placement(kind, parent)
            path = ("%s/%s" % (parent["path"], segment)) if parent else (
                "/%s" % segment
            )
            depth = (parent["depth"] + 1) if parent else 0
            if depth >= MAX_BRANCH_DEPTH:
                raise InvalidBranchPlacement(
                    "branch nesting exceeds the supported depth"
                )
            row = conn.execute(
                """
                insert into contacts.branches(
                    branch_id, tenant_id, parent_branch_id, parent_kind, kind,
                    name, slug, path, depth, owner_principal_id
                ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                returning """ + _BRANCH_SELECT,
                (
                    branch_id or "branch:%s" % generate_ulid(),
                    tenant_id,
                    parent["branch_id"] if parent else None,
                    parent["kind"] if parent else None,
                    kind,
                    name,
                    segment,
                    path,
                    depth,
                    owner_principal_id if parent is None else parent.get(
                        "owner_principal_id"
                    ),
                ),
            ).fetchone()
        return _record(row, _BRANCH_COLUMNS)

    def get_branch(self, tenant_id, branch_id):
        """The branch, or ``None`` -- including when it is someone else's."""
        self._require_tenant(tenant_id)
        with self._read(tenant_id) as conn:
            row = self._fetch_branch(conn, tenant_id, branch_id)
        return _record(row, _BRANCH_COLUMNS)

    def branch_at_path(self, tenant_id, path):
        """Navigate straight to '/acme/sales/emea' in one lookup."""
        self._require_tenant(tenant_id)
        with self._read(tenant_id) as conn:
            row = conn.execute(
                "select " + _BRANCH_SELECT + " from contacts.branches "
                "where tenant_id = %s and path = %s",
                (tenant_id, normalize_path(path)),
            ).fetchone()
        return _record(row, _BRANCH_COLUMNS)

    def children(self, tenant_id, branch_id=None):
        """Direct children, or the roots when ``branch_id`` is ``None``."""
        self._require_tenant(tenant_id)
        with self._read(tenant_id) as conn:
            if branch_id is None:
                rows = conn.execute(
                    "select " + _BRANCH_SELECT + " from contacts.branches "
                    "where tenant_id = %s and parent_branch_id is null "
                    "order by slug",
                    (tenant_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "select " + _BRANCH_SELECT + " from contacts.branches "
                    "where tenant_id = %s and parent_branch_id = %s "
                    "order by slug",
                    (tenant_id, branch_id),
                ).fetchall()
        return [_record(row, _BRANCH_COLUMNS) for row in rows]

    def ancestors(self, tenant_id, branch_id):
        """Root-first ancestry, for breadcrumbs and permission checks."""
        self._require_tenant(tenant_id)
        with self._read(tenant_id) as conn:
            branch = self._fetch_branch(conn, tenant_id, branch_id)
            if branch is None:
                raise BranchNotFound()
            chain, seen = [], set()
            parent_id = branch.get("parent_branch_id")
            while parent_id is not None and parent_id not in seen:
                seen.add(parent_id)
                parent = self._fetch_branch(conn, tenant_id, parent_id)
                if parent is None:
                    break
                chain.append(_record(parent, _BRANCH_COLUMNS))
                parent_id = parent.get("parent_branch_id")
        chain.reverse()
        return chain

    def subtree(self, tenant_id, branch_id):
        """The branch and everything under it, as a prefix scan on ``path``."""
        self._require_tenant(tenant_id)
        with self._read(tenant_id) as conn:
            branch = self._fetch_branch(conn, tenant_id, branch_id)
            if branch is None:
                raise BranchNotFound()
            rows = self._fetch_descendants(conn, tenant_id, branch["path"])
        return [_record(branch, _BRANCH_COLUMNS)] + [
            _record(row, _BRANCH_COLUMNS) for row in rows
        ]

    def move_branch(self, tenant_id, branch_id, new_parent_branch_id):
        """Reparent a branch and carry its whole subtree's paths with it.

        Refused when the new parent is the branch itself or sits inside its
        subtree. The database refuses it too; this refusal exists so the
        caller gets a named error before a transaction is opened, and so the
        descendant path rewrite below is never attempted against a tree that
        has no root.
        """
        self._require_tenant(tenant_id)
        with self._write(tenant_id) as conn:
            branch = self._fetch_branch(conn, tenant_id, branch_id)
            if branch is None:
                raise BranchNotFound()
            parent = None
            if new_parent_branch_id is not None:
                parent = self._fetch_branch(
                    conn, tenant_id, new_parent_branch_id,
                )
                if parent is None:
                    # Another account's branch lands here, and gets the same
                    # answer as an identifier nobody ever minted.
                    raise BranchNotFound()
                if parent["branch_id"] == branch["branch_id"] or _within(
                    parent["path"], branch["path"]
                ):
                    raise CyclicBranchMove()
            _check_placement(branch["kind"], parent)
            old_path = branch["path"]
            new_path = ("%s/%s" % (parent["path"], branch["slug"])) if parent \
                else ("/%s" % branch["slug"])
            new_depth = (parent["depth"] + 1) if parent else 0
            descendants = self._fetch_descendants(conn, tenant_id, old_path)
            if new_depth + _deepest(descendants, branch["depth"]) >= \
                    MAX_BRANCH_DEPTH:
                raise InvalidBranchPlacement(
                    "branch nesting exceeds the supported depth"
                )
            moved = conn.execute(
                "update contacts.branches set parent_branch_id = %s, "
                "parent_kind = %s, path = %s, depth = %s, updated_at = now() "
                "where tenant_id = %s and branch_id = %s "
                "returning " + _BRANCH_SELECT,
                (
                    parent["branch_id"] if parent else None,
                    parent["kind"] if parent else None,
                    new_path,
                    new_depth,
                    tenant_id,
                    branch["branch_id"],
                ),
            ).fetchone()
            if moved is None:
                raise BranchNotFound()
            for row in descendants:
                conn.execute(
                    "update contacts.branches set path = %s, depth = %s, "
                    "updated_at = now() "
                    "where tenant_id = %s and branch_id = %s "
                    "returning " + _BRANCH_SELECT,
                    (
                        new_path + row["path"][len(old_path):],
                        row["depth"] - branch["depth"] + new_depth,
                        tenant_id,
                        row["branch_id"],
                    ),
                )
        return _record(moved, _BRANCH_COLUMNS)

    # -- the canonical record ---------------------------------------------

    def create_contact(
        self, tenant_id, primary_branch_id, display_name, given_name=None,
        family_name=None, locale=None, timezone=None, company_name=None,
        job_title=None, external_reference=None, source="manual",
        contact_id=None,
    ):
        """One record for one person, in exactly one place in the tree.

        The branch is not pre-checked. `(primary_branch_id, tenant_id)` is a
        composite foreign key, so a branch belonging to another account does
        not resolve and the insert is refused by the database -- which is a
        stronger guarantee than a `select` this method could have run first
        and a future edit could have dropped.
        """
        self._require_tenant(tenant_id)
        with self._write(tenant_id) as conn:
            row = conn.execute(
                """
                insert into contacts.contacts(
                    contact_id, tenant_id, primary_branch_id, display_name,
                    given_name, family_name, locale, timezone, company_name,
                    job_title, status, external_reference, source
                ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                returning """ + _CONTACT_SELECT,
                (
                    contact_id or "contact:%s" % generate_ulid(),
                    tenant_id,
                    primary_branch_id,
                    display_name,
                    given_name,
                    family_name,
                    locale,
                    timezone,
                    company_name,
                    job_title,
                    "active",
                    external_reference,
                    source,
                ),
            ).fetchone()
        return _record(row, _CONTACT_COLUMNS)

    def get_contact(self, tenant_id, contact_id):
        self._require_tenant(tenant_id)
        with self._read(tenant_id) as conn:
            row = conn.execute(
                "select " + _CONTACT_SELECT + " from contacts.contacts "
                "where tenant_id = %s and contact_id = %s",
                (tenant_id, contact_id),
            ).fetchone()
        return _record(row, _CONTACT_COLUMNS)

    def move_contact(self, tenant_id, contact_id, primary_branch_id):
        """Relocate the one primary placement. There is never a second one."""
        self._require_tenant(tenant_id)
        with self._write(tenant_id) as conn:
            row = conn.execute(
                "update contacts.contacts set primary_branch_id = %s, "
                "updated_at = now() "
                "where tenant_id = %s and contact_id = %s "
                "returning " + _CONTACT_SELECT,
                (primary_branch_id, tenant_id, contact_id),
            ).fetchone()
        if row is None:
            raise ContactNotFound()
        return _record(row, _CONTACT_COLUMNS)

    def update_contact(self, tenant_id, contact_id, changes):
        """Correct the identity fields of one canonical record.

        Bounded to `EDITABLE_CONTACT_FIELDS`, and an unknown field is refused
        by name rather than dropped. A silent drop is the failure mode that
        matters here: a caller that thought it was writing consent, a
        destination or a branch would be told nothing, and the record would
        read as if the change had been considered and declined.
        """
        self._require_tenant(tenant_id)
        unknown = sorted(set(changes or {}) - set(EDITABLE_CONTACT_FIELDS))
        if unknown:
            raise ValueError(
                "not an editable contact field: %s" % ", ".join(unknown)
            )
        columns = [name for name in EDITABLE_CONTACT_FIELDS if name in changes]
        if not columns:
            raise ValueError("an edit needs at least one field")
        assignments = ", ".join("%s = %%s" % name for name in columns)
        with self._write(tenant_id) as conn:
            row = conn.execute(
                "update contacts.contacts set " + assignments
                + ", updated_at = now() "
                "where tenant_id = %s and contact_id = %s "
                "returning " + _CONTACT_SELECT,
                tuple([changes[name] for name in columns])
                + (tenant_id, contact_id),
            ).fetchone()
        if row is None:
            raise ContactNotFound()
        return _record(row, _CONTACT_COLUMNS)

    def contacts_in_branch(self, tenant_id, branch_id):
        self._require_tenant(tenant_id)
        with self._read(tenant_id) as conn:
            rows = conn.execute(
                "select " + _CONTACT_SELECT + " from contacts.contacts "
                "where tenant_id = %s and primary_branch_id = %s "
                "and status = %s "
                "order by display_name",
                (tenant_id, branch_id, "active"),
            ).fetchall()
        return [_record(row, _CONTACT_COLUMNS) for row in rows]

    def search_contacts(
        self, tenant_id, query, branch_ids=None, status="active", limit=200,
        expand_subtrees=True,
    ):
        """Search the whole account, or only inside the branches named.

        ``branch_ids`` is expanded to full subtrees, and any identifier that
        does not resolve inside this account is dropped rather than refused:
        a caller assembling the list from a permission set should not be able
        to learn which of its guesses were real.

        ``expand_subtrees=False`` takes the identifiers literally, and is what
        a permission-bounded caller must use. A resolved permission set has
        already had explicit restrictions removed from it (U7), and expanding
        it again would walk straight back down into the subtree the
        restriction closed -- turning a bounded search into a full one, with
        the bound still visible in the call site.
        """
        self._require_tenant(tenant_id)
        pattern = "%%%s%%" % (query or "").strip().lower()
        with self._read(tenant_id) as conn:
            scoped = None
            if branch_ids is not None:
                scoped = self._expand_branches(
                    conn, tenant_id, branch_ids, expand_subtrees,
                )
                if not scoped:
                    return []
            sql = (
                "select " + _CONTACT_SELECT + " from contacts.contacts "
                "where tenant_id = %s and status = %s "
                "and lower(display_name) like %s"
            )
            params = [tenant_id, status, pattern]
            if scoped is not None:
                sql += " and primary_branch_id = any(%s)"
                params.append(scoped)
            sql += " order by display_name"
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [_record(row, _CONTACT_COLUMNS) for row in rows[:limit]]

    # -- addresses ---------------------------------------------------------

    def add_address(
        self, tenant_id, contact_id, channel, address, label=None,
        is_primary=False, verified_at=None, address_id=None,
    ):
        """Attach one reachable address to a person.

        A row rather than a column, because consent belongs to the address:
        one person can hold a work mobile they opted into and a personal one
        they did not, and a column would force those two facts to share an
        answer.
        """
        self._require_tenant(tenant_id)
        if channel not in CHANNELS:
            raise ValueError("unsupported channel: %r" % (channel,))
        normalized = normalize_channel_address(channel, address)
        if not normalized:
            raise ValueError("address is empty")
        with self._write(tenant_id) as conn:
            if is_primary:
                # The database allows exactly one primary per contact and
                # channel, so the previous one steps down first.
                conn.execute(
                    "update contacts.contact_addresses set is_primary = %s, "
                    "updated_at = now() "
                    "where tenant_id = %s and contact_id = %s "
                    "and channel = %s and is_primary = %s "
                    "returning " + _ADDRESS_SELECT,
                    (False, tenant_id, contact_id, channel, True),
                )
            row = conn.execute(
                """
                insert into contacts.contact_addresses(
                    address_id, tenant_id, contact_id, channel, address,
                    address_normalized, label, is_primary, verified_at
                ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                returning """ + _ADDRESS_SELECT,
                (
                    address_id or "address:%s" % generate_ulid(),
                    tenant_id,
                    contact_id,
                    channel,
                    (address or "").strip(),
                    normalized,
                    label,
                    bool(is_primary),
                    verified_at,
                ),
            ).fetchone()
        return _record(row, _ADDRESS_COLUMNS)

    def addresses(self, tenant_id, contact_id):
        self._require_tenant(tenant_id)
        with self._read(tenant_id) as conn:
            rows = conn.execute(
                "select " + _ADDRESS_SELECT
                + " from contacts.contact_addresses "
                "where tenant_id = %s and contact_id = %s "
                "order by channel, address_normalized",
                (tenant_id, contact_id),
            ).fetchall()
        return [_record(row, _ADDRESS_COLUMNS) for row in rows]

    def get_address(self, tenant_id, address_id):
        """One address by identifier, in this account and only this account.

        Read by the review queue, which is handed an address identifier and
        has to know which channel it is on before it can say anything about
        consent. Returns ``None`` rather than raising for a row in another
        account, for the same reason the rest of this repository does: a
        distinguishable refusal confirms the row exists.
        """
        self._require_tenant(tenant_id)
        with self._read(tenant_id) as conn:
            row = conn.execute(
                "select " + _ADDRESS_SELECT
                + " from contacts.contact_addresses "
                "where tenant_id = %s and address_id = %s",
                (tenant_id, address_id),
            ).fetchone()
        return _record(row, _ADDRESS_COLUMNS)

    def contact_by_address(self, tenant_id, channel, address):
        """Who this number reaches, in this account and only this account.

        Two accounts holding the same number is ordinary, and each resolves
        to its own canonical person. Within one account the answer is single
        because `(tenant_id, channel, address_normalized)` is unique.
        """
        self._require_tenant(tenant_id)
        normalized = normalize_channel_address(channel, address)
        if not normalized:
            return None
        with self._read(tenant_id) as conn:
            found = conn.execute(
                "select " + _ADDRESS_SELECT
                + " from contacts.contact_addresses "
                "where tenant_id = %s and channel = %s "
                "and address_normalized = %s",
                (tenant_id, channel, normalized),
            ).fetchone()
            if found is None:
                return None
            row = conn.execute(
                "select " + _CONTACT_SELECT + " from contacts.contacts "
                "where tenant_id = %s and contact_id = %s",
                (tenant_id, found["contact_id"]),
            ).fetchone()
        return _record(row, _CONTACT_COLUMNS)

    def record_contacted(self, tenant_id, address_id, at):
        """Stamp when this destination was last reached.

        Written by the dispatch path once it exists (Phase 3); read now by the
        masked preview, where it is often the only field distinguishing a live
        record from a stale duplicate of the same person.
        """
        self._require_tenant(tenant_id)
        with self._write(tenant_id) as conn:
            row = conn.execute(
                "update contacts.contact_addresses set last_contacted_at = %s, "
                "updated_at = now() "
                "where tenant_id = %s and address_id = %s "
                "returning " + _ADDRESS_SELECT,
                (at, tenant_id, address_id),
            ).fetchone()
        return _record(row, _ADDRESS_COLUMNS)

    # -- groupings: references to the canonical record, never copies -------
    #
    # A list, a tag, and a segment are three answers to "which people", and
    # none of them is allowed to become a fourth answer to "who is this
    # person". Membership rows carry identifiers; a segment carries a rule.
    # Neither carries a name, so neither can go stale against the directory.
    #
    # Every resolution below takes ``visible_branch_ids`` positionally and
    # without a default. That is deliberate friction: a grouping resolved
    # unbounded is a way around the tree, and the signature makes forgetting
    # to bound it a ``TypeError`` instead of a disclosure.

    def create_list(
        self, tenant_id, branch_id, name, slug=None, description=None,
        created_by_principal_id=None, list_id=None,
    ):
        """A named, hand-curated grouping that lives on a branch."""
        self._require_tenant(tenant_id)
        with self._write(tenant_id) as conn:
            row = conn.execute(
                """
                insert into contacts.contact_lists(
                    list_id, tenant_id, branch_id, name, slug, description,
                    created_by_principal_id
                ) values (%s, %s, %s, %s, %s, %s, %s)
                returning """ + _LIST_SELECT,
                (
                    list_id or "list:%s" % generate_ulid(),
                    tenant_id,
                    branch_id,
                    name,
                    slugify(slug or name),
                    description,
                    created_by_principal_id,
                ),
            ).fetchone()
        return _record(row, _LIST_COLUMNS)

    def get_list(self, tenant_id, list_id):
        self._require_tenant(tenant_id)
        with self._read(tenant_id) as conn:
            row = conn.execute(
                "select " + _LIST_SELECT + " from contacts.contact_lists "
                "where tenant_id = %s and list_id = %s",
                (tenant_id, list_id),
            ).fetchone()
        return _record(row, _LIST_COLUMNS)

    def add_to_list(
        self, tenant_id, list_id, contact_id, added_by_principal_id=None,
    ):
        """Point a list at a canonical record.

        Idempotent, because "add them again" is what a re-import does and
        because the second row would be the copy this whole section exists to
        prevent.
        """
        self._require_tenant(tenant_id)
        with self._write(tenant_id) as conn:
            existing = conn.execute(
                "select " + _MEMBER_SELECT
                + " from contacts.contact_list_members "
                "where tenant_id = %s and list_id = %s and contact_id = %s",
                (tenant_id, list_id, contact_id),
            ).fetchone()
            if existing is not None:
                return _record(existing, _MEMBER_COLUMNS)
            row = conn.execute(
                """
                insert into contacts.contact_list_members(
                    tenant_id, list_id, contact_id, added_by_principal_id
                ) values (%s, %s, %s, %s)
                returning """ + _MEMBER_SELECT,
                (tenant_id, list_id, contact_id, added_by_principal_id),
            ).fetchone()
        return _record(row, _MEMBER_COLUMNS)

    def remove_from_list(self, tenant_id, list_id, contact_id):
        """Drop the reference. The person is untouched."""
        self._require_tenant(tenant_id)
        with self._write(tenant_id) as conn:
            removed = conn.execute(
                "delete from contacts.contact_list_members "
                "where tenant_id = %s and list_id = %s and contact_id = %s "
                "returning " + _MEMBER_SELECT,
                (tenant_id, list_id, contact_id),
            ).fetchall()
        return len(removed) > 0

    def lists_for_contact(self, tenant_id, contact_id):
        self._require_tenant(tenant_id)
        with self._read(tenant_id) as conn:
            members = conn.execute(
                "select " + _MEMBER_SELECT
                + " from contacts.contact_list_members "
                "where tenant_id = %s and contact_id = %s",
                (tenant_id, contact_id),
            ).fetchall()
            rows = conn.execute(
                "select " + _LIST_SELECT + " from contacts.contact_lists "
                "where tenant_id = %s and list_id = any(%s) order by slug",
                (tenant_id, [row["list_id"] for row in members]),
            ).fetchall()
        return [_record(row, _LIST_COLUMNS) for row in rows]

    def list_members(self, tenant_id, list_id, visible_branch_ids):
        """The canonical records a list points at, bounded to what may be seen.

        The contacts come from `contacts.contacts` and nowhere else, so a
        person in two lists is one row read twice rather than two rows that
        can disagree.
        """
        self._require_tenant(tenant_id)
        if self.get_list(tenant_id, list_id) is None:
            raise GroupingNotFound()
        with self._read(tenant_id) as conn:
            members = conn.execute(
                "select " + _MEMBER_SELECT
                + " from contacts.contact_list_members "
                "where tenant_id = %s and list_id = %s",
                (tenant_id, list_id),
            ).fetchall()
            rows = self._contacts_by_id(
                conn, tenant_id,
                [row["contact_id"] for row in members],
                visible_branch_ids,
            )
        return [_record(row, _CONTACT_COLUMNS) for row in rows]

    def create_tag(
        self, tenant_id, name, slug=None, created_by_principal_id=None,
        tag_id=None,
    ):
        self._require_tenant(tenant_id)
        with self._write(tenant_id) as conn:
            row = conn.execute(
                """
                insert into contacts.contact_tags(
                    tag_id, tenant_id, name, slug, created_by_principal_id
                ) values (%s, %s, %s, %s, %s)
                returning """ + _TAG_SELECT,
                (
                    tag_id or "tag:%s" % generate_ulid(),
                    tenant_id,
                    name,
                    slugify(slug or name),
                    created_by_principal_id,
                ),
            ).fetchone()
        return _record(row, _TAG_COLUMNS)

    def assign_tag(
        self, tenant_id, tag_id, contact_id, assigned_by_principal_id=None,
    ):
        self._require_tenant(tenant_id)
        with self._write(tenant_id) as conn:
            existing = conn.execute(
                "select " + _TAG_ASSIGNMENT_SELECT
                + " from contacts.contact_tag_assignments "
                "where tenant_id = %s and tag_id = %s and contact_id = %s",
                (tenant_id, tag_id, contact_id),
            ).fetchone()
            if existing is not None:
                return _record(existing, _TAG_ASSIGNMENT_COLUMNS)
            row = conn.execute(
                """
                insert into contacts.contact_tag_assignments(
                    tenant_id, tag_id, contact_id, assigned_by_principal_id
                ) values (%s, %s, %s, %s)
                returning """ + _TAG_ASSIGNMENT_SELECT,
                (tenant_id, tag_id, contact_id, assigned_by_principal_id),
            ).fetchone()
        return _record(row, _TAG_ASSIGNMENT_COLUMNS)

    def unassign_tag(self, tenant_id, tag_id, contact_id):
        self._require_tenant(tenant_id)
        with self._write(tenant_id) as conn:
            removed = conn.execute(
                "delete from contacts.contact_tag_assignments "
                "where tenant_id = %s and tag_id = %s and contact_id = %s "
                "returning " + _TAG_ASSIGNMENT_SELECT,
                (tenant_id, tag_id, contact_id),
            ).fetchall()
        return len(removed) > 0

    def tag_slugs_for_contact(self, tenant_id, contact_id):
        self._require_tenant(tenant_id)
        with self._read(tenant_id) as conn:
            assignments = conn.execute(
                "select " + _TAG_ASSIGNMENT_SELECT
                + " from contacts.contact_tag_assignments "
                "where tenant_id = %s and contact_id = %s",
                (tenant_id, contact_id),
            ).fetchall()
            rows = conn.execute(
                "select " + _TAG_SELECT + " from contacts.contact_tags "
                "where tenant_id = %s and tag_id = any(%s) order by slug",
                (tenant_id, [row["tag_id"] for row in assignments]),
            ).fetchall()
        return [row["slug"] for row in rows]

    def tagged_contacts(self, tenant_id, tag_id, visible_branch_ids):
        self._require_tenant(tenant_id)
        with self._read(tenant_id) as conn:
            assignments = conn.execute(
                "select " + _TAG_ASSIGNMENT_SELECT
                + " from contacts.contact_tag_assignments "
                "where tenant_id = %s and tag_id = %s",
                (tenant_id, tag_id),
            ).fetchall()
            rows = self._contacts_by_id(
                conn, tenant_id,
                [row["contact_id"] for row in assignments],
                visible_branch_ids,
            )
        return [_record(row, _CONTACT_COLUMNS) for row in rows]

    def create_segment(
        self, tenant_id, scope_branch_id, name, definition, slug=None,
        created_by_principal_id=None, segment_id=None,
    ):
        """Store the rule and its hash. Never its result.

        Materialising the members here would make "expansion invalidates
        authorization" (R15, KTD7) unfalsifiable: the stored rows and the rule
        would have drifted apart by the time anybody compared them.
        """
        self._require_tenant(tenant_id)
        validate_segment_rule(definition)
        with self._write(tenant_id) as conn:
            row = conn.execute(
                """
                insert into contacts.contact_segments(
                    segment_id, tenant_id, scope_branch_id, name, slug,
                    definition, rule_hash, created_by_principal_id
                ) values (%s, %s, %s, %s, %s, %s, %s, %s)
                returning """ + _SEGMENT_SELECT,
                (
                    segment_id or "segment:%s" % generate_ulid(),
                    tenant_id,
                    scope_branch_id,
                    name,
                    slugify(slug or name),
                    _canonical_rule(definition),
                    rule_hash(definition),
                    created_by_principal_id,
                ),
            ).fetchone()
        return _segment_record(row)

    def get_segment(self, tenant_id, segment_id):
        self._require_tenant(tenant_id)
        with self._read(tenant_id) as conn:
            row = conn.execute(
                "select " + _SEGMENT_SELECT + " from contacts.contact_segments "
                "where tenant_id = %s and segment_id = %s",
                (tenant_id, segment_id),
            ).fetchone()
        return _segment_record(row)

    def resolve_segment(self, tenant_id, segment_id, visible_branch_ids):
        """Evaluate the rule against the directory, inside the caller's bound.

        The intersection is taken before the query, not after: a segment
        scoped to '/acme' resolved by somebody who may only see '/acme/sales'
        reads the sales subtree and never touches the rest, so there is no
        moment at which rows the caller may not see exist in memory.
        """
        self._require_tenant(tenant_id)
        segment = self.get_segment(tenant_id, segment_id)
        if segment is None:
            raise GroupingNotFound()
        definition = segment["definition"] or {}
        validate_segment_rule(definition)
        visible = set(visible_branch_ids or ())
        with self._read(tenant_id) as conn:
            scope = self._segment_scope(conn, tenant_id, segment, definition)
        scoped = [branch_id for branch_id in scope if branch_id in visible]
        if not scoped:
            return []
        rows = self.search_contacts(
            tenant_id,
            definition.get("name_contains") or "",
            branch_ids=scoped,
            status=definition.get("status", "active"),
            expand_subtrees=False,
        )
        return [
            row for row in rows
            if self._matches_rule(tenant_id, row, definition)
        ]

    def _segment_scope(self, conn, tenant_id, segment, definition):
        root = definition.get("branch_id") or segment["scope_branch_id"]
        branch = self._fetch_branch(conn, tenant_id, root)
        if branch is None:
            return []
        scope_branch = self._fetch_branch(
            conn, tenant_id, segment["scope_branch_id"],
        )
        if scope_branch is None:
            return []
        # A rule may narrow its segment's scope branch. It may never step
        # outside it, or creating a segment would be a way to read past the
        # branch the segment was authorised on.
        if branch["path"] != scope_branch["path"] and not _within(
            branch["path"], scope_branch["path"]
        ):
            raise SegmentRuleInvalid(
                "a segment rule cannot reach outside its scope branch"
            )
        scope = [branch["branch_id"]]
        if definition.get("include_subtree", True):
            scope.extend(
                row["branch_id"] for row in
                self._fetch_descendants(conn, tenant_id, branch["path"])
            )
        return scope

    def _matches_rule(self, tenant_id, contact, definition):
        locale = definition.get("locale")
        if locale is not None and contact.get("locale") != locale:
            return False
        channel = definition.get("has_channel")
        if channel is not None:
            if not any(
                address["channel"] == channel for address
                in self.addresses(tenant_id, contact["contact_id"])
            ):
                return False
        required = definition.get("tag_slugs")
        if required:
            held = set(
                self.tag_slugs_for_contact(tenant_id, contact["contact_id"])
            )
            if not set(required).issubset(held):
                return False
        return True

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _contacts_by_id(conn, tenant_id, contact_ids, visible_branch_ids):
        """Canonical rows, filtered to branches the caller may see.

        The branch filter is a predicate on the same statement rather than a
        loop afterwards, so a caller that forgets to check the result is still
        holding rows it was allowed to read.
        """
        if not contact_ids:
            return []
        return conn.execute(
            "select " + _CONTACT_SELECT + " from contacts.contacts "
            "where tenant_id = %s and contact_id = any(%s) "
            "and primary_branch_id = any(%s) order by display_name",
            (tenant_id, list(contact_ids), list(visible_branch_ids or ())),
        ).fetchall()

    @staticmethod
    def _fetch_branch(conn, tenant_id, branch_id):
        if branch_id is None:
            return None
        return conn.execute(
            "select " + _BRANCH_SELECT + " from contacts.branches "
            "where tenant_id = %s and branch_id = %s",
            (tenant_id, branch_id),
        ).fetchone()

    @staticmethod
    def _fetch_descendants(conn, tenant_id, path):
        return conn.execute(
            "select " + _BRANCH_SELECT + " from contacts.branches "
            "where tenant_id = %s and path like %s order by path",
            (tenant_id, path + "/%"),
        ).fetchall()

    def _expand_branches(self, conn, tenant_id, branch_ids, expand=True):
        expanded = []
        for branch_id in branch_ids or ():
            branch = self._fetch_branch(conn, tenant_id, branch_id)
            if branch is None:
                continue
            expanded.append(branch["branch_id"])
            if not expand:
                continue
            expanded.extend(
                row["branch_id"] for row in
                self._fetch_descendants(conn, tenant_id, branch["path"])
            )
        return sorted(set(expanded))


class _BoundConnection(object):
    """A connection with `app.current_org_id` set before anything runs on it.

    Bound here rather than upstream because a pooled connection outlives the
    request that checked it out. Setting it from the same argument the `where`
    clause uses is what makes the policy and the predicate incapable of
    disagreeing.
    """

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


def normalize_path(path):
    """'/Acme/Sales/' and 'acme/sales' both name '/acme/sales'."""
    segments = [
        slugify(segment) for segment in (path or "").split("/") if segment
    ]
    return "/" + "/".join(segments)


def _within(candidate_path, ancestor_path):
    return candidate_path.startswith(ancestor_path + "/")


def _deepest(rows, base_depth):
    return max([row["depth"] - base_depth for row in rows] or [0])


def _check_placement(kind, parent):
    parent_kind = parent["kind"] if parent else None
    if kind == "organization" and parent is not None:
        raise InvalidBranchPlacement("an organization is always a root")
    if kind == "department" and parent_kind != "organization":
        raise InvalidBranchPlacement(
            "a department belongs directly to an organization"
        )
    if kind == "folder" and parent is None:
        raise InvalidBranchPlacement("a folder must sit inside a branch")


def validate_segment_rule(definition):
    """Refuse a rule this evaluator would only partly apply.

    An unknown term skipped silently is the failure a preview cannot show
    you: the rule reads "in Spain and opted in", the audience is everybody,
    and the count looks plausible.
    """
    if definition is None:
        return {}
    if not isinstance(definition, dict):
        raise SegmentRuleInvalid("a segment rule is an object")
    unknown = sorted(set(definition) - set(SEGMENT_RULE_TERMS))
    if unknown:
        raise SegmentRuleInvalid(
            "unsupported segment rule terms: %s" % ", ".join(unknown)
        )
    return definition


def _segment_record(row):
    record = _record(row, _SEGMENT_COLUMNS)
    if record is None:
        return None
    definition = record.get("definition")
    # psycopg hands back a dict for jsonb; the fake and any text column hand
    # back the string that was written. Both are the same rule.
    if isinstance(definition, str):
        record["definition"] = json.loads(definition or "{}")
    elif definition is None:
        record["definition"] = {}
    return record


def _record(row, columns):
    if row is None:
        return None
    if isinstance(row, dict):
        return {name: row.get(name) for name in columns}
    return dict(zip(columns, row))
