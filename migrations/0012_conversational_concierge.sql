-- Short-lived, server-authoritative state for the active Concierge modal.

create table orchestrator.concierge_conversations (
    conversation_id text primary key,
    tenant_id text not null references identity.organizations(organization_id),
    principal_id text not null references identity.principals(principal_id),
    status text not null check (status in (
        'interpreting', 'resolving', 'needs_input', 'retrieving', 'answering',
        'ready', 'awaiting_approval', 'executing', 'succeeded',
        'retryable_failure', 'unknown_outcome', 'cancelled', 'expired', 'closed'
    )),
    state_json jsonb not null default '{}',
    presentation_json jsonb,
    presentation_hash text,
    workflow_run_id text,
    workflow_revision_id text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    expires_at timestamptz not null,
    content_expires_at timestamptz not null,
    closed_at timestamptz,
    unique (conversation_id, tenant_id, principal_id),
    foreign key (workflow_run_id, workflow_revision_id, tenant_id)
        references orchestrator.workflow_revisions(
            workflow_run_id, workflow_revision_id, tenant_id
        )
);

create index concierge_conversations_expiry
    on orchestrator.concierge_conversations(expires_at)
    where closed_at is null;

create table orchestrator.concierge_answers (
    conversation_id text not null,
    tenant_id text not null,
    principal_id text not null,
    idempotency_key text not null,
    field_name text not null,
    answer_hash text not null,
    workflow_run_id text,
    workflow_revision_id text,
    applied_at timestamptz not null default now(),
    primary key (conversation_id, tenant_id, principal_id, idempotency_key),
    foreign key (conversation_id, tenant_id, principal_id)
        references orchestrator.concierge_conversations(
            conversation_id, tenant_id, principal_id
        ),
    foreign key (workflow_run_id, workflow_revision_id, tenant_id)
        references orchestrator.workflow_revisions(
            workflow_run_id, workflow_revision_id, tenant_id
        )
);

alter table orchestrator.concierge_conversations enable row level security;
alter table orchestrator.concierge_conversations force row level security;
create policy concierge_conversations_tenant_isolation
    on orchestrator.concierge_conversations
    using (tenant_id = current_setting('app.current_org_id', true))
    with check (tenant_id = current_setting('app.current_org_id', true));

alter table orchestrator.concierge_answers enable row level security;
alter table orchestrator.concierge_answers force row level security;
create policy concierge_answers_tenant_isolation
    on orchestrator.concierge_answers
    using (tenant_id = current_setting('app.current_org_id', true))
    with check (tenant_id = current_setting('app.current_org_id', true));
