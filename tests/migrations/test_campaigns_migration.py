from pathlib import Path


SQL = (Path(__file__).parents[2] / "migrations" / "0025_campaigns.sql").read_text()


def test_campaign_tables_are_tenant_scoped_and_forced_rls():
    for table in ("campaigns", "campaign_cohort", "campaign_effects", "campaign_audit"):
        assert "alter table campaign.%s enable row level security" % table in SQL.lower()
        assert "alter table campaign.%s force row level security" % table in SQL.lower()
    assert "tenant_id" in SQL


def test_campaign_effects_dedupe_canonical_contact_and_channel():
    assert "unique (tenant_id, campaign_id, contact_id, channel)" in SQL.lower()
