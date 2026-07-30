"""Tests for libs/capability_repository.py (unit U2, ``catalog`` schema).

Needs a real Postgres with migrations/0002_catalog.sql already applied --
see tests/lib/test_identity_repository.py's module docstring for the same
setup contract (`infra/roles.sql` + `python -m tools.migrate` against
`DATABASE_URL`). Skipped (not failed) if unreachable or unmigrated.

Test scenarios (mirroring the plan's U2 spec):
    * Happy path -- capability catalog CRUD
    * Edge case  -- capability_id pattern validation rejects/accepts
"""

import os
import uuid

import psycopg
import pytest

from libs.db import Database
from libs.capability_repository import CAPABILITY_ID_PATTERN, CapabilityRepository

DEFAULT_TEST_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/agenttrust"


@pytest.fixture(scope="module")
def pg_dsn():
    dsn = os.environ.get("DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
    try:
        with psycopg.connect(dsn, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM information_schema.schemata WHERE schema_name = 'catalog'"
                )
                if cur.fetchone() is None:
                    pytest.skip(
                        "catalog schema not present -- run `python -m tools.migrate` "
                        "(after infra/roles.sql) against this DATABASE_URL first."
                    )
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(
            f"Postgres not reachable at {dsn!r} ({exc}). Bring up a Postgres 16 "
            f"instance, run infra/roles.sql + `python -m tools.migrate`, and "
            f"point DATABASE_URL at it to run tests/lib/test_capability_repository.py."
        )
    return dsn


@pytest.fixture()
def run_id():
    return uuid.uuid4().hex[:8]


@pytest.fixture()
def db(pg_dsn):
    database = Database(dsn=pg_dsn)
    yield database
    database.close()


@pytest.fixture()
def repo(db):
    return CapabilityRepository(db)


def _cleanup(pg_dsn, capability_ids):
    if not capability_ids:
        return
    with psycopg.connect(pg_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM catalog.capabilities WHERE capability_id = ANY(%s)",
                (list(capability_ids),),
            )


# ---------------------------------------------------------------------------
# Happy path -- capability catalog CRUD.
# ---------------------------------------------------------------------------


def test_capability_crud(pg_dsn, repo, run_id):
    cap_id = f"terraform.generate_{run_id}"
    try:
        created = repo.register_capability(
            cap_id,
            "1.0.0",
            "Generate Terraform configuration",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            extensions={"vendor.example/tier": "gold"},
        )
        assert created["capability_id"] == cap_id
        assert created["version"] == "1.0.0"
        assert created["input_schema"] == {"type": "object"}
        assert created["extensions"] == {"vendor.example/tier": "gold"}

        fetched = repo.get_capability(cap_id)
        assert fetched is not None
        assert fetched["description"] == "Generate Terraform configuration"
        assert repo.capability_exists(cap_id) is True
        assert repo.capability_exists(f"nonexistent.capability_{run_id}") is False

        all_caps = repo.list_capabilities()
        assert any(c["capability_id"] == cap_id for c in all_caps)

        # duplicate registration is rejected, not silently overwritten
        with pytest.raises(ValueError):
            repo.register_capability(cap_id, "1.0.0", "duplicate")

        updated = repo.update_capability(
            cap_id, version="2.0.0", description="Generate Terraform v2"
        )
        assert updated["version"] == "2.0.0"
        assert updated["description"] == "Generate Terraform v2"
        # fields not passed to update_capability are left unchanged
        assert updated["input_schema"] == {"type": "object"}

        deleted = repo.delete_capability(cap_id)
        assert deleted is True
        assert repo.get_capability(cap_id) is None
        assert repo.delete_capability(cap_id) is False  # already gone
    finally:
        _cleanup(pg_dsn, [cap_id])


def test_capability_without_optional_schemas(pg_dsn, repo, run_id):
    """input_schema/output_schema are optional (nullable) columns."""
    cap_id = f"simple.capability_{run_id}"
    try:
        created = repo.register_capability(cap_id, "1.0", "a minimal capability")
        assert created["input_schema"] is None
        assert created["output_schema"] is None
        assert created["extensions"] == {}
    finally:
        _cleanup(pg_dsn, [cap_id])


# ---------------------------------------------------------------------------
# Edge case -- capability_id pattern validation.
# ---------------------------------------------------------------------------


def test_capability_id_pattern_matches_rfc0001_schema():
    """Sanity check the compiled pattern is byte-for-byte the one declared
    in schemas/capability.schema.json, so the two can never silently drift
    apart."""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    schema_path = os.path.join(repo_root, "schemas", "capability.schema.json")
    if not os.path.exists(schema_path):
        pytest.skip("schemas/capability.schema.json not found")

    import json

    with open(schema_path) as f:
        schema = json.load(f)

    expected_pattern = schema["properties"]["id"]["pattern"]
    assert CAPABILITY_ID_PATTERN.pattern == expected_pattern


def test_capability_id_validation_rejects_invalid_and_accepts_valid(pg_dsn, repo, run_id):
    # No dot-namespace: invalid per RFC-0001's pattern.
    with pytest.raises(ValueError):
        repo.register_capability("nodotnamespace", "1.0", "invalid id")

    # Uppercase, leading dot, empty segment: also invalid.
    for invalid_id in ("Terraform.Generate", ".leadingdot", "trailing.", ""):
        with pytest.raises(ValueError):
            repo.register_capability(invalid_id, "1.0", "invalid id")

    valid_id = f"terraform.generate.{run_id}"
    try:
        created = repo.register_capability(valid_id, "1.0", "valid dot-namespaced id")
        assert created["capability_id"] == valid_id
    finally:
        _cleanup(pg_dsn, [valid_id])
