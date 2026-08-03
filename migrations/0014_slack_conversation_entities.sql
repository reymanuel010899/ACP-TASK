-- Versioned Concierge turns, grounded Slack entities, resumable resolution,
-- and privacy-safe product outcomes. This migration is expand-only.

alter table orchestrator.concierge_conversations
    add column state_version bigint not null default 1
        check (state_version > 0);

create table orchestrator.concierge_turns (
    conversation_id text not null,
    tenant_id text not null,
    principal_id text not null,
    client_turn_id text not null,
    turn_version bigint not null check (turn_version > 0),
    base_state_version bigint not null check (base_state_version > 0),
    request_hash text not null,
    request_json jsonb not null,
    response_hash text,
    response_json jsonb,
    status text not null check (status in (
        'started', 'committed', 'conflicted', 'failed'
    )),
    content_expires_at timestamptz not null,
    created_at timestamptz not null default now(),
    committed_at timestamptz,
    primary key (conversation_id, tenant_id, principal_id, client_turn_id),
    unique (conversation_id, tenant_id, principal_id, turn_version),
    foreign key (conversation_id, tenant_id, principal_id)
        references orchestrator.concierge_conversations(
            conversation_id, tenant_id, principal_id
        )
);

create unique index concierge_turns_one_active_base
    on orchestrator.concierge_turns(
        conversation_id, tenant_id, principal_id, base_state_version
    ) where status = 'started';

create table orchestrator.slack_conversation_entities (
    entity_ref_id text not null,
    tenant_id text not null,
    conversation_id text not null,
    principal_id text not null,
    entity_kind text not null check (entity_kind in (
        'workspace', 'channel', 'user', 'message', 'thread', 'file', 'reaction'
    )),
    connection_id text not null,
    team_id text not null,
    provider_entity_id text not null,
    entity_version bigint not null check (entity_version > 0),
    entity_hash text not null,
    entity_json jsonb not null,
    provenance_json jsonb not null default '{}',
    observed_at timestamptz not null,
    stale_after timestamptz not null,
    superseded_at timestamptz,
    primary key (entity_ref_id, tenant_id),
    unique (
        tenant_id, conversation_id, entity_kind, connection_id,
        provider_entity_id, entity_version
    ),
    foreign key (conversation_id, tenant_id, principal_id)
        references orchestrator.concierge_conversations(
            conversation_id, tenant_id, principal_id
        )
);

create index slack_conversation_entities_lookup
    on orchestrator.slack_conversation_entities(
        tenant_id, conversation_id, entity_kind, connection_id,
        provider_entity_id, observed_at desc
    ) where superseded_at is null;

create table orchestrator.slack_resolver_runs (
    resolver_run_id text not null,
    tenant_id text not null,
    conversation_id text not null,
    principal_id text not null,
    connection_id text not null,
    entity_kind text not null,
    query_hash text not null,
    requested_state_version bigint not null check (requested_state_version > 0),
    status text not null check (status in (
        'pending', 'running', 'waiting_retry', 'completed', 'failed', 'cancelled'
    )),
    cursor_json jsonb not null default '{}',
    budget_json jsonb not null default '{}',
    pages_processed integer not null default 0 check (pages_processed >= 0),
    candidates_seen integer not null default 0 check (candidates_seen >= 0),
    retry_at timestamptz,
    last_error_code text,
    workflow_run_id text,
    workflow_revision_id text,
    outcome_json jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    completed_at timestamptz,
    primary key (resolver_run_id, tenant_id),
    unique (tenant_id, conversation_id, resolver_run_id),
    foreign key (conversation_id, tenant_id, principal_id)
        references orchestrator.concierge_conversations(
            conversation_id, tenant_id, principal_id
        )
);

create index slack_resolver_runs_claimable
    on orchestrator.slack_resolver_runs(status, retry_at, updated_at)
    where status in ('pending', 'running', 'waiting_retry');

create unique index slack_resolver_runs_request
    on orchestrator.slack_resolver_runs(
        tenant_id, conversation_id, connection_id, entity_kind, query_hash,
        requested_state_version
    );

create table orchestrator.concierge_outcome_events (
    event_id text not null,
    tenant_id text not null,
    conversation_id text not null,
    principal_id text not null,
    event_sequence bigint not null check (event_sequence > 0),
    event_type text not null check (event_type in (
        'operation_attempted', 'clarification_requested', 'corrected',
        'previewed', 'approved', 'rejected', 'completed', 'abandoned', 'failed'
    )),
    operation_family text,
    metrics_json jsonb not null default '{}',
    created_at timestamptz not null default now(),
    primary key (event_id, tenant_id),
    unique (tenant_id, conversation_id, event_sequence),
    foreign key (conversation_id, tenant_id, principal_id)
        references orchestrator.concierge_conversations(
            conversation_id, tenant_id, principal_id
        )
);

do $$
declare table_name text;
begin
    foreach table_name in array array[
        'concierge_turns', 'slack_conversation_entities',
        'slack_resolver_runs', 'concierge_outcome_events'
    ] loop
        execute format('alter table orchestrator.%I enable row level security', table_name);
        execute format('alter table orchestrator.%I force row level security', table_name);
        execute format(
            'create policy %I on orchestrator.%I using '
            '(tenant_id = current_setting(''app.current_org_id'', true)) '
            'with check (tenant_id = current_setting(''app.current_org_id'', true))',
            table_name || '_tenant_isolation', table_name
        );
    end loop;
end $$;

create trigger concierge_outcome_events_append_only
before update or delete on orchestrator.concierge_outcome_events
for each row execute function orchestrator.reject_append_only_mutation();
