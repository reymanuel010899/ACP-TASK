"""Bulk import, and the surfaces a contact manager works the directory from.

R12 says a contact may be added manually or imported, and that a change to
identity, destination, consent or permissions needs an authorized human
decision before it becomes usable. Phase 2 built the ledgers those decisions
land in (U6), the authority they are taken under (U7), and the queue an
*agent's* proposal waits in (U8). What it never built is the way a human puts
ten thousand people into the directory, or looks at one of them afterwards.

This module is both halves, in one file because they are one mechanism seen
from two ends:

**Import is staging plus a decision, never a write.** A file lands in
`contacts.contact_import_batches` / `contacts.contact_import_rows` (0020),
where every row is classified against the account it is entering -- new, a
duplicate of somebody already here, or a collision with somebody the importer
did not mean to touch. Nothing is in the directory yet. Applying the batch is
one recorded human act that walks the staged rows through the *same* paths a
single contact takes: `create_contact`, `add_address`, `propose_address`, and
U8's `ProposalQueue.approve`. There is no second approval path, so there is no
second place for the consent rule to be wrong.

**A staged row that asserts consent without evidence is refused outright.**
Not staged-and-flagged: refused, with nothing written. This is the mechanism
that stops a purchased list becoming an authorized audience. A file that
merely lacks consent is fine and imports normally -- the people exist, and
their addresses stay `proposed`, which under 0018 means unusable for any
effect until a human activates them. The refused case is narrower and worse:
a file that *claims* permission it cannot evidence.

**Every read here is masked and permission-bounded.** `ContactDirectory` is
what the record view, the edit form and the permission editor are built on,
and it answers with U7's `mask_destination` unless the requester separately
holds view over the branch the person sits in. A surface that could return the
digits would eventually return them to somebody holding campaign-use and
nothing else, which is precisely the split U7 exists to keep open.

What is deliberately absent, per the plan's scope boundaries: column-mapping
*proposals* (`read_delimited` takes a mapping, it does not guess one) and
agent-driven merge reasoning (a collision is handed to a person, and the only
answers are "yes, that is the same person" and "no").
"""

import csv
import io
from datetime import datetime, timezone

from libs.contacts_consent import (
    AUTHORITY_ADMINISTER,
    AUTHORITY_MANAGE_CONTACTS,
    CHANNELS,
    PURPOSES,
    ConsentEvidence,
    ConsentEvidenceRequired,
    ContactsConsentRepository,
    HumanDecisionRequired,
)
from libs.contacts_permissions import (
    DIMENSION_ADMINISTER,
    DIMENSION_CAMPAIGN_USE,
    DIMENSION_EDIT,
    DIMENSION_VIEW,
    DIMENSIONS,
    EFFECTS,
    BranchPermissionsRepository,
    ContactsAccess,
    PermissionDenied,
    mask_destination,
)
from libs.contacts_proposals import ProposalQueue
from libs.contacts_repository import (
    EDITABLE_CONTACT_FIELDS,
    ContactsRepository,
    normalize_channel_address,
    record_version as compute_record_version,
)
from libs.tenancy import TenantScopeRequired
from libs.ulid import generate_ulid


__all__ = [
    "CLASSIFICATIONS",
    "ContactDirectory",
    "ContactImporter",
    "ImportAlreadyDecided",
    "ImportBatchNotFound",
    "ImportRowInvalid",
    "ImportRowNotFound",
    "ROW_DECISIONS",
    "StaleContactRecord",
    "UnsupportedRowDecision",
    "canonical_address",
    "read_delimited",
    "to_e164",
]


#: What the scan can conclude about one staged row.
CLASSIFICATIONS = ("new", "duplicate", "collision")

#: What a human may answer to a collision. There is no "keep both": the
#: directory is uniquely keyed on (tenant, channel, canonical address), so a
#: second record holding the same destination is not a decision anybody can
#: take -- it is a row the database refuses. That is R9 enforced by the schema
#: rather than by an option nobody should pick.
ROW_DECISIONS = ("link", "reject")

GRANT_AUTHORITIES = (AUTHORITY_MANAGE_CONTACTS, AUTHORITY_ADMINISTER)

#: Shortest run of digits that still reads as a national subscriber number.
#: Used only to disambiguate a number written without '+' whose leading digits
#: happen to equal the batch's calling code -- see `to_e164`.
MIN_NATIONAL_DIGITS = 7

_BATCH_COLUMNS = (
    "batch_id", "tenant_id", "target_branch_id", "source_name",
    "default_calling_code", "state", "row_count", "new_count",
    "duplicate_count", "collision_count", "staged_by_principal_id",
    "staged_by_actor_kind", "decided_by_principal_id", "decided_by_authority",
    "decided_by_actor_kind", "decided_at", "reason",
)

_ROW_COLUMNS = (
    "import_row_id", "tenant_id", "batch_id", "row_number", "display_name",
    "given_name", "family_name", "company_name", "job_title", "locale",
    "timezone", "external_reference", "channel", "address",
    "address_canonical", "classification", "matched_contact_id",
    "matched_branch_id", "duplicate_of_row_id", "asserts_consent",
    "consent_purposes", "capture_method", "captured_at", "captured_at_local",
    "capture_timezone", "jurisdiction", "disclosure_text", "disclosure_hash",
    "default_unchecked", "legal_basis", "consent_source",
    "consent_expires_at", "state", "applied_contact_id", "applied_address_id",
    "decided_by_principal_id", "decided_by_authority", "decided_by_actor_kind",
    "decided_at", "reason",
)

_BATCH_SELECT = ", ".join(_BATCH_COLUMNS)
_ROW_SELECT = ", ".join(_ROW_COLUMNS)

#: The identity columns a file may carry, beyond the destination itself. Bound
#: to the repository's editable set rather than restated, so a field that
#: becomes editable becomes importable and neither list can quietly lead.
_IDENTITY_FIELDS = EDITABLE_CONTACT_FIELDS

#: The evidence a consent claim has to arrive with. The same set 0018 refuses a
#: grant without; named here so a file cannot assert consent and lose the proof
#: on the way in.
_EVIDENCE_FIELDS = (
    "capture_method", "captured_at", "captured_at_local", "capture_timezone",
    "jurisdiction", "disclosure_text", "legal_basis", "default_unchecked",
    "source", "expires_at",
)


