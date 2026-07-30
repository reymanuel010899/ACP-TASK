"""PostgreSQL authority for tenant-bound provider installations."""

import json
import uuid


class IntegrationConnectionConflict(Exception):
    pass


class IntegrationConnectionRepository(object):
    def __init__(self, db):
        self.db = db

    def upsert(
        self,
        tenant_id,
        owner_principal_id,
        provider,
        app_id,
        credential_id,
        effective_scopes,
        enabled_capabilities,
        connection_id=None,
        team_id=None,
        team_name=None,
        enterprise_id=None,
        bot_user_id=None,
        credential_version=1,
    ):
        if not tenant_id:
            raise ValueError("tenant_id is required")
        if provider == "slack" and not team_id:
            raise ValueError("team_id is required for Slack installations")
        resolved_id = connection_id or _stable_connection_id(
            provider, app_id, team_id, owner_principal_id
        )
        with self.db.transaction() as conn:
            existing = conn.execute(
                """
                select tenant_id, owner_principal_id
                from integrations.connections
                where connection_id = %s
                   or (provider = 'slack' and provider = %s
                       and app_id = %s and team_id = %s)
                for update
                """,
                (resolved_id, provider, app_id, team_id),
            ).fetchone()
            if existing and (
                existing[0] != tenant_id or existing[1] != owner_principal_id
            ):
                raise IntegrationConnectionConflict(
                    "provider installation belongs to another tenant or owner"
                )
            row = conn.execute(
                """
                insert into integrations.connections(
                    connection_id, tenant_id, owner_principal_id, provider,
                    app_id, team_id, team_name, enterprise_id, bot_user_id, credential_id,
                    credential_version, effective_scopes, enabled_capabilities
                ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
                on conflict (connection_id) do update set
                    credential_id = excluded.credential_id,
                    credential_version = excluded.credential_version,
                    effective_scopes = excluded.effective_scopes,
                    enabled_capabilities = excluded.enabled_capabilities,
                    enterprise_id = excluded.enterprise_id,
                    bot_user_id = excluded.bot_user_id,
                    status = 'connected', updated_at = now(), disconnected_at = null
                returning connection_id, tenant_id, owner_principal_id, provider,
                          app_id, team_id, team_name, enterprise_id, bot_user_id,
                          credential_id, credential_version, effective_scopes,
                          enabled_capabilities, status
                """,
                (
                    resolved_id,
                    tenant_id,
                    owner_principal_id,
                    provider,
                    app_id,
                    team_id,
                    team_name,
                    enterprise_id,
                    bot_user_id,
                    credential_id,
                    credential_version,
                    json.dumps(sorted(set(effective_scopes))),
                    json.dumps(sorted(set(enabled_capabilities))),
                ),
            ).fetchone()
        return _record(row)

    def get(self, tenant_id, connection_id):
        with self.db.connection() as conn:
            row = conn.execute(
                """
                select connection_id, tenant_id, owner_principal_id, provider,
                       app_id, team_id, team_name, enterprise_id, bot_user_id,
                       credential_id, credential_version, effective_scopes,
                       enabled_capabilities, status
                from integrations.connections
                where tenant_id = %s and connection_id = %s
                """,
                (tenant_id, connection_id),
            ).fetchone()
        return _record(row)

    def list_for_owner(self, tenant_id, owner_principal_id, provider=None):
        sql = """
            select connection_id, tenant_id, owner_principal_id, provider,
                   app_id, team_id, team_name, enterprise_id, bot_user_id,
                   credential_id, credential_version, effective_scopes,
                   enabled_capabilities, status
            from integrations.connections
            where tenant_id = %s and owner_principal_id = %s
        """
        params = [tenant_id, owner_principal_id]
        if provider:
            sql += " and provider = %s"
            params.append(provider)
        sql += " order by provider, team_id nulls first, connection_id"
        with self.db.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_record(row) for row in rows]


def _stable_connection_id(provider, app_id, team_id, owner_principal_id):
    identity = ":".join(
        [provider, app_id, team_id or "", owner_principal_id if not team_id else ""]
    )
    return "conn:%s" % uuid.uuid5(uuid.NAMESPACE_URL, "tessera:%s" % identity)


def _record(row):
    if row is None:
        return None
    keys = (
        "connection_id", "tenant_id", "owner_principal_id", "provider",
        "app_id", "team_id", "team_name", "enterprise_id", "bot_user_id",
        "credential_id", "credential_version", "effective_scopes",
        "enabled_capabilities", "status",
    )
    return dict(zip(keys, row))
