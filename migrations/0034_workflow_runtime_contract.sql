-- Reconcile the original workflow schema with the runtime contract that grew
-- around retries, reconciliation, authorization modes, and durable evidence.

begin;

alter table orchestrator.workflow_approvals
    add column authorization_mode text not null default 'explicit_write',
    add constraint workflow_authorization_mode_check check (
        authorization_mode in (
            'explicit_write', 'requested_read', 'campaign_envelope'
        )
    );

alter table orchestrator.workflow_steps
    add column credential_version bigint not null default 0,
    add column content_expires_at timestamptz,
    add column uncounted_attempts integer not null default 0,
    add column reconcile_after timestamptz,
    add column reconcile_attempts integer not null default 0,
    add constraint workflow_uncounted_attempts_check check (
        uncounted_attempts >= 0 and uncounted_attempts <= attempt
    ),
    add constraint workflow_reconcile_attempts_check check (
        reconcile_attempts >= 0
    );

alter table orchestrator.workflow_receipts
    add column receipt_json jsonb;

alter table orchestrator.workflow_attestations
    add column attestation_json jsonb;

create table orchestrator.workflow_campaign_bindings (
    workflow_revision_id text primary key,
    workflow_run_id text not null,
    tenant_id text not null,
    campaign_id text not null,
    envelope_hash text not null,
    foreign key (workflow_run_id, workflow_revision_id, tenant_id)
        references orchestrator.workflow_revisions(
            workflow_run_id, workflow_revision_id, tenant_id
        ) on delete cascade
);

alter table orchestrator.workflow_campaign_bindings enable row level security;
alter table orchestrator.workflow_campaign_bindings force row level security;
create policy workflow_campaign_bindings_tenant_isolation
    on orchestrator.workflow_campaign_bindings
    using (tenant_id = nullif(current_setting('app.current_org_id', true), ''))
    with check (
        tenant_id = nullif(current_setting('app.current_org_id', true), '')
    );

commit;
