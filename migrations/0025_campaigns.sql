begin;
create schema if not exists campaign;

create table campaign.campaigns (
    tenant_id text not null,
    campaign_id text not null,
    created_by_principal_id text not null,
    authorized_by_principal_id text,
    definition jsonb not null,
    definition_hash text not null,
    cohort_hash text,
    envelope_hash text,
    status text not null check (status in (
        'defined','audience_previewed','authorized','scheduled','running',
        'deferred_quiet_hours','throttled','blocked_connection','paused',
        'stopped','draining','reconciling','drained','expired','invalidated'
    )),
    approval_expires_at timestamptz,
    envelope_expires_at timestamptz,
    reaffirm_by timestamptz,
    estimated_spend_micros bigint not null default 0,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key (tenant_id, campaign_id)
);

create table campaign.campaign_cohort (
    tenant_id text not null,
    campaign_id text not null,
    contact_id text not null,
    channel text not null,
    address_id text not null,
    branch_id text not null,
    masked_destination text not null,
    included smallint not null check (included in (0, 1, 2)),
    exclusion_reason text,
    primary key (tenant_id, campaign_id, contact_id, channel),
    foreign key (tenant_id, campaign_id)
      references campaign.campaigns (tenant_id, campaign_id) on delete cascade
);

create table campaign.campaign_effects (
    tenant_id text not null,
    campaign_id text not null,
    contact_id text not null,
    channel text not null,
    address_id text not null,
    cycle integer not null default 1,
    status text not null check (status in (
        'pending','claimed','deferred','completed','prevented','uncertain',
        'never_eligible','cancelled'
    )),
    reason text,
    not_before timestamptz,
    claimed_by text,
    lease_expires_at timestamptz,
    attempt_count integer not null default 0,
    provider_id text,
    updated_at timestamptz not null default now(),
    unique (tenant_id, campaign_id, contact_id, channel),
    foreign key (tenant_id, campaign_id)
      references campaign.campaigns (tenant_id, campaign_id) on delete cascade
);

create table campaign.campaign_audit (
    tenant_id text not null,
    event_id bigserial,
    campaign_id text not null,
    event_type text not null,
    actor_id text,
    details jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now(),
    primary key (tenant_id, event_id),
    foreign key (tenant_id, campaign_id)
      references campaign.campaigns (tenant_id, campaign_id) on delete cascade
);

create table campaign.throughput_limits (
    tenant_id text not null,
    capability_id text not null,
    limit_count integer not null check (limit_count > 0),
    window_seconds integer not null check (window_seconds > 0),
    window_started_at timestamptz,
    used integer not null default 0,
    primary key (tenant_id, capability_id)
);

alter table campaign.campaigns enable row level security;
alter table campaign.campaigns force row level security;
alter table campaign.campaign_cohort enable row level security;
alter table campaign.campaign_cohort force row level security;
alter table campaign.campaign_effects enable row level security;
alter table campaign.campaign_effects force row level security;
alter table campaign.campaign_audit enable row level security;
alter table campaign.campaign_audit force row level security;
alter table campaign.throughput_limits enable row level security;
alter table campaign.throughput_limits force row level security;

create policy tenant_isolation on campaign.campaigns
  using (tenant_id = current_setting('app.tenant_id', true))
  with check (tenant_id = current_setting('app.tenant_id', true));
create policy tenant_isolation on campaign.campaign_cohort
  using (tenant_id = current_setting('app.tenant_id', true))
  with check (tenant_id = current_setting('app.tenant_id', true));
create policy tenant_isolation on campaign.campaign_effects
  using (tenant_id = current_setting('app.tenant_id', true))
  with check (tenant_id = current_setting('app.tenant_id', true));
create policy tenant_isolation on campaign.campaign_audit
  using (tenant_id = current_setting('app.tenant_id', true))
  with check (tenant_id = current_setting('app.tenant_id', true));
create policy tenant_isolation on campaign.throughput_limits
  using (tenant_id = current_setting('app.tenant_id', true))
  with check (tenant_id = current_setting('app.tenant_id', true));
commit;
