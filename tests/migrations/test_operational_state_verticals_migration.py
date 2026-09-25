from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SQL = (ROOT / "migrations/0031_operational_state_verticals.sql").read_text(
    encoding="utf-8"
).lower()


def test_voice_session_and_encrypted_transcript_metadata_are_durable():
    assert "create table voice.sessions" in SQL
    assert "create table voice.transcript_events" in SQL
    assert "content_ciphertext text not null" in SQL
    assert "content_digest text not null" in SQL
    assert "content_expires_at timestamptz not null" in SQL


def test_vertical_operational_tables_use_canonical_strict_rls():
    assert "app.tenant_id" not in SQL
    assert "app.current_org_id" in SQL
    assert "nullif(current_setting" in SQL
    for table in (
        "billing.spend_budgets",
        "billing.spend_reservations",
        "billing.brand_daily_volume",
        "twilio.identities",
        "twilio.dispatch_ledger",
        "twilio.provider_events",
        "twilio.effect_verdicts",
        "twilio.whatsapp_session_windows",
        "twilio.whatsapp_templates",
    ):
        assert f"'{table}'" in SQL


def test_voice_tables_are_forced_rls():
    for table in ("voice.sessions", "voice.transcript_events"):
        assert f"alter table {table} enable row level security" in SQL
        assert f"alter table {table} force row level security" in SQL

