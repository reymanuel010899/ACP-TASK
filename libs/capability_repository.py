"""Postgres-backed storage for the capability catalog (unit U2, ``catalog``
schema -- ``migrations/0002_catalog.sql``).

Today ``capability_id`` is a bare string repeated across five different
in-memory stores with no catalog behind it -- nothing stops
``"terraform.generate"`` from being spelled two ways in two services. This
module gives it one real home and validates the id shape at the repository
layer before it ever reaches the database, using the exact same pattern
``schemas/capability.schema.json`` already declares (RFC-0001) -- so a
capability that would fail RFC-0001 schema validation can never be inserted
here either.

Uses ``libs.db.Database`` for every connection -- no hand-rolled psycopg
connection handling here (KTD1).
"""

import json
import re

from typing import List, Optional

import psycopg
from psycopg.rows import dict_row

from libs.db import Database

#: Verbatim from schemas/capability.schema.json's "id" pattern: stable,
#: dot-namespaced capability identifier, e.g. 'terraform.generate'. Kept as a
#: literal copy (not imported from the schema file) since the schema is JSON
#: Schema data, not Python, and this repository's only dependency should be
#: libs/db.py (KTD1) -- see tests/lib/test_capability_repository.py for a
#: test that keeps the two in sync.
CAPABILITY_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*(\.[a-z0-9][a-z0-9_-]*)+$")


class CapabilityRepository(object):
    """Repository for ``catalog.capabilities``."""

    def __init__(self, db=None):
        # type: (Optional[Database]) -> None
        self._db = db or Database()

    def _validate_capability_id(self, capability_id):
        # type: (str) -> None
        if not capability_id or not CAPABILITY_ID_PATTERN.match(capability_id):
            raise ValueError(
                "invalid capability_id (must match %s): %r"
                % (CAPABILITY_ID_PATTERN.pattern, capability_id)
            )

    def register_capability(
        self,
        capability_id,
        version,
        description,
        input_schema=None,
        output_schema=None,
        extensions=None,
    ):
        # type: (str, str, str, Optional[dict], Optional[dict], Optional[dict]) -> dict
        """Register a new capability; return the stored row.

        Raises ``ValueError`` if ``capability_id`` doesn't match the
        dot-namespaced pattern (RFC-0001), or if it's already registered.
        """
        self._validate_capability_id(capability_id)

        with self._db.transaction() as conn:
            try:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        """
                        INSERT INTO catalog.capabilities
                            (capability_id, version, description,
                             input_schema, output_schema, extensions)
                        VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb)
                        RETURNING *
                        """,
                        (
                            capability_id,
                            version,
                            description,
                            _dumps_or_null(input_schema),
                            _dumps_or_null(output_schema),
                            json.dumps(extensions or {}),
                        ),
                    )
                    return cur.fetchone()
            except psycopg.errors.UniqueViolation:
                raise ValueError(
                    "capability_id already registered: %s" % capability_id
                )

    def get_capability(self, capability_id):
        # type: (str) -> Optional[dict]
        """Fetch a capability row, or ``None`` if unknown."""
        with self._db.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM catalog.capabilities WHERE capability_id = %s",
                    (capability_id,),
                )
                return cur.fetchone()

    def capability_exists(self, capability_id):
        # type: (str) -> bool
        """Check if a capability exists."""
        with self._db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM catalog.capabilities WHERE capability_id = %s",
                    (capability_id,),
                )
                return cur.fetchone() is not None

    def list_capabilities(self):
        # type: () -> List[dict]
        """All registered capabilities, ordered by id."""
        with self._db.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM catalog.capabilities ORDER BY capability_id"
                )
                return cur.fetchall()

    def update_capability(
        self,
        capability_id,
        version=None,
        description=None,
        input_schema=None,
        output_schema=None,
        extensions=None,
    ):
        # type: (str, Optional[str], Optional[str], Optional[dict], Optional[dict], Optional[dict]) -> Optional[dict]
        """Update the given fields of an existing capability (``None``
        arguments leave the current value unchanged); return the updated
        row, or ``None`` if ``capability_id`` doesn't exist."""
        with self._db.transaction() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    UPDATE catalog.capabilities
                    SET version = COALESCE(%s, version),
                        description = COALESCE(%s, description),
                        input_schema = COALESCE(%s::jsonb, input_schema),
                        output_schema = COALESCE(%s::jsonb, output_schema),
                        extensions = COALESCE(%s::jsonb, extensions)
                    WHERE capability_id = %s
                    RETURNING *
                    """,
                    (
                        version,
                        description,
                        _dumps_or_null(input_schema),
                        _dumps_or_null(output_schema),
                        _dumps_or_null(extensions),
                        capability_id,
                    ),
                )
                return cur.fetchone()

    def delete_capability(self, capability_id):
        # type: (str) -> bool
        """Delete a capability; return whether a row was actually removed."""
        with self._db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM catalog.capabilities WHERE capability_id = %s",
                    (capability_id,),
                )
                return cur.rowcount > 0


def _dumps_or_null(value):
    # type: (Optional[dict]) -> Optional[str]
    """JSON-encode a dict for a ``jsonb`` column parameter, preserving
    ``None`` (SQL NULL) rather than encoding it as the JSON string ``"null"``
    -- ``input_schema``/``output_schema`` are nullable columns."""
    if value is None:
        return None
    return json.dumps(value)
