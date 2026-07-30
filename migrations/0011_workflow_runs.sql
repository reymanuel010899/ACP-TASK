-- Durable workflow, revision, execution and evidence ownership (U11).

create schema orchestrator;

create table orchestrator.workflow_runs (
    workflow_run_id text primary key,
    tenant_id text not null references identity.organizations(organization_id),
    user_principal_id text not null references identity.principals(principal_id),
    goal_hash text not null,
    status text not null,
    current_revision_id text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (workflow_run_id, tenant_id)
);

create table orchestrator.workflow_revisions (
    workflow_revision_id text primary key,
    workflow_run_id text not null,
    tenant_id text not null,
    revision_number integer not null check (revision_number > 0),
    plan_graph_hash text not null,
    capability_snapshot_hash text not null,
    status text not null,
    created_at timestamptz not null default now(),
    foreign key (workflow_run_id, tenant_id)
        references orchestrator.workflow_runs(workflow_run_id, tenant_id),
    unique (workflow_run_id, revision_number),
    unique (workflow_run_id, workflow_revision_id, tenant_id)
);

alter table orchestrator.workflow_runs
    add constraint workflow_current_revision_fk
    foreign key (workflow_run_id, current_revision_id, tenant_id)
    references orchestrator.workflow_revisions(
        workflow_run_id, workflow_revision_id, tenant_id
    ) deferrable initially deferred;

create table orchestrator.workflow_steps (
    workflow_revision_id text not null,
    step_id text not null,
    workflow_run_id text not null,
    tenant_id text not null,
    capability_id text not null references catalog.capabilities(capability_id),
    capability_version text not null,
    connection_id text references integrations.connections(connection_id) on delete restrict,
    descriptor_snapshot_hash text not null,
    input_hash text not null,
    input_json jsonb not null default '{}',
    output_json jsonb,
    dependency_ids jsonb not null default '[]',
    effect text not null check (effect in ('read', 'write')),
    execution_status text not null,
    verification_status text not null,
    attempt integer not null default 0 check (attempt >= 0),
    claimed_by text,
    claimed_at timestamptz,
    retry_at timestamptz,
    terminal_reason text,
    primary key (workflow_revision_id, step_id),
    foreign key (workflow_run_id, workflow_revision_id, tenant_id)
        references orchestrator.workflow_revisions(
            workflow_run_id, workflow_revision_id, tenant_id
        ),
    unique (workflow_revision_id, step_id, tenant_id)
);

create table orchestrator.workflow_approvals (
    workflow_revision_id text primary key,
    workflow_run_id text not null,
    tenant_id text not null,
    plan_graph_hash text not null,
    approved_effects_hash text not null,
    approved_by text not null references identity.principals(principal_id),
    approved_at timestamptz not null default now(),
    expires_at timestamptz not null,
    foreign key (workflow_run_id, workflow_revision_id, tenant_id)
        references orchestrator.workflow_revisions(
            workflow_run_id, workflow_revision_id, tenant_id
        )
);

create table orchestrator.workflow_blockers (
    blocker_id text primary key,
    workflow_revision_id text not null,
    workflow_run_id text not null,
    tenant_id text not null,
    step_id text,
    blocker_type text not null,
    prompt text not null,
    resolved_at timestamptz,
    foreign key (workflow_run_id, workflow_revision_id, tenant_id)
        references orchestrator.workflow_revisions(
            workflow_run_id, workflow_revision_id, tenant_id
        ),
    foreign key (workflow_revision_id, step_id)
        references orchestrator.workflow_steps(workflow_revision_id, step_id)
);

create table orchestrator.workflow_leases (
    lease_hash text primary key,
    workflow_revision_id text not null,
    step_id text not null,
    attempt integer not null,
    tenant_id text not null,
    worker_id text not null,
    connection_id text references integrations.connections(connection_id) on delete restrict,
    descriptor_snapshot_hash text not null,
    expires_at timestamptz not null,
    consumed_at timestamptz,
    revoked_at timestamptz,
    foreign key (workflow_revision_id, step_id, tenant_id)
        references orchestrator.workflow_steps(
            workflow_revision_id, step_id, tenant_id
        ),
    unique (workflow_revision_id, step_id, attempt)
);
create unique index workflow_one_active_lease
    on orchestrator.workflow_leases(workflow_revision_id, step_id)
    where consumed_at is null and revoked_at is null;

create table orchestrator.workflow_receipts (
    receipt_id text primary key,
    workflow_revision_id text not null,
    step_id text not null,
    attempt integer not null,
    tenant_id text not null,
    connection_id text references integrations.connections(connection_id) on delete restrict,
    descriptor_snapshot_hash text not null,
    approved_input_hash text not null,
    provider_identifiers jsonb not null default '{}',
    receipt_hash text not null,
    created_at timestamptz not null default now(),
    foreign key (workflow_revision_id, step_id, tenant_id)
        references orchestrator.workflow_steps(
            workflow_revision_id, step_id, tenant_id
        ),
    unique (workflow_revision_id, step_id, attempt)
);

create table orchestrator.workflow_attestations (
    attestation_id text primary key,
    receipt_id text not null unique references orchestrator.workflow_receipts(receipt_id),
    workflow_revision_id text not null,
    step_id text not null,
    tenant_id text not null,
    attestation_hash text not null,
    verification_status text not null,
    created_at timestamptz not null default now(),
    foreign key (workflow_revision_id, step_id, tenant_id)
        references orchestrator.workflow_steps(
            workflow_revision_id, step_id, tenant_id
        )
);

create table orchestrator.workflow_content (
    content_id text primary key,
    workflow_revision_id text not null,
    step_id text,
    tenant_id text not null,
    data_class text not null,
    encrypted_content bytea,
    content_hash text not null,
    expires_at timestamptz not null,
    purged_at timestamptz,
    foreign key (workflow_revision_id, step_id, tenant_id)
        references orchestrator.workflow_steps(
            workflow_revision_id, step_id, tenant_id
        )
);

do $$
declare table_name text;
begin
    foreach table_name in array array[
        'workflow_runs', 'workflow_revisions', 'workflow_steps',
        'workflow_approvals', 'workflow_blockers', 'workflow_leases',
        'workflow_receipts', 'workflow_attestations', 'workflow_content'
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