class ImportBatchNotFound(LookupError):
    """No such batch, or it belongs to another account.

    One answer for both, for the reason the rest of contacts gives: a
    distinguishable refusal confirms the batch is real.
    """

    def __init__(self, message="import batch not found"):
        super(ImportBatchNotFound, self).__init__(message)


class ImportRowNotFound(LookupError):
    def __init__(self, message="import row not found"):
        super(ImportRowNotFound, self).__init__(message)


class ImportAlreadyDecided(ValueError):
    """This batch left staging already. Applying it twice would double it."""


class ImportRowInvalid(ValueError):
    """A row that cannot be staged, named with the position it came from.

    Carries `row_number` so a person looking at a ten-thousand-line file is
    told which line, rather than that "the import failed".
    """

    def __init__(self, message, row_number=None):
        self.row_number = row_number
        if row_number is not None:
            message = "row %s: %s" % (row_number, message)
        super(ImportRowInvalid, self).__init__(message)


class UnsupportedRowDecision(ValueError):
    """Not one of the answers a collision has."""


class StaleContactRecord(ValueError):
    """The record moved since it was read, so this edit is about another one."""

    def __init__(self, message="contact record changed since it was read"):
        super(StaleContactRecord, self).__init__(message)


# -- canonical destinations -------------------------------------------------

def to_e164(raw, default_calling_code=None, row_number=None):
    """The one form two spellings of the same number both reduce to.

    Dedupe is only as good as this function. '+1 809 555-0100',
    '001 809 555 0100' and '(809) 555-0100' are one person; comparing them as
    written produces three, which is the exact duplicate this whole unit
    exists to prevent.

    A number written without any international prefix is *not* a destination
    on its own -- the same nine digits reach a different person under a
    different calling code -- so it is refused unless the batch says which
    code to read it under. Guessing would mean an import silently addressing
    another country, and the bill arrives before the mistake is noticed.

    The one genuinely ambiguous case is a national number whose leading digits
    happen to equal the calling code. It is read as already-international only
    when what remains is long enough to be a subscriber number, and that
    choice is recorded on the batch (`default_calling_code`) so the reading is
    reconstructible afterwards.
    """
    text = (raw or "").strip()
    digits = "".join(character for character in text if character.isdigit())
    if not digits:
        return ""
    if "+" in text:
        return "+" + digits
    if digits.startswith("00"):
        return "+" + digits[2:]
    code = str(default_calling_code or "").lstrip("+")
    if not code:
        raise ImportRowInvalid(
            "a number written without '+' needs the batch's calling code: %r"
            % (text,),
            row_number,
        )
    if (
        digits.startswith(code)
        and len(digits) - len(code) >= MIN_NATIONAL_DIGITS
    ):
        return "+" + digits
    # A single leading zero is a national trunk prefix, not part of the
    # subscriber number, and survives into E.164 in nobody's numbering plan.
    return "+" + code + digits.lstrip("0")


def canonical_address(channel, raw, default_calling_code=None, row_number=None):
    """The text an imported address is stored *as*, not merely compared by.

    Deliberately the storage form and not a separate comparison key.
    `contacts.contact_addresses` is unique on
    `normalize_channel_address(address)`, so if import deduped on E.164 while
    storing whatever the file said, two rows this function calls identical
    could still be written as two addresses -- or, worse, one row could pass
    the dedupe and then be refused by a unique constraint halfway through a
    batch. Feeding the canonical form to `add_address` makes the two keys the
    same key by construction.
    """
    if channel not in CHANNELS:
        raise ImportRowInvalid(
            "unsupported channel: %r" % (channel,), row_number,
        )
    if channel == "email":
        return normalize_channel_address("email", raw)
    return to_e164(raw, default_calling_code, row_number)


# -- reading a file ---------------------------------------------------------

def read_delimited(text, mapping=None, delimiter=","):
    """Parse a delimited file into staging rows, using a mapping it is given.

    The mapping is an argument and never a guess. Proposing a column mapping
    is explicitly out of Phase 2's scope, and the reason is worth keeping in
    view: a wrong guess between 'mobile' and 'work phone' does not fail, it
    delivers to the wrong number, and every downstream check passes because
    the number is real.
    """
    reader = csv.DictReader(io.StringIO(text or ""), delimiter=delimiter)
    rows = []
    for raw in reader:
        renamed = {}
        for header, value in raw.items():
            if header is None:
                continue
            field = (mapping or {}).get(header, header)
            renamed[field.strip()] = (value or "").strip()
        rows.append(_row_from_flat(renamed))
    return rows


def _row_from_flat(flat):
    """Lift the flat consent columns of a file into the nested claim."""
    row = {
        name: flat.get(name) or None
        for name in _IDENTITY_FIELDS + ("channel", "address")
    }
    consent = {}
    for name in _EVIDENCE_FIELDS:
        if flat.get(name):
            consent[name] = flat[name]
    purposes = flat.get("consent_purposes")
    if purposes:
        consent["purposes"] = [
            purpose.strip() for purpose in purposes.split("|") if purpose.strip()
        ]
    if "default_unchecked" in consent:
        consent["default_unchecked"] = _as_bool(consent["default_unchecked"])
    for name in ("captured_at", "expires_at"):
        if name in consent:
            consent[name] = _as_datetime(consent[name])
    if consent:
        row["consent"] = consent
    return row


def _as_bool(value):
    if isinstance(value, bool) or value is None:
        return value
    return str(value).strip().lower() in ("true", "yes", "y", "1")


def _as_datetime(value):
    if isinstance(value, datetime) or value is None:
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return value


# -- import -----------------------------------------------------------------

