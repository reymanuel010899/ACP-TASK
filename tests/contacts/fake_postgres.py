"""A Postgres stand-in that enforces what the contacts migrations say.

Covers `migrations/0017_contacts.sql`, `migrations/0018_contact_consent.sql`,
`migrations/0019_contact_permissions.sql`, and
`migrations/0020_contact_import.sql`.

The point of this fake is not to let the contacts tests run without a
database. It is to make the tests able to fail for the right reason.

A fake that simply stores whatever it is handed and returns whatever is asked
for would pass every isolation test ever written against it, because the
isolation would live entirely in the assertions. So this one enforces the
three mechanisms the migration relies on, and nothing the migration does not
have:

* **Forced row-level security.** Every read is filtered to the tenant bound
  by ``select set_config('app.current_org_id', ...)``, and every write is
  rejected unless the row's tenant matches. A repository method that forgot
  its ``tenant_id`` predicate still cannot see another account's rows here,
  which is exactly the backstop the real ``force row level security`` gives.
* **Tenant-carrying composite foreign keys.** A child whose parent lives in
  another tenant does not resolve, so it cannot be written.
* **The cycle trigger**, raising the same message the migration raises.
* **The append-only triggers**, including the one narrow hole 0018 leaves for
  the retention purge. "The audit outlives the message" is only a real claim
  against a store that would have refused the rewrite.
* **The ledger identity columns.** 0018's four ledgers are read as "the newest
  row wins", and `recorded_at` ties routinely -- one inbound STOP writes a
  withdrawal per purpose under a single `now()`. The store hands out
  `ledger_sequence` in insertion order the way `generated always as identity`
  does, and refuses a caller that tries to supply or change one. A fake that
  left the column to the caller would let a test agree with a reading the
  database would have produced by coin flip.

It also holds the tenant-scoped unique keys, since "two accounts may hold the
same phone number" is only a real assertion against a store that would have
rejected a global one.
"""

import re
from contextlib import contextmanager


class FakeIntegrityError(Exception):
    """A constraint the database refused, not a decision the caller made."""


class RowLevelSecurityViolation(FakeIntegrityError):
    """A write whose tenant is not the one bound on this connection."""


