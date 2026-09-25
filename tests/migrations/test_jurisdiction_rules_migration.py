from pathlib import Path


SQL = Path("migrations/0022_jurisdiction_rules.sql").read_text().lower()


def test_rules_cannot_be_enabled_without_verification_and_source():
    assert "not enabled or (verified_at is not null and source_uri is not null)" in SQL
    assert "force row level security" in SQL
