begin;
create schema if not exists voice;

create table voice.transfer_routes (
  tenant_id text not null,
  route_id text not null,
  department text not null,
  language text not null default '*',
  destination text not null,
  timezone text not null,
  start_hour smallint not null check (start_hour between 0 and 23),
  end_hour smallint not null check (end_hour between 0 and 24),
  ring_seconds integer not null check (ring_seconds between 5 and 600),
  total_budget_seconds integer not null check (total_budget_seconds between 5 and 1800),
  priority integer not null,
  enabled boolean not null default true,
  primary key (tenant_id, route_id)
);

create table voice.unfiled_activity (
  tenant_id text not null,
  activity_id bigserial,
  provider_call_id text not null,
  principal_id text not null,
  details jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  primary key (tenant_id, activity_id)
);

create table voice.transfer_work_items (
  tenant_id text not null,
  work_item_id bigserial,
  department text not null,
  provider_call_id text not null,
  outcome text not null check (outcome in ('no_responder','caller_abandoned','runtime_unavailable')),
  status text not null default 'open' check (status in ('open','claimed','resolved')),
  created_at timestamptz not null default now(),
  primary key (tenant_id, work_item_id)
);

alter table voice.transfer_routes enable row level security;
alter table voice.transfer_routes force row level security;
alter table voice.unfiled_activity enable row level security;
alter table voice.unfiled_activity force row level security;
alter table voice.transfer_work_items enable row level security;
alter table voice.transfer_work_items force row level security;
create policy tenant_isolation on voice.transfer_routes using (tenant_id=current_setting('app.tenant_id',true)) with check (tenant_id=current_setting('app.tenant_id',true));
create policy tenant_isolation on voice.unfiled_activity using (tenant_id=current_setting('app.tenant_id',true)) with check (tenant_id=current_setting('app.tenant_id',true));
create policy tenant_isolation on voice.transfer_work_items using (tenant_id=current_setting('app.tenant_id',true)) with check (tenant_id=current_setting('app.tenant_id',true));
commit;
