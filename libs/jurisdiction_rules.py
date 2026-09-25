"""Postgres access for verified, hot-patchable communication rules."""


class JurisdictionRuleRepository:
    def __init__(self, db):
        self.db = db

    def active_rows(self, tenant_id):
        with self.db.connection() as conn:
            conn.execute("select set_config('app.current_org_id', %s, true)", (tenant_id,))
            rows = conn.execute(
                """select rule_id,jurisdiction,channel,purpose,priority,
                          contact_hour_start,contact_hour_end,registry_max_age_seconds
                   from compliance.jurisdiction_rules
                   where tenant_id=%s and enabled and verified_at is not null""",
                (tenant_id,),
            ).fetchall()
        columns = (
            "rule_id", "jurisdiction", "channel", "purpose", "priority",
            "contact_hour_start", "contact_hour_end", "registry_max_age_seconds",
        )
        return [dict(zip(columns, row), enabled=True) for row in rows]