#: Declared columns per table, so selecting a column nobody inserted returns
#: null rather than raising, the way a real table would.
COLUMNS = {
    "contacts.branches": (
        "branch_id", "tenant_id", "parent_branch_id", "parent_kind", "kind",
        "name", "slug", "path", "depth", "owner_principal_id",
    ),
    "contacts.contacts": (
        "contact_id", "tenant_id", "primary_branch_id", "display_name",
        "given_name", "family_name", "locale", "timezone", "company_name",
        "job_title", "status", "merged_into_contact_id", "external_reference",
        "source",
    ),
    "contacts.contact_addresses": (
        "address_id", "tenant_id", "contact_id", "channel", "address",
        "address_normalized", "label", "is_primary", "verified_at",
        "last_contacted_at",
    ),
    # The three axes of `migrations/0018_contact_consent.sql`, plus the
    # provider-reachability ledger that is constantly mistaken for one.
    "contacts.consent_records": (
        "consent_record_id", "tenant_id", "contact_id", "address_id",
        "channel", "purpose", "state", "transition_kind", "capture_method",
        "captured_at", "captured_at_local", "capture_timezone", "jurisdiction",
        "disclosure_text", "disclosure_hash", "default_unchecked",
        "legal_basis", "source", "actor_kind", "actor_principal_id",
        "decided_by_principal_id", "decided_by_authority", "expires_at",
        "revocation_scope", "inbound_message_body", "content_expires_at",
        "content_purged_at", "retained_until", "recorded_at",
        "ledger_sequence",
    ),
    "contacts.address_suppressions": (
        "suppression_id", "tenant_id", "address_id", "channel", "sender_id",
        "state", "transition_kind", "reason_code", "source", "actor_kind",
        "actor_principal_id", "decided_by_principal_id",
        "decided_by_authority", "retained_until", "recorded_at",
        "ledger_sequence",
    ),
    "contacts.address_usability_decisions": (
        "usability_decision_id", "tenant_id", "address_id", "state",
        "transition_kind", "proposed_by_actor_kind",
        "proposed_by_principal_id", "decided_by_principal_id",
        "decided_by_authority", "reason", "retained_until", "recorded_at",
        "ledger_sequence",
    ),
    "contacts.provider_reachability_events": (
        "reachability_event_id", "tenant_id", "address_id", "channel",
        "sender_id", "state", "provider_keyword", "source", "retained_until",
        "recorded_at", "ledger_sequence",
    ),
    # `migrations/0019_contact_permissions.sql`: the four dimensions, and the
    # three ways a contact is grouped without being copied.
    "contacts.branch_permissions": (
        "permission_id", "tenant_id", "branch_id", "principal_id",
        "dimension", "effect", "decided_by_principal_id",
        "decided_by_authority", "decided_by_actor_kind", "reason",
        "recorded_at", "updated_at",
    ),
    "contacts.contact_lists": (
        "list_id", "tenant_id", "branch_id", "name", "slug", "description",
        "created_by_principal_id",
    ),
    # Identifiers and provenance only. The absence of a name column here is
    # the schema's half of "a contact in two lists is still one record".
    "contacts.contact_list_members": (
        "tenant_id", "list_id", "contact_id", "added_by_principal_id",
        "added_at",
    ),
    "contacts.contact_tags": (
        "tag_id", "tenant_id", "name", "slug", "created_by_principal_id",
    ),
    "contacts.contact_tag_assignments": (
        "tenant_id", "tag_id", "contact_id", "assigned_by_principal_id",
        "assigned_at",
    ),
    "contacts.contact_segments": (
        "segment_id", "tenant_id", "scope_branch_id", "name", "slug",
        "definition", "rule_hash", "created_by_principal_id",
    ),
    # `migrations/0020_contact_import.sql`: the staging a file lands in, and
    # never the directory.
    "contacts.contact_import_batches": (
        "batch_id", "tenant_id", "target_branch_id", "source_name",
        "default_calling_code", "state", "row_count", "new_count",
        "duplicate_count", "collision_count", "staged_by_principal_id",
        "staged_by_actor_kind", "decided_by_principal_id",
        "decided_by_authority", "decided_by_actor_kind", "decided_at",
        "reason",
    ),
    "contacts.contact_import_rows": (
        "import_row_id", "tenant_id", "batch_id", "row_number",
        "display_name", "given_name", "family_name", "company_name",
        "job_title", "locale", "timezone", "external_reference", "channel",
        "address", "address_canonical", "classification",
        "matched_contact_id", "matched_branch_id", "duplicate_of_row_id",
        "asserts_consent", "consent_purposes", "capture_method",
        "captured_at", "captured_at_local", "capture_timezone",
        "jurisdiction", "disclosure_text", "disclosure_hash",
        "default_unchecked", "legal_basis", "consent_source",
        "consent_expires_at", "state", "applied_contact_id",
        "applied_address_id", "decided_by_principal_id",
        "decided_by_authority", "decided_by_actor_kind", "decided_at",
        "reason",
    ),
}

#: Tables the migration makes append-only. A test that asserts the audit
#: outlives the message has to be able to watch a rewrite fail, so the trigger
#: is emulated rather than assumed.
APPEND_ONLY = (
    "contacts.address_suppressions",
    "contacts.address_usability_decisions",
    "contacts.provider_reachability_events",
)

#: The one hole in the consent ledger's append-only rule: the retention purge
#: may redact the inbound body and stamp the purge time, and nothing else.
CONSENT_PURGE_COLUMNS = ("inbound_message_body", "content_purged_at")

#: `bigint generated always as identity` in 0018, one per ledger. The value is
#: the store's to hand out and never the caller's, because a caller who could
#: write it could change which row reads as current without updating a row --
#: which is the whole thing the append-only triggers exist to prevent.
IDENTITY_COLUMNS = {
    "contacts.consent_records": "ledger_sequence",
    "contacts.address_suppressions": "ledger_sequence",
    "contacts.address_usability_decisions": "ledger_sequence",
    "contacts.provider_reachability_events": "ledger_sequence",
}