class ContactImporter(object):
    """A file, held in staging, until an authorized human decides on it."""

    def __init__(
        self, db, contacts=None, permissions=None, consent=None, access=None,
        queue=None, clock=None,
    ):
        self.db = db
        self.contacts = contacts or ContactsRepository(db)
        self.permissions = permissions or BranchPermissionsRepository(
            db, contacts=self.contacts,
        )
        self.consent = consent or ContactsConsentRepository(db)
        self.access = access or ContactsAccess(
            db, contacts=self.contacts, permissions=self.permissions,
            consent=self.consent,
        )
        #: U8's queue, reused rather than reimplemented. Approving a staged row
        #: and approving an agent proposal are the same act on the same
        #: ledgers, and two implementations of it would eventually disagree
        #: about whether evidence was required.
        self.queue = queue or ProposalQueue(
            self.access, self.consent, contacts=self.contacts,
        )
        self.clock = clock

    def _now(self, now=None):
        # Defaulted here rather than left to the ledgers below, because
        # `decided_at` on a batch is written by this module and a decision
        # with no timestamp is a decision nobody can order against the rows
        # it produced.
        if now is not None:
            return now
        return self.clock() if self.clock else datetime.now(timezone.utc)

    # -- staging -----------------------------------------------------------

    def stage(
        self, tenant_id, actor, target_branch_id, rows, source_name=None,
        default_calling_code=None, now=None, batch_id=None,
    ):
        """Scan a file against this account and write it to staging.

        Nothing reaches the directory here, and nothing is half-written: every
        row is validated and classified before the first insert, so a file with
        a bad line on row 900 leaves no staging batch behind at all. A
        partially staged import is worse than a refused one, because the part
        that made it in looks reviewed.
        """
        self._require_tenant(tenant_id)
        self.permissions.require(
            tenant_id, actor.principal_id, target_branch_id, DIMENSION_EDIT,
        )
        prepared = self._prepare(tenant_id, rows, default_calling_code)
        self._classify(tenant_id, target_branch_id, prepared)
        identifier = batch_id or "import:%s" % generate_ulid()
        counts = {name: 0 for name in CLASSIFICATIONS}
        for row in prepared:
            counts[row["classification"]] += 1
        with self._write(tenant_id) as conn:
            batch = conn.execute(
                """
                insert into contacts.contact_import_batches(
                    batch_id, tenant_id, target_branch_id, source_name,
                    default_calling_code, state, row_count, new_count,
                    duplicate_count, collision_count, staged_by_principal_id,
                    staged_by_actor_kind
                ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                returning """ + _BATCH_SELECT,
                (
                    identifier, tenant_id, target_branch_id, source_name,
                    default_calling_code, "staged", len(prepared),
                    counts["new"], counts["duplicate"], counts["collision"],
                    actor.principal_id, actor.kind,
                ),
            ).fetchone()
            for row in prepared:
                conn.execute(
                    """
                    insert into contacts.contact_import_rows(
                        import_row_id, tenant_id, batch_id, row_number,
                        display_name, given_name, family_name, company_name,
                        job_title, locale, timezone, external_reference,
                        channel, address, address_canonical, classification,
                        matched_contact_id, matched_branch_id,
                        duplicate_of_row_id, asserts_consent,
                        consent_purposes, capture_method, captured_at,
                        captured_at_local, capture_timezone, jurisdiction,
                        disclosure_text, disclosure_hash, default_unchecked,
                        legal_basis, consent_source, consent_expires_at, state
                    ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                              %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                              %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    returning """ + _ROW_SELECT,
                    (
                        row["import_row_id"], tenant_id, identifier,
                        row["row_number"], row["display_name"],
                        row.get("given_name"), row.get("family_name"),
                        row.get("company_name"), row.get("job_title"),
                        row.get("locale"), row.get("timezone"),
                        row.get("external_reference"), row["channel"],
                        row["address"], row["address_canonical"],
                        row["classification"], row.get("matched_contact_id"),
                        row.get("matched_branch_id"),
                        row.get("duplicate_of_row_id"),
                        bool(row.get("evidence")),
                        list(row.get("purposes") or ()) or None,
                        _evidence_field(row, "capture_method"),
                        _evidence_field(row, "captured_at"),
                        _evidence_field(row, "captured_at_local"),
                        _evidence_field(row, "capture_timezone"),
                        _evidence_field(row, "jurisdiction"),
                        _evidence_field(row, "disclosure_text"),
                        _disclosure_hash(row),
                        _evidence_field(row, "default_unchecked"),
                        _evidence_field(row, "legal_basis"),
                        _evidence_field(row, "source"),
                        _evidence_field(row, "expires_at"),
                        "staged",
                    ),
                )
        return _record(batch, _BATCH_COLUMNS)

    def _prepare(self, tenant_id, rows, default_calling_code):
        """Validate every row before any of them is written."""
        prepared = []
        for index, raw in enumerate(rows or (), start=1):
            display_name = (raw.get("display_name") or "").strip()
            if not display_name:
                raise ImportRowInvalid("a contact needs a display name", index)
            channel = raw.get("channel")
            canonical = canonical_address(
                channel, raw.get("address"), default_calling_code, index,
            )
            if not canonical:
                raise ImportRowInvalid("a contact needs an address", index)
            row = {
                "import_row_id": "importrow:%s" % generate_ulid(),
                "row_number": index,
                "display_name": display_name,
                "channel": channel,
                "address": (raw.get("address") or "").strip(),
                "address_canonical": canonical,
            }
            for name in _IDENTITY_FIELDS:
                if name != "display_name":
                    row[name] = raw.get(name)
            evidence, purposes = self._consent_claim(raw.get("consent"), index)
            row["evidence"] = evidence
            row["purposes"] = purposes
            prepared.append(row)
        return prepared

    @staticmethod
    def _consent_claim(claim, row_number):
        """Turn a row's consent block into evidence, or refuse the import.

        The refusal is the point of this method. A claim of permission that
        cannot be defended later is worse than no claim at all -- it *looks*
        like permission, to every surface downstream -- so it is refused here,
        before anything is staged, rather than staged as a flagged row that
        somebody eventually approves in bulk.
        """
        if not claim:
            return None, ()
        purposes = tuple(claim.get("purposes") or ())
        unknown = sorted(set(purposes) - set(PURPOSES))
        if unknown:
            raise ImportRowInvalid(
                "unsupported consent purpose: %s" % ", ".join(unknown),
                row_number,
            )
        if not purposes:
            raise ImportRowInvalid(
                "a consent claim names the purposes it covers", row_number,
            )
        evidence = ConsentEvidence(
            capture_method=claim.get("capture_method"),
            captured_at=claim.get("captured_at"),
            captured_at_local=claim.get("captured_at_local"),
            capture_timezone=claim.get("capture_timezone"),
            jurisdiction=claim.get("jurisdiction"),
            disclosure_text=claim.get("disclosure_text"),
            legal_basis=claim.get("legal_basis"),
            source=claim.get("source"),
            default_unchecked=claim.get("default_unchecked"),
            expires_at=claim.get("expires_at"),
        )
        missing = evidence.missing_fields()
        if missing:
            raise ConsentEvidenceRequired(
                ["row %s: %s" % (row_number, name) for name in missing]
            )
        return evidence, purposes

    def _classify(self, tenant_id, target_branch_id, prepared):
        """New, duplicate, or a collision a person has to settle.

        Two passes' worth of matching in one loop: against the rest of the
        file, then against the directory. The file half matters more than it
        looks -- a spreadsheet holding the same person on rows 12 and 4,000 is
        the ordinary case, and a dedupe that only consulted the database would
        create the second one and then be unable to create it.

        A destination already held by somebody outside the target subtree is a
        collision and never a merge. The importer chose a branch; a row that
        reaches out of it is either a person they did not know was already
        here or a number that has changed hands, and both are decisions.
        """
        try:
            scope = {
                branch["branch_id"]
                for branch in self.contacts.subtree(tenant_id, target_branch_id)
            }
        except LookupError:
            scope = set()
        seen = {}
        for row in prepared:
            key = (row["channel"], row["address_canonical"])
            first = seen.get(key)
            if first is not None:
                row["classification"] = "duplicate"
                row["duplicate_of_row_id"] = first["import_row_id"]
                row["matched_contact_id"] = first.get("matched_contact_id")
                row["matched_branch_id"] = first.get("matched_branch_id")
                continue
            seen[key] = row
            existing = self.contacts.contact_by_address(
                tenant_id, row["channel"], row["address_canonical"],
            )
            if existing is None:
                row["classification"] = "new"
                continue
            row["matched_contact_id"] = existing["contact_id"]
            row["matched_branch_id"] = existing["primary_branch_id"]
            row["classification"] = (
                "duplicate" if existing["primary_branch_id"] in scope
                else "collision"
            )

    # -- reading staging ---------------------------------------------------

    def batch(self, tenant_id, batch_id):
        self._require_tenant(tenant_id)
        with self._read(tenant_id) as conn:
            row = conn.execute(
                "select " + _BATCH_SELECT
                + " from contacts.contact_import_batches "
                "where tenant_id = %s and batch_id = %s",
                (tenant_id, batch_id),
            ).fetchone()
        return _record(row, _BATCH_COLUMNS)

    def staged_rows(self, tenant_id, batch_id):
        """The raw staged rows. Internal; `review` is the surface read."""
        self._require_tenant(tenant_id)
        with self._read(tenant_id) as conn:
            rows = conn.execute(
                "select " + _ROW_SELECT
                + " from contacts.contact_import_rows "
                "where tenant_id = %s and batch_id = %s "
                "order by row_number",
                (tenant_id, batch_id),
            ).fetchall()
        return [_record(row, _ROW_COLUMNS) for row in rows]

    def review(self, tenant_id, principal_id, batch_id):
        """What a reviewer is shown before authorizing a batch.

        Destinations are masked here even though the person who uploaded the
        file has already seen them in full: the reviewer is frequently not the
        uploader, and "they saw it once" is not an authority model. The
        written form is included only where the principal separately holds
        view over the branch the row is entering.
        """
        self._require_tenant(tenant_id)
        batch = self.batch(tenant_id, batch_id)
        if batch is None:
            raise ImportBatchNotFound()
        branch = self.contacts.get_branch(
            tenant_id, batch["target_branch_id"],
        ) or {}
        may_view = self.permissions.holds(
            tenant_id, principal_id, batch["target_branch_id"], DIMENSION_VIEW,
        )
        entries = []
        for row in self.staged_rows(tenant_id, batch_id):
            entry = {
                "import_row_id": row["import_row_id"],
                "row_number": row["row_number"],
                "channel": row["channel"],
                "classification": row["classification"],
                "state": row["state"],
                "asserts_consent": bool(row["asserts_consent"]),
                "consent_purposes": tuple(row["consent_purposes"] or ()),
                "matched_contact_id": row["matched_contact_id"],
                "duplicate_of_row_id": row["duplicate_of_row_id"],
                # Whether this reviewer may claim the collision is the same
                # person. Computed here rather than inferred by the surface:
                # the branch that person lives in is frequently one the
                # reviewer cannot see, so the browser has nothing to infer it
                # from and would default to "yes".
                "may_link": bool(
                    row["classification"] == "collision"
                    and row["matched_branch_id"]
                    and self.permissions.holds(
                        tenant_id, principal_id, row["matched_branch_id"],
                        DIMENSION_EDIT,
                    )
                ),
                "destination": mask_destination(
                    row["channel"], row["address_canonical"],
                    address_id=row["import_row_id"], tenant_id=tenant_id,
                    branch_path=branch.get("path"),
                ).as_dict(),
            }
            if may_view:
                entry["display_name"] = row["display_name"]
                entry["written_address"] = row["address"]
            else:
                # Absent rather than null, the same shape `audience_preview`
                # uses: a key that is sometimes a name and sometimes None
                # invites a renderer to print "None" where a name would go.
                entry["redacted"] = True
            entries.append(entry)
        return {
            "batch_id": batch["batch_id"],
            "state": batch["state"],
            "target_branch_id": batch["target_branch_id"],
            "branch_path": branch.get("path"),
            "source_name": batch["source_name"],
            "row_count": batch["row_count"],
            "new_count": batch["new_count"],
            "duplicate_count": batch["duplicate_count"],
            "collision_count": batch["collision_count"],
            "decided_by_principal_id": batch["decided_by_principal_id"],
            "redacted": not may_view,
            "rows": tuple(entries),
        }

    # -- the decision ------------------------------------------------------

    def apply(self, tenant_id, batch_id, actor, reason=None, now=None):
        """One human act, many rows. Recorded as one act, with its actor.

        A thousand-row import cannot ask for a thousand clicks, so the batch
        decision is the unit. What it must not become is an anonymous one:
        every row this writes carries the principal who authorized it, and the
        batch carries them too, because a bulk mistake is only recoverable if
        somebody can be asked what they thought they were approving.

        Collisions are deliberately not covered by it. They are the rows where
        "apply the whole file" and "decide each case" genuinely differ, so they
        stay staged and go to `decide_row` one at a time.
        """
        self._require_tenant(tenant_id)
        batch = self.batch(tenant_id, batch_id)
        if batch is None:
            raise ImportBatchNotFound()
        if batch["state"] != "staged":
            raise ImportAlreadyDecided(
                "batch %s is already %s" % (batch_id, batch["state"])
            )
        _require_authorized_human(
            actor, "applying an import requires an authorized human decision",
        )
        self.permissions.require(
            tenant_id, actor.principal_id, batch["target_branch_id"],
            DIMENSION_EDIT,
        )
        moment = self._now(now)
        produced, created, linked, deferred = {}, 0, 0, 0
        for row in self.staged_rows(tenant_id, batch_id):
            if row["state"] != "staged":
                continue
            key = (row["channel"], row["address_canonical"])
            if row["classification"] == "collision":
                deferred += 1
                continue
            if row["classification"] == "duplicate":
                settled = row["matched_contact_id"] or produced.get(key, {}).get(
                    "contact_id"
                )
                if settled is None:
                    # A duplicate of a row that itself is still waiting -- a
                    # collision written twice in the file. It waits with it.
                    deferred += 1
                    continue
                self._settle(
                    tenant_id, row["import_row_id"], actor, "applied",
                    contact_id=settled,
                    address_id=produced.get(key, {}).get("address_id"),
                    reason="already a canonical record in this account",
                    now=moment,
                )
                linked += 1
                continue
            contact, address = self._materialize(
                tenant_id, batch, row, actor, moment,
            )
            produced[key] = {
                "contact_id": contact["contact_id"],
                "address_id": address["address_id"],
            }
            self._settle(
                tenant_id, row["import_row_id"], actor, "applied",
                contact_id=contact["contact_id"],
                address_id=address["address_id"],
                reason=reason, now=moment,
            )
            created += 1
        decided = self._decide_batch(
            tenant_id, batch_id, actor, "applied", reason, moment,
        )
        return {
            "batch_id": batch_id,
            "state": decided["state"],
            "created": created,
            "linked": linked,
            "deferred": deferred,
            "decided_by_principal_id": decided["decided_by_principal_id"],
        }

    def _materialize(self, tenant_id, batch, row, actor, moment):
        """One staged row, walked through the ordinary single-contact path.

        The branch is load-bearing, and so is the fact that it is a branch
        rather than a sequence. A row with no evidence gets `propose_address`
        and is left in 0018's `proposed` state -- unusable for any effect, and
        visible in U8's review queue where a person can act on it. A row that
        arrived with evidence goes through `ProposalQueue.approve`, which
        activates the address and records the grant as one authorized human
        decision.

        Writing *both* -- a proposal and then an activation, stamped with the
        same instant -- would be the tidier-looking code and the wrong ledger
        entry. Not for ordering reasons: 0018 breaks a `recorded_at` tie on
        `ledger_sequence`, so the activation written second is the one that
        reads as current. For truthfulness ones. A row that arrived with
        evidence was never proposed and then approved, and writing a proposal
        nobody made puts an event that did not happen into an append-only
        ledger the account is expected to defend line by line.
        """
        contact = self.contacts.create_contact(
            tenant_id, batch["target_branch_id"], row["display_name"],
            given_name=row["given_name"], family_name=row["family_name"],
            locale=row["locale"], timezone=row["timezone"],
            company_name=row["company_name"], job_title=row["job_title"],
            external_reference=row["external_reference"], source="import",
        )
        address = self.contacts.add_address(
            tenant_id, contact["contact_id"], row["channel"],
            row["address_canonical"], is_primary=True,
        )
        if row["asserts_consent"]:
            self.queue.approve(
                tenant_id, address["address_id"], actor,
                evidence=_evidence_from_row(row),
                purposes=tuple(row["consent_purposes"] or ()),
                reason="import batch %s" % batch["batch_id"],
                now=moment,
            )
        else:
            self.consent.propose_address(
                tenant_id, address["address_id"], actor,
                reason="imported from %s row %s" % (
                    batch["source_name"] or "an import", row["row_number"],
                ),
                now=moment,
            )
        return contact, address

    def decide_row(
        self, tenant_id, import_row_id, actor, decision, reason=None, now=None,
    ):
        """Settle one collision, by hand, with the authority it requires.

        'link' says the staged row is the person who is already here. It
        creates nothing -- that is the whole point of R9 -- but it is still an
        assertion about a record living in a branch the importer may never
        have been able to see, so it takes edit authority *there* rather than
        on the branch the file was aimed at. An importer who cannot hold that
        authority can still reject the row.
        """
        self._require_tenant(tenant_id)
        if decision not in ROW_DECISIONS:
            raise UnsupportedRowDecision(
                "a collision is answered with %s" % " or ".join(ROW_DECISIONS)
            )
        row = self._row(tenant_id, import_row_id)
        if row["state"] != "staged":
            raise ImportAlreadyDecided(
                "row %s is already %s" % (import_row_id, row["state"])
            )
        _require_authorized_human(
            actor, "deciding an import row requires an authorized human",
        )
        if decision == "reject":
            return self._settle(
                tenant_id, import_row_id, actor, "rejected",
                contact_id=None, address_id=None,
                reason=reason or "rejected in import review",
                now=self._now(now),
            )
        if not row["matched_contact_id"]:
            raise UnsupportedRowDecision(
                "there is nobody to link this row to"
            )
        self.permissions.require(
            tenant_id, actor.principal_id, row["matched_branch_id"],
            DIMENSION_EDIT,
        )
        return self._settle(
            tenant_id, import_row_id, actor, "applied",
            contact_id=row["matched_contact_id"], address_id=None,
            reason=reason or "same person as an existing canonical record",
            now=self._now(now),
        )

    # -- internals ---------------------------------------------------------

    def _row(self, tenant_id, import_row_id):
        with self._read(tenant_id) as conn:
            row = conn.execute(
                "select " + _ROW_SELECT
                + " from contacts.contact_import_rows "
                "where tenant_id = %s and import_row_id = %s",
                (tenant_id, import_row_id),
            ).fetchone()
        if row is None:
            raise ImportRowNotFound()
        return _record(row, _ROW_COLUMNS)

    def _settle(
        self, tenant_id, import_row_id, actor, state, contact_id, address_id,
        reason, now,
    ):
        with self._write(tenant_id) as conn:
            row = conn.execute(
                "update contacts.contact_import_rows set state = %s, "
                "applied_contact_id = %s, applied_address_id = %s, "
                "decided_by_principal_id = %s, decided_by_authority = %s, "
                "decided_by_actor_kind = %s, decided_at = %s, reason = %s, "
                "updated_at = now() "
                "where tenant_id = %s and import_row_id = %s "
                "returning " + _ROW_SELECT,
                (
                    state, contact_id, address_id, actor.principal_id,
                    _authority_of(actor), actor.kind, now, reason,
                    tenant_id, import_row_id,
                ),
            ).fetchone()
        return _record(row, _ROW_COLUMNS)

    def _decide_batch(self, tenant_id, batch_id, actor, state, reason, now):
        with self._write(tenant_id) as conn:
            row = conn.execute(
                "update contacts.contact_import_batches set state = %s, "
                "decided_by_principal_id = %s, decided_by_authority = %s, "
                "decided_by_actor_kind = %s, decided_at = %s, reason = %s, "
                "updated_at = now() "
                "where tenant_id = %s and batch_id = %s "
                "returning " + _BATCH_SELECT,
                (
                    state, actor.principal_id, _authority_of(actor),
                    actor.kind, now, reason, tenant_id, batch_id,
                ),
            ).fetchone()
        return _record(row, _BATCH_COLUMNS)

    @staticmethod
    def _require_tenant(tenant_id):
        if not tenant_id or not isinstance(tenant_id, str):
            raise TenantScopeRequired()
        return tenant_id

    def _read(self, tenant_id):
        return _BoundConnection(self.db, tenant_id, write=False)

    def _write(self, tenant_id):
        return _BoundConnection(self.db, tenant_id, write=True)


