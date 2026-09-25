"""PostgreSQL authority for tenant-bound provider installations."""

import json
import uuid

from libs.integrations.catalog import (
    GEO_DIMENSION,
    SENDER_DIMENSION,
    TEMPLATE_DIMENSION,
    VerifiedAccountState,
    VerifiedSender,
    derive_synthetic_scopes,
    synthetic_scope,
)


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

    def list_for_tenant(self, tenant_id, provider=None, usable_only=True):
        sql = """
            select connection_id, tenant_id, owner_principal_id, provider,
                   app_id, team_id, team_name, enterprise_id, bot_user_id,
                   credential_id, credential_version, effective_scopes,
                   enabled_capabilities, status
            from integrations.connections
            where tenant_id = %s
        """
        params = [tenant_id]
        if provider:
            sql += " and provider = %s"
            params.append(provider)
        if usable_only:
            sql += " and status = 'connected'"
        sql += " order by provider, team_id nulls first, connection_id"
        with self.db.connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_record(row) for row in rows]


class ProviderControlPlaneRepository(object):
    """Verified account state, and the synthetic scopes derived from it.

    Every write here ends in one place: recompute the connection's effective
    scopes from what the account currently, verifiably holds. That is the only
    lever a non-OAuth provider has on authority, and it is deliberately the
    only one this repository pulls — the credential version belongs to the
    sealed secret and is left alone by every method except the one that
    replaces it.
    """

    def __init__(self, db):
        self.db = db

    def record_verified_account(
        self, tenant_id, connection_id, provider, provider_account_id, state
    ):
        """Persist an account verification and re-derive its authority.

        Called at connection time and on every re-verification. An account
        that came back anything other than verified keeps its rows but derives
        no scopes, so its effects stop dispatching without losing the record
        of what it used to be allowed to do.
        """
        state = state if isinstance(state, VerifiedAccountState) else None
        if state is None:
            raise ValueError("verified account state is required")
        with self.db.transaction() as conn:
            conn.execute(
                """
                insert into integrations.provider_accounts(
                    connection_id, tenant_id, provider, provider_account_id,
                    status, verified_at, reverified_at
                ) values (
                    %s, %s, %s, %s, %s,
                    case when %s = 'verified' then now() end, now()
                )
                on conflict (connection_id, tenant_id) do update set
                    status = excluded.status,
                    verified_at = coalesce(
                        integrations.provider_accounts.verified_at,
                        excluded.verified_at
                    ),
                    reverified_at = now(),
                    updated_at = now()
                """,
                (
                    connection_id, tenant_id, provider, provider_account_id,
                    state.status, state.status,
                ),
            )
            families = sorted({
                family.partition(":")[0] for family in state.families
            })
            for family in families:
                conn.execute(
                    """
                    insert into integrations.provider_account_families(
                        connection_id, tenant_id, family, enabled,
                        provider_state
                    ) values (%s, %s, %s, true, 'live')
                    on conflict (connection_id, tenant_id, family)
                    do update set provider_state = 'live', updated_at = now()
                    """,
                    (connection_id, tenant_id, family),
                )
            for sender in state.senders:
                conn.execute(
                    """
                    insert into integrations.provider_senders(
                        connection_id, tenant_id, sender_id, family,
                        countries, enabled, disabled_at
                    ) values (
                        %s, %s, %s, %s, %s::jsonb, %s,
                        case when %s then null else now() end
                    )
                    on conflict (connection_id, tenant_id, sender_id)
                    do update set
                        family = excluded.family,
                        countries = excluded.countries,
                        updated_at = now()
                    """,
                    (
                        connection_id, tenant_id, sender.sender_id,
                        sender.family,
                        json.dumps(sorted(set(sender.countries))),
                        sender.enabled, sender.enabled,
                    ),
                )
            return self._rederive(conn, tenant_id, connection_id)

    def set_sender_enabled(
        self, tenant_id, connection_id, sender_id, enabled,
        acting_principal_id=None,
    ):
        """Enable or disable one sending identity and nothing else.

        Disabling removes exactly one sender scope from the connection, so
        every in-flight binding that named this sender fails the subset check
        the policy evaluator already runs, and bindings naming a different
        sender on the same connection keep dispatching. The credential version
        is untouched on purpose: the secret did not change, so nothing should
        report a credential mismatch.
        """
        with self.db.transaction() as conn:
            updated = conn.execute(
                """
                update integrations.provider_senders set
                    enabled = %s,
                    disabled_at = case when %s then null else now() end,
                    disabled_by_principal_id = case
                        when %s then null else %s end,
                    updated_at = now()
                where tenant_id = %s and connection_id = %s and sender_id = %s
                returning sender_id
                """,
                (
                    bool(enabled), bool(enabled), bool(enabled),
                    acting_principal_id, tenant_id, connection_id, sender_id,
                ),
            ).fetchone()
            if updated is None:
                raise IntegrationConnectionConflict(
                    "sender is not part of this connection"
                )
            return self._rederive(conn, tenant_id, connection_id)

    def set_family_enabled(self, tenant_id, connection_id, family, enabled):
        """Enable or disable one capability family independently."""
        with self.db.transaction() as conn:
            updated = conn.execute(
                """
                update integrations.provider_account_families set
                    enabled = %s, updated_at = now()
                where tenant_id = %s and connection_id = %s and family = %s
                returning family
                """,
                (bool(enabled), tenant_id, connection_id, family),
            ).fetchone()
            if updated is None:
                raise IntegrationConnectionConflict(
                    "family is not part of this connection"
                )
            return self._rederive(conn, tenant_id, connection_id)

    def rotate_static_credential(
        self, tenant_id, connection_id, credential_id
    ):
        """Record that the sealed secret itself was replaced.

        This is the only lawful reason to move the credential version, and the
        reason every other method here leaves it alone: a version bump means
        "the secret you bound against is gone", and an operator who rotated an
        auth token in the provider's console has genuinely made that true.
        """
        with self.db.transaction() as conn:
            row = conn.execute(
                """
                update integrations.connections set
                    credential_id = %s,
                    credential_version = credential_version + 1,
                    updated_at = now()
                where tenant_id = %s and connection_id = %s
                returning credential_id, credential_version
                """,
                (credential_id, tenant_id, connection_id),
            ).fetchone()
        if row is None:
            raise IntegrationConnectionConflict("connection does not exist")
        return {"credential_id": row[0], "credential_version": row[1]}

    def set_emergency_stop(
        self, tenant_id, active, reason=None, acting_principal_id=None,
    ):
        """Stop or resume one account, account-wide.

        Deliberately not scoped to a connection. R28 makes a stop a fact about
        the account covering inbound handling as well as outbound dispatch, so
        hanging it off one provider's connection would leave every other
        provider running through a stop an operator believed was total.
        """
        active = bool(active)
        if active and not acting_principal_id:
            raise ValueError("an emergency stop must name who ordered it")
        with self.db.transaction() as conn:
            conn.execute(
                """
                insert into integrations.tenant_control_plane(
                    tenant_id, stopped, stop_reason, stopped_at,
                    stopped_by_principal_id, resumed_at,
                    resumed_by_principal_id
                ) values (
                    %s, %s, %s,
                    case when %s then now() end, %s,
                    case when %s then null else now() end,
                    case when %s then null else %s end
                )
                on conflict (tenant_id) do update set
                    stopped = excluded.stopped,
                    stop_reason = excluded.stop_reason,
                    stopped_at = case when excluded.stopped
                        then now()
                        else integrations.tenant_control_plane.stopped_at end,
                    stopped_by_principal_id = case when excluded.stopped
                        then excluded.stopped_by_principal_id
                        else integrations.tenant_control_plane
                             .stopped_by_principal_id end,
                    resumed_at = case when excluded.stopped
                        then integrations.tenant_control_plane.resumed_at
                        else now() end,
                    resumed_by_principal_id = case when excluded.stopped
                        then integrations.tenant_control_plane
                             .resumed_by_principal_id
                        else %s end,
                    updated_at = now()
                """,
                (
                    tenant_id, active, reason if active else None,
                    active, acting_principal_id,
                    active, active, acting_principal_id,
                    acting_principal_id,
                ),
            )
            return self._control_plane_state(conn, tenant_id)

    def control_plane_state(self, tenant_id):
        """Every switch this tenant holds, in one tenant-scoped read."""
        if not tenant_id:
            raise ValueError("tenant_id is required")
        with self.db.connection() as conn:
            return self._control_plane_state(conn, tenant_id)

    def _control_plane_state(self, conn, tenant_id):
        stop = conn.execute(
            """
            select stopped, stop_reason, stopped_at, stopped_by_principal_id
            from integrations.tenant_control_plane where tenant_id = %s
            """,
            (tenant_id,),
        ).fetchone()
        families = conn.execute(
            """
            select family, bool_or(enabled)
            from integrations.provider_account_families
            where tenant_id = %s group by family order by family
            """,
            (tenant_id,),
        ).fetchall()
        senders = conn.execute(
            """
            select sender_id, bool_or(enabled)
            from integrations.provider_senders
            where tenant_id = %s group by sender_id order by sender_id
            """,
            (tenant_id,),
        ).fetchall()
        return {
            "tenant_id": tenant_id,
            "emergency_stop": bool(stop[0]) if stop else False,
            "stop_reason": stop[1] if stop else None,
            "stopped_at": stop[2] if stop else None,
            "stopped_by_principal_id": stop[3] if stop else None,
            "families": {row[0]: bool(row[1]) for row in families},
            "senders": {row[0]: bool(row[1]) for row in senders},
        }

    def verified_state(self, tenant_id, connection_id):
        with self.db.connection() as conn:
            return self._account_state(conn, tenant_id, connection_id)

    def _account_state(self, conn, tenant_id, connection_id):
        account = conn.execute(
            """
            select provider, provider_account_id, status
            from integrations.provider_accounts
            where tenant_id = %s and connection_id = %s
            """,
            (tenant_id, connection_id),
        ).fetchone()
        if account is None:
            return None
        families = conn.execute(
            """
            select family from integrations.provider_account_families
            where tenant_id = %s and connection_id = %s and enabled
            """,
            (tenant_id, connection_id),
        ).fetchall()
        senders = conn.execute(
            """
            select sender_id, family, countries, enabled
            from integrations.provider_senders
            where tenant_id = %s and connection_id = %s
            """,
            (tenant_id, connection_id),
        ).fetchall()
        templates = conn.execute(
            """
            select template_id from integrations.provider_templates
            where tenant_id = %s and connection_id = %s and approved
            """,
            (tenant_id, connection_id),
        ).fetchall()
        return VerifiedAccountState(
            provider=account[0],
            account_id=account[1],
            status=account[2],
            # A family row names the family; the actions it admits are the
            # catalog's business, so every enabled family is recorded as its
            # own send action here and narrowed by the descriptor later.
            families=frozenset("%s:send" % row[0] for row in families),
            senders=tuple(
                VerifiedSender(
                    sender_id=row[0],
                    family=row[1],
                    countries=frozenset(_loaded(row[2])),
                    enabled=bool(row[3]),
                )
                for row in senders
            ),
            templates=frozenset(row[0] for row in templates),
        )

    def _rederive(self, conn, tenant_id, connection_id):
        state = self._account_state(conn, tenant_id, connection_id)
        if state is None:
            raise IntegrationConnectionConflict(
                "connection has no provider account"
            )
        scopes = derive_synthetic_scopes(state)
        conn.execute(
            """
            delete from integrations.provider_derived_scopes
            where tenant_id = %s and connection_id = %s
            """,
            (tenant_id, connection_id),
        )
        for scope, dimension, source_id in _scope_sources(state, scopes):
            conn.execute(
                """
                insert into integrations.provider_derived_scopes(
                    connection_id, tenant_id, scope, dimension, source_id
                ) values (%s, %s, %s, %s, %s)
                """,
                (connection_id, tenant_id, scope, dimension, source_id),
            )
        # Effective scopes move; the credential version does not.
        conn.execute(
            """
            update integrations.connections set
                effective_scopes = %s::jsonb, updated_at = now()
            where tenant_id = %s and connection_id = %s
            """,
            (json.dumps(sorted(scopes)), tenant_id, connection_id),
        )
        return frozenset(scopes)


def _scope_sources(state, scopes):
    """Pair each derived scope with the account fact it came from."""
    sources = {}
    for family in state.families:
        name, _separator, action = family.partition(":")
        sources[synthetic_scope(state.provider, name, action)] = (
            "family", name
        )
    for sender in state.senders:
        if not sender.enabled:
            continue
        sources.setdefault(
            synthetic_scope(state.provider, SENDER_DIMENSION, sender.sender_id),
            (SENDER_DIMENSION, sender.sender_id),
        )
        for country in sender.countries:
            sources.setdefault(
                synthetic_scope(state.provider, GEO_DIMENSION, country),
                (GEO_DIMENSION, country),
            )
    for template in state.templates:
        sources.setdefault(
            synthetic_scope(state.provider, TEMPLATE_DIMENSION, template),
            (TEMPLATE_DIMENSION, template),
        )
    return tuple(
        (scope,) + sources.get(scope, ("family", scope))
        for scope in sorted(scopes)
    )


def _loaded(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return ()
    return value or ()


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