#: Unique keys, tenant-scoped wherever the migration scopes them.
UNIQUE_KEYS = {
    "contacts.branches": (
        ("branch_id",),
        ("tenant_id", "path"),
        ("tenant_id", "parent_branch_id", "slug"),
    ),
    "contacts.contacts": (
        ("contact_id",),
    ),
    "contacts.contact_addresses": (
        ("address_id",),
        ("tenant_id", "channel", "address_normalized"),
    ),
    "contacts.consent_records": (
        ("consent_record_id",),
    ),
    "contacts.address_suppressions": (
        ("suppression_id",),
    ),
    "contacts.address_usability_decisions": (
        ("usability_decision_id",),
    ),
    "contacts.provider_reachability_events": (
        ("reachability_event_id",),
    ),
    "contacts.branch_permissions": (
        ("permission_id",),
        # One decision per principal, per branch, per dimension -- so a test
        # that asserts the four dimensions are independent is asserting
        # against a store that would have rejected a second, contradicting
        # row on the same one.
        ("tenant_id", "branch_id", "principal_id", "dimension"),
    ),
    "contacts.contact_lists": (
        ("list_id",),
        ("tenant_id", "slug"),
    ),
    "contacts.contact_list_members": (
        ("tenant_id", "list_id", "contact_id"),
    ),
    "contacts.contact_tags": (
        ("tag_id",),
        ("tenant_id", "slug"),
    ),
    "contacts.contact_tag_assignments": (
        ("tenant_id", "tag_id", "contact_id"),
    ),
    "contacts.contact_segments": (
        ("segment_id",),
        ("tenant_id", "slug"),
    ),
    "contacts.contact_import_batches": (
        ("batch_id",),
    ),
    "contacts.contact_import_rows": (
        ("import_row_id",),
        # One row per position in the file. A stager that wrote the same row
        # twice would be rejected here rather than doubling a count nobody
        # can reconcile afterwards.
        ("tenant_id", "batch_id", "row_number"),
    ),
}

#: (child column, parent table, parent column). The tenant is implied and
#: always checked alongside, because every one of these is composite.
FOREIGN_KEYS = {
    "contacts.branches": (
        ("parent_branch_id", "contacts.branches", "branch_id"),
    ),
    "contacts.contacts": (
        ("primary_branch_id", "contacts.branches", "branch_id"),
    ),
    "contacts.contact_addresses": (
        ("contact_id", "contacts.contacts", "contact_id"),
    ),
    # A consent record names both, so it cannot be filed against a person who
    # does not hold the address -- and neither reference resolves across
    # accounts.
    "contacts.consent_records": (
        ("contact_id", "contacts.contacts", "contact_id"),
        ("address_id", "contacts.contact_addresses", "address_id"),
    ),
    "contacts.address_suppressions": (
        ("address_id", "contacts.contact_addresses", "address_id"),
    ),
    "contacts.address_usability_decisions": (
        ("address_id", "contacts.contact_addresses", "address_id"),
    ),
    "contacts.provider_reachability_events": (
        ("address_id", "contacts.contact_addresses", "address_id"),
    ),
    # A permission over another account's branch does not resolve, so it
    # cannot be written -- which is what makes the cross-tenant permission
    # tests able to fail.
    "contacts.branch_permissions": (
        ("branch_id", "contacts.branches", "branch_id"),
    ),
    "contacts.contact_lists": (
        ("branch_id", "contacts.branches", "branch_id"),
    ),
    "contacts.contact_list_members": (
        ("list_id", "contacts.contact_lists", "list_id"),
        ("contact_id", "contacts.contacts", "contact_id"),
    ),
    "contacts.contact_tag_assignments": (
        ("tag_id", "contacts.contact_tags", "tag_id"),
        ("contact_id", "contacts.contacts", "contact_id"),
    ),
    "contacts.contact_segments": (
        ("scope_branch_id", "contacts.branches", "branch_id"),
    ),
    "contacts.contact_import_batches": (
        ("target_branch_id", "contacts.branches", "branch_id"),
    ),
    # Every match a staged row can hold. None of them resolve across accounts,
    # which is what makes "an import cannot dedupe against another account's
    # contacts" a property of the store rather than of the caller.
    "contacts.contact_import_rows": (
        ("batch_id", "contacts.contact_import_batches", "batch_id"),
        ("matched_contact_id", "contacts.contacts", "contact_id"),
        ("matched_branch_id", "contacts.branches", "branch_id"),
        ("applied_contact_id", "contacts.contacts", "contact_id"),
        ("applied_address_id", "contacts.contact_addresses", "address_id"),
    ),
}