# -- the human's directory --------------------------------------------------

class ContactDirectory(object):
    """What a contact manager sees and changes, without going near the agent.

    Every read is bounded by the requester's authority and masked by U7's
    `mask_destination`; every write is an authorized human decision that lands
    in the ledgers U6 and U7 already own. Nothing here is a new place to store
    a fact -- it is the missing surface over the ones that exist.
    """

    def __init__(
        self, db, contacts=None, permissions=None, consent=None, access=None,
        queue=None, clock=None,
    ):
        self.db = db
        self.contacts = contacts or ContactsRepository(db)
        self.permissions = permissions or BranchPermissionsRepository(
            db, contacts=self.contacts,
        )
        self.consent = consent or ContactsConsentRepository(db)
        self.access = access or ContactsAccess(
            db, contacts=self.contacts, permissions=self.permissions,
            consent=self.consent,
        )
        self.queue = queue or ProposalQueue(
            self.access, self.consent, contacts=self.contacts,
        )
        self.clock = clock

    def _now(self, now=None):
        # Defaulted here rather than left to the ledgers below, because
        # `decided_at` on a batch is written by this module and a decision
        # with no timestamp is a decision nobody can order against the rows
        # it produced.
        if now is not None:
            return now
        return self.clock() if self.clock else datetime.now(timezone.utc)

    # -- the record view ---------------------------------------------------

    def record(self, tenant_id, principal_id, contact_id, now=None):
        """One person, with all four axes and nothing the requester may not see.

        Returns ``None`` for a contact in another account, and for one in a
        branch this principal holds neither view nor campaign-use over --
        absence, not refusal, because a distinguishable refusal confirms the
        person exists.

        Holding campaign-use alone still returns a record, redacted: counts,
        exclusion state and masked destinations, with the identity absent.
        That is U7's projection applied to one row instead of an audience, and
        it is what lets an operator ask "why did this person fall out of my
        campaign" without being handed the directory.
        """
        self._require_tenant(tenant_id)
        contact = self.contacts.get_contact(tenant_id, contact_id)
        if contact is None:
            return None
        branch_id = contact["primary_branch_id"]
        effective = self.permissions.effective(
            tenant_id, principal_id, branch_id,
        )
        if not (effective[DIMENSION_VIEW] or effective[DIMENSION_CAMPAIGN_USE]):
            return None
        may_view = effective[DIMENSION_VIEW]
        branch = self.contacts.get_branch(tenant_id, branch_id) or {}
        addresses = self.contacts.addresses(tenant_id, contact_id)
        moment = self._now(now)
        entries = []
        authorized_channels = set()
        for address in addresses:
            channel = address["channel"]
            usability = self.consent.usability_state(
                tenant_id, address["address_id"],
            )
            suppression = self.consent.suppression_state(
                tenant_id, address["address_id"], channel,
            )
            reachability = self.consent.provider_reachability(
                tenant_id, address["address_id"], channel,
            )
            consent = self.consent.consent_by_purpose(
                tenant_id, address["address_id"], channel, now=moment,
            )
            eligibility = {
                purpose: self.consent.evaluate_eligibility(
                    tenant_id, address["address_id"], channel, purpose,
                    now=moment,
                ).reason
                for purpose in PURPOSES
            }
            entry = {
                "address_id": address["address_id"],
                "channel": channel,
                "is_primary": bool(address["is_primary"]),
                "label": address["label"],
                "last_contacted_at": address.get("last_contacted_at"),
                "destination": mask_destination(
                    channel, address["address"],
                    address_id=address["address_id"], tenant_id=tenant_id,
                    branch_path=branch.get("path"),
                    last_contacted_at=address.get("last_contacted_at"),
                ).as_dict(),
                "usability": usability["state"],
                "suppression": suppression["state"],
                "provider_reachability": reachability["state"],
                "consent": {
                    purpose: {
                        "state": reading["state"],
                        "capture_method": reading.get("capture_method"),
                        "captured_at": reading.get("captured_at"),
                        "jurisdiction": reading.get("jurisdiction"),
                        "legal_basis": reading.get("legal_basis"),
                        "disclosure_hash": reading.get("disclosure_hash"),
                        "expires_at": reading.get("expires_at"),
                        "decided_by_principal_id": reading.get(
                            "decided_by_principal_id"
                        ),
                    }
                    for purpose, reading in consent.items()
                },
                "exclusions": {
                    purpose: reason for purpose, reason in eligibility.items()
                    if reason != "eligible"
                },
            }
            if may_view:
                # The written form, and only for a principal who holds view.
                # There is no branch of this function that puts it in the
                # payload otherwise, which is what makes the mask the default
                # rather than a formatting choice somebody can skip.
                entry["written_address"] = address["address"]
            if any(reason == "eligible" for reason in eligibility.values()):
                authorized_channels.add(channel)
            entries.append(entry)
        record = {
            "contact_id": contact_id,
            "record_version": compute_record_version(contact, addresses),
            "branch_id": branch_id,
            "branch_path": branch.get("path"),
            "status": contact["status"],
            "source": contact["source"],
            "addresses": tuple(entries),
            "authorized_channels": tuple(sorted(authorized_channels)),
            "may_edit": effective[DIMENSION_EDIT],
            "may_administer": effective[DIMENSION_ADMINISTER],
        }
        if may_view:
            for name in _IDENTITY_FIELDS:
                record[name] = contact.get(name)
        else:
            record["redacted"] = True
        return record

    # -- manual entry ------------------------------------------------------

    def create_contact(
        self, tenant_id, actor, branch_id, display_name, channel=None,
        address=None, consent=None, default_calling_code=None, now=None,
        **identity
    ):
        """Add one person by hand. R12's other arm, on the same rails.

        Identical in every consequence to a one-row import: the address lands
        `proposed` and therefore unusable, and it becomes usable only through
        `ProposalQueue.approve` with the evidence U6 requires. A manual form
        that could write a usable address directly would be the hole every
        other guard in this phase is built around.
        """
        self._require_tenant(tenant_id)
        _require_authorized_human(
            actor, "creating a contact requires an authorized human decision",
        )
        self.permissions.require(
            tenant_id, actor.principal_id, branch_id, DIMENSION_EDIT,
        )
        if not (display_name or "").strip():
            raise ValueError("a contact needs a display name")
        unknown = sorted(set(identity) - set(_IDENTITY_FIELDS))
        if unknown:
            raise ValueError(
                "not an editable contact field: %s" % ", ".join(unknown)
            )
        moment = self._now(now)
        evidence, purposes = ContactImporter._consent_claim(consent, None)
        canonical = None
        if address:
            canonical = canonical_address(
                channel, address, default_calling_code,
            )
            existing = self.contacts.contact_by_address(
                tenant_id, channel, canonical,
            )
            if existing is not None:
                same_identity = (
                    existing["primary_branch_id"] == branch_id
                    and existing["display_name"] == display_name.strip()
                    and all(
                        value is None or existing.get(name) == value
                        for name, value in identity.items()
                    )
                )
                if not same_identity:
                    raise ValueError(
                        "this address already belongs to another contact"
                    )
                stored = next(
                    item for item in self.contacts.addresses(
                        tenant_id, existing["contact_id"]
                    )
                    if item["channel"] == channel
                    and item["address_normalized"] == canonical
                )
                if evidence is not None:
                    self.queue.approve(
                        tenant_id, stored["address_id"], actor,
                        evidence=evidence, purposes=purposes,
                        reason="completed retried manual entry", now=moment,
                    )
                return {
                    "contact_id": existing["contact_id"],
                    "address_id": stored["address_id"],
                }
        contact = self.contacts.create_contact(
            tenant_id, branch_id, display_name.strip(), source="manual",
            **{
                name: identity.get(name) for name in _IDENTITY_FIELDS
                if name != "display_name"
            }
        )
        created_address = None
        if address:
            created_address = self.contacts.add_address(
                tenant_id, contact["contact_id"], channel, canonical,
                is_primary=True,
            )
            if evidence is not None:
                self.queue.approve(
                    tenant_id, created_address["address_id"], actor,
                    evidence=evidence, purposes=purposes,
                    reason="entered by hand", now=moment,
                )
            else:
                # Not both, and not in one instant -- see `_materialize`.
                self.consent.propose_address(
                    tenant_id, created_address["address_id"], actor,
                    reason="entered by hand", now=moment,
                )
        return {
            "contact_id": contact["contact_id"],
            "address_id": None if created_address is None
            else created_address["address_id"],
        }

    def update_contact(
        self, tenant_id, actor, contact_id, record_version, changes,
    ):
        """Correct identity fields on a record the requester already read.

        The version is checked and refused loudly, the same way U8's
        `propose_update` refuses: an edit raised against a record that has
        since moved is an edit to a different record, and applying it would
        overwrite whatever the move was without anybody seeing it.
        """
        self._require_tenant(tenant_id)
        _require_authorized_human(
            actor, "editing a contact requires an authorized human decision",
        )
        contact = self.contacts.get_contact(tenant_id, contact_id)
        if contact is None:
            return None
        self.permissions.require(
            tenant_id, actor.principal_id, contact["primary_branch_id"],
            DIMENSION_EDIT,
        )
        addresses = self.contacts.addresses(tenant_id, contact_id)
        if compute_record_version(contact, addresses) != record_version:
            raise StaleContactRecord()
        if "display_name" in (changes or {}) and not (
            changes["display_name"] or ""
        ).strip():
            raise ValueError("a contact needs a display name")
        updated = self.contacts.update_contact(tenant_id, contact_id, changes)
        return {
            "contact_id": contact_id,
            "record_version": compute_record_version(
                updated, self.contacts.addresses(tenant_id, contact_id),
            ),
        }

    # -- the permission editor --------------------------------------------

    def branch_permissions(self, tenant_id, principal_id, branch_id):
        """What the editor renders: inherited, explicit, and what may be given.

        `grantable` is the answer to the question the UI keeps getting wrong.
        An administrator on one branch is not an administrator everywhere, and
        an administrator who does not themselves hold campaign-use cannot hand
        it out -- so the set of dimensions this principal may delegate here is
        computed on the server and sent, rather than inferred by a component
        from a role string.
        """
        self._require_tenant(tenant_id)
        branch = self.contacts.get_branch(tenant_id, branch_id)
        if branch is None:
            return None
        effective = self.permissions.effective(
            tenant_id, principal_id, branch_id,
        )
        if not effective[DIMENSION_ADMINISTER]:
            return None
        return {
            "branch_id": branch_id,
            "branch_path": branch["path"],
            "effective": effective,
            "decisions": tuple(
                self.permissions.decisions_on_branch(tenant_id, branch_id)
            ),
            "grantable": tuple(
                dimension for dimension in DIMENSIONS if effective[dimension]
            ),
        }

    def set_branch_permission(
        self, tenant_id, actor, branch_id, principal_id, dimension, effect,
        reason=None,
    ):
        """Grant or restrict one dimension, bounded by what the actor holds.

        Two gates, and the second is the one U7 could not apply on its own.
        U7 requires an administrator; it has no opinion about *where*, because
        at that layer the actor's own branch authority is not in the call. Here
        it is, so:

        * the actor must hold `administer` on this branch, not merely somewhere
          -- otherwise an administrator of `/acme/finance` could open
          `/acme/sales`;
        * and the actor must hold the dimension they are granting. Handing out
          view over a branch whose names you cannot read is privilege creation,
          not delegation.

        A restriction is exempt from the second gate. Closing a dimension is
        restrictive, and the asymmetry KTD13 sets up says a restrictive move
        does not need the authority a permissive one does.
        """
        self._require_tenant(tenant_id)
        if dimension not in DIMENSIONS:
            raise ValueError("unknown permission dimension: %r" % (dimension,))
        if effect not in EFFECTS:
            raise ValueError("unknown permission effect: %r" % (effect,))
        _require_authorized_human(
            actor, "a permission change requires a human decision",
        )
        effective = self.permissions.effective(
            tenant_id, actor.principal_id, branch_id,
        )
        if not effective[DIMENSION_ADMINISTER]:
            raise PermissionDenied(DIMENSION_ADMINISTER)
        if effect == "grant" and not effective.get(dimension):
            raise PermissionDenied(
                dimension,
                "cannot grant %s here: this principal does not hold it"
                % (dimension,),
            )
        writer = self.permissions.grant if effect == "grant" \
            else self.permissions.restrict
        return writer(
            tenant_id, branch_id, principal_id, dimension, actor, reason=reason,
        )

    def revoke_branch_permission(
        self, tenant_id, actor, branch_id, principal_id, dimension,
    ):
        """Remove the decision written at this branch. Inheritance resumes."""
        self._require_tenant(tenant_id)
        _require_authorized_human(
            actor, "a permission change requires a human decision",
        )
        if not self.permissions.holds(
            tenant_id, actor.principal_id, branch_id, DIMENSION_ADMINISTER,
        ):
            raise PermissionDenied(DIMENSION_ADMINISTER)
        return self.permissions.revoke(
            tenant_id, branch_id, principal_id, dimension, actor,
        )

    @staticmethod
    def _require_tenant(tenant_id):
        if not tenant_id or not isinstance(tenant_id, str):
            raise TenantScopeRequired()
        return tenant_id


