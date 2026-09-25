-- PostgreSQL authority for operational sessions, OAuth handshakes, actions,
-- dispatch records, and migration/cutover metadata.
--
-- Existing integration and workflow tables remain authoritative. This
-- migration fills the state gaps that were still represented only in SQLite.

begin;

create table identity.web_sessions (
    session_hash text primary key,
    principal_id text not null
        references identity.principals(principal_id) on delete cascade,
    csrf_hash text not null,
    created_at timestamptz not null,
    last_seen_at timestamptz not null,
    authenticated_at timestamptz not null,
    absolute_expires_at timestamptz not null,
    revoked_at timestamptz,
    check (last_seen_at >= created_at),
    check (authenticated_at >= created_at),
    check (absolute_expires_at > created_at),
    check (revoked_at is null or revoked_at >= created_at)
);
create index web_sessions_principal_idx
    on identity.web_sessions(principal_id);
create index web_sessions_active_expiry_idx
    on identity.web_sessions(absolute_expires_at, last_seen_at)
    where revoked_at is null;

-- Identity proof replay protection is global to the proof fingerprint. It is
-- intentionally not tenant-scoped: authentication happens before an
-- organization is selected and the same proof cannot be spent in two tenants.
create table identity.consumed_identity_proofs (
    proof_hash text primary key,
    consumed_at timestamptz not null
);

create table integrations.oauth_transactions (
    transaction_id text primary key,
    tenant_id text not null
        references identity.organizations(organization_id) on delete cascade,
    session_hash text not null
        references identity.web_sessions(session_hash) on delete cascade,
    principal_id text not null
        references identity.principals(principal_id) on delete cascade,
    provider text not null,
    requested_scopes jsonb not null default '[]'::jsonb,
    requested_capabilities jsonb not null default '[]'::jsonb,
    state_hash text not null unique,
    pkce_verifier_ciphertext text not null,
    return_to text not null,
    app_id text,
    intended_team_id text,
    target_connection_id text,
    created_at timestamptz not null,
    expires_at timestamptz not null,
    consumed_at timestamptz,
    foreign key (tenant_id, principal_id)
        references identity.organization_members(organization_id, principal_id),
    check (expires_at > created_at),
    check (consumed_at is null or consumed_at >= created_at)
);
create index oauth_transactions_expiry_idx
    on integrations.oauth_transactions(expires_at)
    where consumed_at is null;

create table orchestrator.action_proposals (
    proposal_id text not null,
    version integer not null check (version > 0),
    tenant_id text not null
        references identity.organizations(organization_id) on delete cascade,
    user_principal_id text not null
        references identity.principals(principal_id) on delete restrict,
    agent_principal_id text not null
        references identity.principals(principal_id) on delete restrict,
    credential_id text not null
        references vault.credentials(credential_id) on delete restrict,
    capability_id text not null
        references catalog.capabilities(capability_id) on delete restrict,
    payload_json jsonb not null,
    payload_hash text not null,
    idempotency_key text not null,
    status text not null check (status in (
        'proposed', 'approved', 'rejected', 'superseded', 'executing',
        'dispatched', 'completed', 'failed', 'execution_unknown'
    )),
    expires_at timestamptz not null,
    approved_at timestamptz,
    rejected_at timestamptz,
    execution_started_at timestamptz,
    dispatched_at timestamptz,
    execution_finished_at timestamptz,
    receipt_json jsonb,
    broker_response_json jsonb,
    failure_reason text,
    workflow_revision_id text,
    step_id text,
    plan_graph_hash text,
    connection_id text,
    attempt integer not null default 0 check (attempt >= 0),
    authority_profile text not null default 'bot',
    authority_profile_id text,
    slack_subject_id text,
    reinforced boolean not null default false,
    primary key (tenant_id, proposal_id, version),
    unique (tenant_id, idempotency_key)
);
create index action_proposals_lookup_idx
    on orchestrator.action_proposals(tenant_id, proposal_id, version desc);
create index action_proposals_stalled_idx
    on orchestrator.action_proposals(execution_started_at)
    where status in ('executing', 'execution_unknown');