_INSERT = re.compile(r"insert into ([\w.]+)\s*\(([^)]*)\)\s*values", re.I)
_SELECT_FROM = re.compile(r"\bfrom ([\w.]+)", re.I)
_UPDATE = re.compile(r"update ([\w.]+) set (.+?) where ", re.I)
_DELETE = re.compile(r"delete from ([\w.]+)", re.I)
_WHERE = re.compile(r"\bwhere (.+?)(?: order by | returning |$)", re.I)


class FakeCursor(object):
    def __init__(self, rows):
        self.rows = [dict(row) for row in rows]

    def fetchone(self):
        return dict(self.rows[0]) if self.rows else None

    def fetchall(self):
        return [dict(row) for row in self.rows]

    def __iter__(self):
        return iter(self.fetchall())


class FakeStore(object):
    """The durable side. Survives connections, the way a database does."""

    def __init__(self):
        self.tables = {name: [] for name in COLUMNS}
        #: One counter per identity column, standing in for the sequence
        #: Postgres attaches to it.
        self.sequences = {name: 0 for name in IDENTITY_COLUMNS}

    def rows(self, table):
        return self.tables[table]

    def next_identity(self, table):
        """The next sequence value, consumed whether or not the insert lands.

        Sequences do not roll back, and the property the ledgers rely on is
        that the numbers only ever go up -- not that they have no gaps.
        """
        self.sequences[table] += 1
        return self.sequences[table]


