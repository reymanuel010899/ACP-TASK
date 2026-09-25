from pathlib import Path


SQL = Path("migrations/0024_whatsapp.sql").read_text().lower()


def test_whatsapp_state_is_tenant_scoped_and_window_is_fixed():
    assert "interval '24 hours'" in SQL
    assert SQL.count("force row level security") == 2
    assert "content_sid ~ '^hx[0-9a-fa-f]{32}$'" in SQL
