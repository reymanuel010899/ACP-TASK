# migrations/

Flat, numbered `.sql` files (KTD7), e.g. `0001_identity.sql`,
`0002_catalog.sql`, ... Sequential numbering directly encodes the schemas'
dependency order (identity -> catalog -> vault/audit -> registry/trust ->
marketplace) instead of needing a second ordering mechanism across
subdirectories.

Applied in filename order by `tools/migrate.py`, which tracks what has run in
a `schema_migrations(filename, applied_at)` table it creates if missing.
Re-running is a no-op: already-applied filenames are skipped.

Run `infra/roles.sql` once before the first migration (and it is safe to
re-run after any later migration adds a new schema -- see the comment at the
top of that file).

    psql "$DATABASE_URL" -f infra/roles.sql
    python -m tools.migrate

This directory starts empty (U1). Schema DDL lands here starting with U2
(`0001_identity.sql`, `0002_catalog.sql`).

`0010_integration_connections.sql` is the expand step for provider-neutral,
tenant-bound installations. Deploy it before enabling dual-write. Run the
idempotent connection backfill, verify counts/checksums and resolve every
`migration_blocked` row before cutover. Rollback disables dual-write/read
preference only; it never deletes the new connection or credential records.