class FakeConnection(object):
    def __init__(self, store):
        self.store = store
        #: What ``app.current_org_id`` is set to. None means unset, which
        #: under forced row-level security makes every table look empty.
        self.org_context = None
        self.statements = []

    # -- statement dispatch ------------------------------------------------

    def execute(self, sql, params=()):
        flat = " ".join(str(sql).split())
        params = tuple(params or ())
        self.statements.append((flat, params))
        lowered = flat.lower()
        if lowered.startswith("select set_config"):
            self.org_context = params[0] or None
            return FakeCursor([])
        if lowered.startswith("insert into"):
            return self._insert(flat, params)
        if lowered.startswith("update "):
            return self._update(flat, params)
        if lowered.startswith("delete from"):
            return self._delete(flat, params)
        if lowered.startswith("select "):
            return self._select(flat, params)
        raise AssertionError("unsupported statement: %s" % flat)

    def cursor(self, *_args, **_kwargs):
        return _CursorAdapter(self)

    # -- the three mechanisms ---------------------------------------------

    def _visible(self, table):
        """Forced row-level security, applied before any caller predicate."""
        if not self.org_context:
            return []
        return [
            row for row in self.store.rows(table)
            if row.get("tenant_id") == self.org_context
        ]

    def _check_write_tenant(self, row):
        if row.get("tenant_id") != self.org_context:
            raise RowLevelSecurityViolation(
                "new row violates row-level security policy"
            )

    def _check_foreign_keys(self, table, row):
        for column, parent_table, parent_column in FOREIGN_KEYS.get(table, ()):
            value = row.get(column)
            if value is None:
                continue
            # The tenant travels inside the reference. A parent in another
            # account simply does not resolve.
            if not any(
                candidate.get(parent_column) == value
                and candidate.get("tenant_id") == row.get("tenant_id")
                for candidate in self.store.rows(parent_table)
            ):
                raise FakeIntegrityError(
                    "%s.%s has no matching (%s, tenant_id)"
                    % (table, column, parent_column)
                )

    def _check_unique(self, table, row, replacing=None):
        for key in UNIQUE_KEYS.get(table, ()):
            if any(row.get(column) is None for column in key):
                continue
            fingerprint = tuple(row.get(column) for column in key)
            for other in self.store.rows(table):
                if other is replacing:
                    continue
                if tuple(other.get(column) for column in key) == fingerprint:
                    raise FakeIntegrityError(
                        "duplicate key value violates unique constraint on %s"
                        % (key,)
                    )

    def _check_append_only(self, table, old, new):
        """The 0018 triggers, with the same two messages they raise.

        Emulated rather than trusted because "the audit outlives the message"
        is only a real claim against a store that would have refused the
        rewrite. A purge job handed the wrong update statement fails here the
        way it fails in Postgres.
        """
        if table in APPEND_ONLY:
            raise FakeIntegrityError("%s is append-only" % table)
        if table != "contacts.consent_records":
            return
        for column in COLUMNS[table]:
            if column in CONSENT_PURGE_COLUMNS:
                continue
            if old.get(column) != new.get(column):
                raise FakeIntegrityError(
                    "contacts.consent_records is append-only"
                )
        if new.get("inbound_message_body") is not None:
            raise FakeIntegrityError(
                "a consent content purge must redact the message body"
            )
        if new.get("content_purged_at") is None:
            raise FakeIntegrityError(
                "a consent content purge must stamp content_purged_at"
            )

    def _check_cycle_trigger(self, row):
        """The migration's `contacts.reject_cyclic_branch_move`, verbatim."""
        parent_id = row.get("parent_branch_id")
        if parent_id is None:
            return
        if parent_id == row.get("branch_id"):
            raise FakeIntegrityError("a branch cannot be its own parent")
        steps = 0
        ancestor = parent_id
        while ancestor is not None:
            steps += 1
            if steps > 128:
                raise FakeIntegrityError(
                    "branch ancestry exceeds the supported depth"
                )
            found = None
            for candidate in self.store.rows("contacts.branches"):
                if (
                    candidate.get("branch_id") == ancestor
                    and candidate.get("tenant_id") == row.get("tenant_id")
                ):
                    found = candidate
                    break
            ancestor = found.get("parent_branch_id") if found else None
            if ancestor == row.get("branch_id"):
                raise FakeIntegrityError(
                    "move would create cyclic branch ancestry"
                )

    # -- statements --------------------------------------------------------

    def _insert(self, flat, params):
        match = _INSERT.search(flat)
        if match is None:
            raise AssertionError("unparsable insert: %s" % flat)
        table = match.group(1)
        columns = [name.strip() for name in match.group(2).split(",")]
        row = {name: None for name in COLUMNS[table]}
        for name, value in zip(columns, params):
            row[name] = value
        identity = IDENTITY_COLUMNS.get(table)
        if identity is not None:
            if identity in columns:
                raise FakeIntegrityError(
                    'cannot insert a non-DEFAULT value into column "%s"'
                    % identity
                )
            row[identity] = self.store.next_identity(table)
        self._check_write_tenant(row)
        self._check_unique(table, row)
        self._check_foreign_keys(table, row)
        if table == "contacts.branches":
            self._check_cycle_trigger(row)
        self.store.rows(table).append(row)
        return FakeCursor([row])

    def _update(self, flat, params):
        match = _UPDATE.search(flat)
        if match is None:
            raise AssertionError("unparsable update: %s" % flat)
        table = match.group(1)
        assignments = _split_assignments(match.group(2))
        identity = IDENTITY_COLUMNS.get(table)
        if identity is not None and any(
            column == identity for column, _ in assignments
        ):
            raise FakeIntegrityError(
                'column "%s" can only be updated to DEFAULT' % identity
            )
        consumed = sum(1 for _, placeholder in assignments if placeholder)
        set_params = params[:consumed]
        where_params = params[consumed:]
        rows = self._match(table, flat, where_params)
        updated = []
        for row in rows:
            candidate = dict(row)
            index = 0
            for column, placeholder in assignments:
                if placeholder:
                    candidate[column] = set_params[index]
                    index += 1
            self._check_write_tenant(candidate)
            self._check_unique(table, candidate, replacing=row)
            self._check_foreign_keys(table, candidate)
            self._check_append_only(table, row, candidate)
            if table == "contacts.branches":
                self._check_cycle_trigger(candidate)
            row.update(candidate)
            updated.append(row)
        return FakeCursor(updated)

    def _delete(self, flat, params):
        """Revocation. Filtered by row-level security before any predicate.

        Deleting through `_match` rather than through the store directly is
        the point: a revoke that forgot its tenant predicate still cannot
        reach another account's rows here, the same way it cannot in Postgres.
        """
        match = _DELETE.search(flat)
        if match is None:
            raise AssertionError("unparsable delete: %s" % flat)
        table = match.group(1)
        if table in APPEND_ONLY or table == "contacts.consent_records":
            raise FakeIntegrityError("%s is append-only" % table)
        removed = self._match(table, flat, params)
        rows = self.store.rows(table)
        for row in removed:
            rows.remove(row)
        return FakeCursor(removed)

    def _select(self, flat, params):
        match = _SELECT_FROM.search(flat)
        if match is None:
            raise AssertionError("unparsable select: %s" % flat)
        return FakeCursor(self._match(match.group(1), flat, params))

    def _match(self, table, flat, params):
        where = _WHERE.search(flat)
        clauses = _split_clauses(where.group(1)) if where else []
        rows = []
        for row in self._visible(table):
            index = 0
            keep = True
            for clause in clauses:
                keep, index = _clause_matches(clause, row, params, index) if keep \
                    else (False, _advance(clause, index))
            if keep:
                rows.append(row)
        if " order by " in flat.lower():
            key = flat.lower().split(" order by ", 1)[1].split(" returning ")[0]
            for column in reversed([name.strip() for name in key.split(",")]):
                if column in COLUMNS[table]:
                    rows = sorted(rows, key=lambda r: (r.get(column) or "",))
        return rows


