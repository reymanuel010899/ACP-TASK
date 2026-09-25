-- Tenant-bound continuation state for protocol-level multi-turn tasks.

begin;

create table orchestrator.task_conversations (
    tenant_id text not null
        references identity.organizations(organization_id) on delete cascade,
    task_id text not null,
    conversation_id text not null,
    agent_id text not null,
    capability text not null,
    state_json jsonb not null,
    created_at timestamptz not null,
    updated_at timestamptz not null,
    expires_at timestamptz not null,
    primary key (tenant_id, task_id),
    unique (tenant_id, conversation_id),
    check (expires_at > created_at)
);

create index task_conversations_expiry_idx
    on orchestrator.task_conversations(tenant_id, expires_at);

alter table orchestrator.task_conversations enable row level security;
alter table orchestrator.task_conversations force row level security;
create policy task_conversations_tenant_isolation
    on orchestrator.task_conversations
    using (tenant_id = nullif(current_setting('app.current_org_id', true), ''))
    with check (
        tenant_id = nullif(current_setting('app.current_org_id', true), '')
    );

commit;
