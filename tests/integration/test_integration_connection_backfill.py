from services.oauth.repository import OAuthRepository
from scripts.backfill_integration_connections import backfill_connections


def test_google_backfill_is_stable_idempotent_and_blocks_unknown_tenant(tmp_path):
    repository = OAuthRepository(str(tmp_path / "oauth.sqlite3"))
    repository.upsert_connection(
        "user:alice", "google", "cred-a", ["scope-a"], ["gmail.read"], 10
    )
    repository.upsert_connection(
        "user:orphan", "google", "cred-b", ["scope-b"], ["drive.read"], 11
    )

    first = backfill_connections(
        repository,
        tenant_resolver=lambda principal_id: (
            "org:acme" if principal_id == "user:alice" else None
        ),
        now_ts=20,
    )
    second = backfill_connections(
        repository,
        tenant_resolver=lambda principal_id: (
            "org:acme" if principal_id == "user:alice" else None
        ),
        now_ts=30,
    )

    assert first["source_count"] == second["source_count"] == 2
    assert first["checksum"] == second["checksum"]
    assert second["created_count"] == 0
    assert second["preserved_count"] == 1
    assert second["blocked_count"] == 1
    migrated = repository.list_installations("org:acme", "user:alice", "google")
    assert len(migrated) == 1
    assert migrated[0]["credential_id"] == "cred-a"
