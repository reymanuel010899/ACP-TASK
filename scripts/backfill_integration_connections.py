"""Idempotent legacy OAuth connection backfill.

Rows without a provable tenant are recorded as blocked and are never assigned
to a guessed/default tenant.
"""

import hashlib
import json


def backfill_connections(repository, tenant_resolver, now_ts, app_id="google:tessera"):
    rows = repository.legacy_connections()
    source = json.dumps(rows, sort_keys=True, separators=(",", ":"))
    checksum = hashlib.sha256(source.encode("utf-8")).hexdigest()
    created = preserved = blocked = 0

    for row in rows:
        legacy_key = "%s:%s" % (row["principal_id"], row["provider"])
        prior = repository.legacy_mapping(legacy_key)
        tenant_id = tenant_resolver(row["principal_id"])
        if not tenant_id:
            repository.record_legacy_mapping(
                legacy_key,
                prior["connection_id"] if prior else None,
                "migration_blocked",
                checksum,
                now_ts,
                error_code="tenant_unproven",
            )
            blocked += 1
            continue

        connection = repository.upsert_installation(
            tenant_id=tenant_id,
            principal_id=row["principal_id"],
            provider=row["provider"],
            app_id=app_id,
            credential_id=row["credential_id"],
            granted_scopes=row["granted_scopes"],
            enabled_capabilities=row["enabled_capabilities"],
            now_ts=now_ts,
            connection_id=prior["connection_id"] if prior else None,
        )
        repository.record_legacy_mapping(
            legacy_key,
            connection["connection_id"],
            "migrated",
            checksum,
            now_ts,
        )
        if prior:
            preserved += 1
        else:
            created += 1

    return {
        "source_count": len(rows),
        "created_count": created,
        "preserved_count": preserved,
        "blocked_count": blocked,
        "checksum": checksum,
    }
