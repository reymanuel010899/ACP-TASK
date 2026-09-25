# Operational SQLite fixtures

Fixtures in this directory represent source databases accepted by the U3
importer. They must contain synthetic values only: no real session hashes,
OAuth state, credentials, phone numbers, contact data, message bodies, or
transcripts.

Each fixture added during implementation must document:

- the source repository and schema version it represents;
- the domain family and expected PostgreSQL projection;
- the expected imported, conflicting, and quarantined row counts;
- whether rerunning the import is expected to be a no-op;
- the interruption checkpoint used by resume tests.

Generate fixtures through test helpers rather than committing transient WAL,
shared-memory, or journal files.