class _CursorAdapter(object):
    """`libs.db.Database.set_org_context` reaches for a cursor context."""

    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def execute(self, sql, params=()):
        return self.connection.execute(sql, params)


class FakeDatabase(object):
    """The `libs.db.Database` surface the repositories in this repo expect."""

    def __init__(self, store=None):
        self.store = store or FakeStore()
        self.connections = []

    def _open(self):
        connection = FakeConnection(self.store)
        self.connections.append(connection)
        return connection

    @contextmanager
    def connection(self):
        yield self._open()

    @contextmanager
    def transaction(self):
        yield self._open()

    def set_org_context(self, conn, organization_id):
        conn.execute(
            "select set_config('app.current_org_id', %s, true)",
            (organization_id or "",),
        )

    def statements(self):
        return [
            statement
            for connection in self.connections
            for statement in connection.statements
        ]


# -- clause parsing --------------------------------------------------------

def _split_assignments(fragment):
    assignments = []
    for part in fragment.split(","):
        column, _, value = part.partition("=")
        assignments.append((column.strip(), "%s" in value))
    return assignments


def _split_clauses(fragment):
    return [clause.strip() for clause in re.split(r"\s+and\s+", fragment)]


def _advance(clause, index):
    return index + clause.count("%s")


def _clause_matches(clause, row, params, index):
    lowered = clause.lower()
    if lowered.endswith(" is null"):
        column = clause[: -len(" is null")].strip()
        return row.get(column) is None, index
    if lowered.endswith(" is not null"):
        column = clause[: -len(" is not null")].strip()
        return row.get(column) is not None, index
    if " = any(%s)" in lowered:
        column = clause.lower().split(" = any(%s)")[0].strip()
        return row.get(column) in tuple(params[index] or ()), index + 1
    if " <= %s" in lowered:
        # The retention sweep asks for bodies whose content clock has run
        # out, and pushing that predicate into the statement is the point --
        # a purge that filtered in Python would scan every consent row ever
        # written.
        column = clause[: lowered.index(" <= %s")].strip()
        value = _column_value(column, row)
        return value is not None and value <= params[index], index + 1
    if " like %s" in lowered:
        column = clause[: lowered.index(" like %s")].strip()
        value = _column_value(column, row)
        return _like(value, params[index]), index + 1
    if " = %s" in lowered:
        column = clause[: lowered.index(" = %s")].strip()
        return _column_value(column, row) == params[index], index + 1
    raise AssertionError("unsupported where clause: %s" % clause)


def _column_value(expression, row):
    if expression.lower().startswith("lower(") and expression.endswith(")"):
        value = row.get(expression[len("lower("):-1].strip())
        return value.lower() if isinstance(value, str) else value
    return row.get(expression)


def _like(value, pattern):
    if value is None:
        return False
    return re.match(
        "^" + ".*".join(re.escape(part) for part in pattern.split("%")) + "$",
        value,
        re.S,
    ) is not None