# -- shared helpers ---------------------------------------------------------

def _require_authorized_human(actor, message):
    """R12's gate, in the one shape every write in this module uses.

    Actor kind first, then authority, matching `grant_consent`: an agent
    holding every authority in the set is still a proposer, and the message it
    gets should say so rather than complain about a missing authority it
    actually has.
    """
    if actor is None or actor.kind != "human":
        raise HumanDecisionRequired(message)
    if not actor.holds(*GRANT_AUTHORITIES):
        raise HumanDecisionRequired(message)
    return actor


def _authority_of(actor):
    return AUTHORITY_ADMINISTER if actor.holds(AUTHORITY_ADMINISTER) \
        else AUTHORITY_MANAGE_CONTACTS


def _evidence_field(row, name):
    evidence = row.get("evidence")
    return None if evidence is None else getattr(evidence, name, None)


def _disclosure_hash(row):
    evidence = row.get("evidence")
    return None if evidence is None else evidence.disclosure_hash


def _evidence_from_row(row):
    """Rebuild the evidence bundle from what staging kept.

    Reconstructed from the row rather than carried in memory from `stage`,
    because the batch is applied in a different request -- often by a
    different person -- and the evidence that defends the grant has to be the
    evidence that was reviewed, not whatever the applying call was handed.
    """
    return ConsentEvidence(
        capture_method=row["capture_method"],
        captured_at=row["captured_at"],
        captured_at_local=row["captured_at_local"],
        capture_timezone=row["capture_timezone"],
        jurisdiction=row["jurisdiction"],
        disclosure_text=row["disclosure_text"],
        legal_basis=row["legal_basis"],
        source=row["consent_source"],
        default_unchecked=row["default_unchecked"],
        expires_at=row["consent_expires_at"],
    )


class _BoundConnection(object):
    """`app.current_org_id` bound from the same argument the predicate uses."""

    def __init__(self, db, tenant_id, write):
        self.db = db
        self.tenant_id = tenant_id
        self._context = db.transaction() if write else db.connection()

    def __enter__(self):
        conn = self._context.__enter__()
        self.db.set_org_context(conn, self.tenant_id)
        return conn

    def __exit__(self, *exc_info):
        return self._context.__exit__(*exc_info)


def _record(row, columns):
    if row is None:
        return None
    if isinstance(row, dict):
        return {name: row.get(name) for name in columns}
    return dict(zip(columns, row))
