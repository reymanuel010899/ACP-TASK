from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "migrations" / "0027_contact_ledger_sequence_repair.sql"
)

TABLES = (
    "consent_records",
    "address_suppressions",
    "address_usability_decisions",
    "provider_reachability_events",
)


def _flat():
    return " ".join(MIGRATION.read_text().split()).lower()


def test_repair_adds_database_assigned_order_to_every_contact_ledger():
    sql = _flat()

    for table in TABLES:
        assert (
            f"alter table contacts.{table} add column if not exists "
            "ledger_sequence bigint generated always as identity"
        ) in sql


def test_repair_rebuilds_every_current_state_index_with_the_tiebreaker():
    sql = _flat()

    for index in (
        "consent_records_current",
        "address_suppressions_current",
        "address_usability_current",
        "provider_reachability_current",
    ):
        assert f"drop index if exists contacts.{index}" in sql
        assert f"create index {index}" in sql
    assert sql.count("ledger_sequence desc") == len(TABLES)
