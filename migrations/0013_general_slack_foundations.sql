-- Expand-only foundations for catalog operations, immutable effects, policy
-- decisions, durable event delivery, and ordered conversation projections.

create table orchestrator.operation_instances (
    operation_instance_id text primary key,
    tenant_id text not null references identity.organizations(organization_id),
    workflow_run_id text not null,
    workflow_revision_id text not null,
    operation_key text not null,
    operation_version integer not null check (operation_version > 0),
    status text not null check (status in (
        'materializing', 'awaiting_approval', 'approved', 'executing',
        'partially_completed', 'completed', 'failed', 'cancelled', 'superseded'
    )),
    created_at timestamptz not null default now(),
    foreign key (workflow_run_id, workflow_revision_id, tenant_id)
        references orchestrator.workflow_revisions(
            workflow_run_id, workflow_revision_id, tenant_id
        ),
    unique (operation_instance_id, tenant_id),
    unique (tenant_id, operation_key, operation_version)
);

create table orchestrator.effect_instances (
    effect_instance_id text primary key,
    tenant_id text not null references identity.organizations(organization_id),
    operation_instance_id text not null,
    logical_effect_id text not null,
    effect_version integer not null check (effect_version > 0),
    capability_id text not null references catalog.capabilities(capability_id),
    payload_hash text not null,
    status text not null check (status in (
        'materialized', 'awaiting_approval', 'approved', 'leased', 'dispatched',
        'outcome_unknown', 'verified', 'retryable', 'failed', 'cancelled',
        'superseded'
    )),
    created_at timestamptz not null default now(),
    foreign key (operation_instance_id, tenant_id)
        references orchestrator.operation_instances(operation_instance_id, tenant_id),
    unique (effect_instance_id, tenant_id),
    unique (tenant_id, logical_effect_id, effect_version)
);

create table orchestrator.policy_decisions (
    policy_decision_id text primary key,
    tenant_id text not null references identity.organizations(organization_id),
    operation_instance_id text not null,
    effect_instance_id text,
    policy_version text not null,
    input_hash text not null,
    decision_hash text not null,
    decision text not null check (decision in ('allow', 'deny', 'pause', 'replan')),
    reason_code text not null,
    decided_at timestamptz not null default now(),
    foreign key (operation_instance_id, tenant_id)
        references orchestrator.operation_instances(operation_instance_id, tenant_id),
    foreign key (effect_instance_id, tenant_id)
        references orchestrator.effect_instances(effect_instance_id, tenant_id),
    unique (policy_decision_id, tenant_id),
    unique (tenant_id, operation_instance_id, effect_instance_id,
            policy_version, input_hash)
);

create table orchestrator.workflow_outbox (
    event_id text primary key,
    tenant_id text not null references identity.organizations(organization_id),
    aggregate_type text not null,
    aggregate_id text not null,
    aggregate_version bigint not null check (aggregate_version > 0),
    event_type text not null,
    payload_json jsonb not null,
    dedupe_key text not null,
    status text not null default 'pending' check (status in (
        'pending', 'claimed', 'completed', 'dead_letter'
    )),
    attempts integer not null default 0 check (attempts >= 0),
    max_attempts integer not null default 5 check (max_attempts > 0),
    available_at timestamptz not null default now(),
    claimed_by text,
    claim_expires_at timestamptz,
    last_error text,
    created_at timestamptz not null default now(),
    completed_at timestamptz,
    dead_lettered_at timestamptz,
    unique (event_id, tenant_id),
    unique (tenant_id, dedupe_key),
    unique (tenant_id, aggregate_type, aggregate_id, aggregate_version),
    check (
        (status = 'claimed' and claimed_by is not null and claim_expires_at is not null)
        or (status != 'claimed' and claimed_by is null and claim_expires_at is null)
    )
);

create index workflow_outbox_claimable
    on orchestrator.workflow_outbox(available_at, created_at)
    where status = 'pending';
create index workflow_outbox_expired_claims
    on orchestrator.workflow_outbox(claim_expires_at)
    where status = 'claimed';
create index workflow_outbox_retention
    on orchestrator.workflow_outbox(tenant_id, completed_at)
    where status = 'completed';

create table orchestrator.projection_watermarks (
    tenant_id text not null references identity.organizations(organization_id),
    projection_name text not null,
    aggregate_type text not null,
    aggregate_id text not null,
    projected_version bigint not null check (projected_version > 0),
    last_event_id text not null,
    updated_at timestamptz not null default now(),
    primary key (tenant_id, projection_name, aggregate_type, aggregate_id),
    foreign key (last_event_id, tenant_id)
        references orchestrator.workflow_outbox(event_id, tenant_id)
);

-- All records are tenant-owned. Worker and broker roles still require explicit
-- grants; RLS is forced so a pooled connection cannot bypass tenant context.
do $$
declare table_name text;
begin
    foreach table_name in array array[
        'operation_instances', 'effect_instances', 'policy_decisions',
        'workflow_outbox', 'projection_watermarks'
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

-- Append-only domain/audit records. Lifecycle updates are allowed only for the
-- delivery and projection coordination tables.
create function orchestrator.reject_append_only_mutation()
returns trigger language plpgsql as $$
begin
    raise exception '% is append-only', tg_table_name;
end;
$$;

create trigger operation_instances_append_only
before update or delete on orchestrator.operation_instances
for each row execute function orchestrator.reject_append_only_mutation();
create trigger effect_instances_append_only
before update or delete on orchestrator.effect_instances
for each row execute function orchestrator.reject_append_only_mutation();
create trigger policy_decisions_append_only
before update or delete on orchestrator.policy_decisions
for each row execute function orchestrator.reject_append_only_mutation();
