-- Remaining durable communications and voice state plus strict policy
-- normalization for operational tables created before U3.

begin;

create table voice.sessions (
    tenant_id text not null
        references identity.organizations(organization_id) on delete cascade,
    session_id text not null,
    call_sid text,
    principal_id text
        references identity.principals(principal_id) on delete set null,
    status text not null,
    started_at timestamptz not null,
    ended_at timestamptz,
    content_expires_at timestamptz not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key (tenant_id, session_id),
    unique (tenant_id, call_sid),
    check (ended_at is null or ended_at >= started_at),
    check (content_expires_at > started_at)
);

create table voice.transcript_events (
    tenant_id text not null,
    session_id text not null,
    event_sequence bigint not null check (event_sequence > 0),
    event_type text not null,
    content_ciphertext text not null,
    content_digest text not null,
    occurred_at timestamptz not null,
    content_expires_at timestamptz not null,
    primary key (tenant_id, session_id, event_sequence),
    foreign key (tenant_id, session_id)
        references voice.sessions(tenant_id, session_id) on delete cascade
);
create index voice_transcript_expiry_idx
    on voice.transcript_events(content_expires_at);

alter table voice.sessions enable row level security;
alter table voice.sessions force row level security;
create policy tenant_isolation on voice.sessions
    using (tenant_id = nullif(current_setting('app.current_org_id', true), ''))
    with check (tenant_id = nullif(current_setting('app.current_org_id', true), ''));

alter table voice.transcript_events enable row level security;
alter table voice.transcript_events force row level security;
create policy tenant_isolation on voice.transcript_events
    using (tenant_id = nullif(current_setting('app.current_org_id', true), ''))
    with check (tenant_id = nullif(current_setting('app.current_org_id', true), ''));

-- Normalize older policies onto the exact fail-closed expression. The table
-- list is explicit so a new operational table cannot silently inherit a
-- permissive compatibility branch.
do $$
declare
    qualified_name text;
    policy_name text;
begin
    foreach qualified_name in array array[
        'billing.spend_budgets',
        'billing.spend_reservations',
        'billing.brand_daily_volume',
        'twilio.identities',
        'twilio.dispatch_ledger',
        'twilio.provider_events',
        'twilio.effect_verdicts',
        'twilio.whatsapp_session_windows',
        'twilio.whatsapp_templates'
    ]
    loop
        for policy_name in
            select pol.polname
            from pg_policy pol
            join pg_class cls on cls.oid = pol.polrelid
            join pg_namespace ns on ns.oid = cls.relnamespace
            where ns.nspname || '.' || cls.relname = qualified_name
        loop
            execute format('drop policy %I on %s', policy_name, qualified_name);
        end loop;
        execute format('alter table %s enable row level security', qualified_name);
        execute format('alter table %s force row level security', qualified_name);
        execute format(
            'create policy tenant_isolation on %s using '
            '(tenant_id = nullif(current_setting(''app.current_org_id'', true), '''')) '
            'with check '
            '(tenant_id = nullif(current_setting(''app.current_org_id'', true), ''''))',
            qualified_name
        );
    end loop;
end
$$;

commit;