create table orchestrator.capability_leases (
    lease_hash text primary key,
    tenant_id text not null
        references identity.organizations(organization_id) on delete cascade,
    user_principal_id text not null
        references identity.principals(principal_id) on delete restrict,
    agent_principal_id text not null
        references identity.principals(principal_id) on delete restrict,
    task_id text not null,
    credential_id text not null
        references vault.credentials(credential_id) on delete restrict,
    capabilities_json jsonb not null default '[]'::jsonb,
    expires_at timestamptz not null,
    revoked_at timestamptz,
    consumed_at timestamptz,
    workflow_revision_id text,
    step_id text,
    plan_graph_hash text,
    connection_id text,
    attempt integer not null default 0 check (attempt >= 0),
    authority_profile text not null default 'bot',
    authority_profile_id text,
    slack_subject_id text,
    check (revoked_at is null or consumed_at is null)
);
create unique index capability_one_active_workflow_lease
    on orchestrator.capability_leases(tenant_id, workflow_revision_id, step_id)
    where workflow_revision_id is not null
      and step_id is not null
      and consumed_at is null
      and revoked_at is null;
create index capability_leases_expiry_idx
    on orchestrator.capability_leases(expires_at)
    where consumed_at is null and revoked_at is null;

create table orchestrator.dispatch_records (
    tenant_id text not null
        references identity.organizations(organization_id) on delete cascade,
    dispatch_key text not null,
    effect_id text not null,
    payload_hash text not null,
    status text not null check (status in (
        'intent_recorded', 'dispatching', 'retryable', 'accepted',
        'ambiguous', 'rejected'
    )),
    provider_id text,
    provider_status text,
    attempt_count integer not null default 0 check (attempt_count >= 0),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key (tenant_id, dispatch_key),
    unique (tenant_id, effect_id)
);

create schema operational_migration;

create table operational_migration.store_authority (
    tenant_id text not null
        references identity.organizations(organization_id) on delete cascade,
    domain_family text not null,
    authority text not null check (authority in (
        'sqlite_authoritative', 'importing', 'ready', 'postgres_authoritative'
    )),
    source_fingerprint text,
    import_generation bigint not null default 0 check (import_generation >= 0),
    changed_at timestamptz not null default now(),
    changed_by_principal_id text
        references identity.principals(principal_id) on delete set null,
    primary key (tenant_id, domain_family)
);

create table operational_migration.import_runs (
    import_run_id text not null,
    tenant_id text not null
        references identity.organizations(organization_id) on delete cascade,
    domain_family text not null,
    import_generation bigint not null check (import_generation > 0),
    source_fingerprint text not null,
    source_schema_fingerprint text not null,
    status text not null check (status in (
        'dry_run', 'running', 'completed', 'failed', 'abandoned'
    )),
    imported_count bigint not null default 0 check (imported_count >= 0),
    conflict_count bigint not null default 0 check (conflict_count >= 0),
    quarantine_count bigint not null default 0 check (quarantine_count >= 0),
    started_at timestamptz not null default now(),
    completed_at timestamptz,
    primary key (tenant_id, import_run_id),
    unique (tenant_id, domain_family, import_generation)
);

create table operational_migration.import_checkpoints (
    tenant_id text not null,
    import_run_id text not null,
    source_table text not null,
    last_source_key text,
    processed_count bigint not null default 0 check (processed_count >= 0),
    normalized_digest text not null,
    updated_at timestamptz not null default now(),
    primary key (tenant_id, import_run_id, source_table),
    foreign key (tenant_id, import_run_id)
        references operational_migration.import_runs(tenant_id, import_run_id)
        on delete cascade
);

create table operational_migration.import_quarantine (
    tenant_id text not null,
    import_run_id text not null,
    source_table text not null,
    source_key_hash text not null,
    row_digest text not null,
    reason_code text not null,
    created_at timestamptz not null default now(),
    resolved_at timestamptz,
    primary key (tenant_id, import_run_id, source_table, source_key_hash),
    foreign key (tenant_id, import_run_id)
        references operational_migration.import_runs(tenant_id, import_run_id)
        on delete cascade
);

do $$
declare
    qualified_name text;
begin
    foreach qualified_name in array array[
        'integrations.oauth_transactions',
        'orchestrator.action_proposals',
        'orchestrator.capability_leases',
        'orchestrator.dispatch_records',
        'operational_migration.store_authority',
        'operational_migration.import_runs',
        'operational_migration.import_checkpoints',
        'operational_migration.import_quarantine'
    ]
    loop
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
