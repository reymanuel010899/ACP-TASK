"""Migration runner (unit U1, KTD2).

Intentionally minimal (no Alembic, no ORM models to key off, KTD1/KTD2):
read ``migrations/*.sql`` sorted by filename, diff against a
``schema_migrations`` table (created here if missing), apply every file not
yet recorded -- each inside its own transaction -- and record it as applied.
Re-running is a no-op: nothing pending means nothing runs.

Run ``infra/roles.sql`` once before the first migration (see that file's
header) so every schema this runner creates already has its service role's
grants waiting via ``ALTER DEFAULT PRIVILEGES``.

Usage::

    python -m tools.migrate                       # DATABASE_URL env var
    python -m tools.migrate --database-url ...
    python -m tools.migrate --migrations-dir path/to/migrations

Connects with an owner/admin DSN (the role that will own the tables it
creates) -- never one of the least-privilege service roles from
``infra/roles.sql``; those roles get access to the tables this runner
creates via the default-privilege grants in that file, not by owning them.
"""

import argparse
import os
import sys
from pathlib import Path
from typing import List, Optional

import psycopg

DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"

_CREATE_TRACKING_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename    text PRIMARY KEY,
    applied_at  timestamptz NOT NULL DEFAULT now()
);
"""


def _pending_migrations(migrations_dir: Path, applied: set) -> List[Path]:
    files = sorted(p for p in migrations_dir.glob("*.sql") if p.is_file())
    return [f for f in files if f.name not in applied]


def _applied_filenames(conn) -> set:
    with conn.cursor() as cur:
        cur.execute("SELECT filename FROM schema_migrations")
        return {row[0] for row in cur.fetchall()}


def run_migrations(
    database_url: Optional[str] = None,
    migrations_dir: Optional[Path] = None,
) -> List[str]:
    """Apply every pending migration in ``migrations_dir`` in filename order.

    Returns the list of filenames actually applied during this call (empty
    if everything was already applied -- the idempotent no-op case).

    Each migration file runs inside its own transaction: a failure partway
    through a file rolls back that file's statements entirely and the file
    is NOT recorded in ``schema_migrations``, so a fixed version of the same
    file (or the same file re-run after the underlying issue is resolved)
    will be attempted again on the next run.
    """
    dsn = database_url or os.environ.get("DATABASE_URL", "")
    migrations_dir = Path(migrations_dir) if migrations_dir else DEFAULT_MIGRATIONS_DIR

    applied_now: List[str] = []

    with psycopg.connect(dsn) as conn:
        # Tracking table itself is created/ensured outside the per-file
        # transactions below, in its own auto-committing statement.
        with conn.cursor() as cur:
            cur.execute(_CREATE_TRACKING_TABLE)
        conn.commit()

        already_applied = _applied_filenames(conn)
        # _applied_filenames issued a bare SELECT, which (autocommit is off)
        # left an implicit transaction open on this connection. Without
        # closing it here, each `with conn.transaction():` below would be
        # entered as a *nested* transaction (a savepoint) inside that
        # still-open outer transaction rather than its own independent,
        # already-committed unit of work -- so a later file's failure would
        # roll back every earlier file's supposedly-already-applied
        # migration too, not just its own.
        conn.commit()
        pending = _pending_migrations(migrations_dir, already_applied)

        for path in pending:
            sql = path.read_text()
            try:
                with conn.transaction():
                    with conn.cursor() as cur:
                        if sql.strip():
                            cur.execute(sql)
                        cur.execute(
                            "INSERT INTO schema_migrations (filename) VALUES (%s)",
                            (path.name,),
                        )
            except Exception:
                # psycopg's conn.transaction() context already rolled back
                # every statement in this file on exception; re-raise so the
                # caller (CLI or test) sees the failure instead of silently
                # continuing to the next file.
                raise
            applied_now.append(path.name)

    return applied_now


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Apply pending migrations/*.sql files.")
    parser.add_argument(
        "--database-url",
        default=None,
        help="Postgres connection string (defaults to the DATABASE_URL env var).",
    )
    parser.add_argument(
        "--migrations-dir",
        default=None,
        help="Directory of *.sql migration files (defaults to migrations/ at the repo root).",
    )
    args = parser.parse_args(argv)

    dsn = args.database_url or os.environ.get("DATABASE_URL")
    if not dsn:
        parser.error("--database-url or the DATABASE_URL env var is required")

    applied = run_migrations(database_url=dsn, migrations_dir=args.migrations_dir)
    if applied:
        print(f"Applied {len(applied)} migration(s): {', '.join(applied)}")
    else:
        print("No pending migrations.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
