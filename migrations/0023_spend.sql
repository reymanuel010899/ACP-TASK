create schema if not exists billing;
create table billing.spend_budgets (
    tenant_id text not null, budget_kind text not null,
    budget_id text not null, currency text not null default 'USD',
    ceiling_micros bigint not null check(ceiling_micros >= 0),
    reserved_micros bigint not null default 0 check(reserved_micros >= 0),
    settled_micros bigint not null default 0 check(settled_micros >= 0),
    updated_at timestamptz not null default now(),
    primary key(tenant_id,budget_kind,budget_id),
    check(budget_kind in ('account','campaign'))
);
create table billing.spend_reservations (
    tenant_id text not null, reservation_id text not null,
    campaign_id text, effect_id text not null, channel text not null,
    reserved_micros bigint not null check(reserved_micros >= 0),
    settled_micros bigint, status text not null,
    created_at timestamptz not null default now(), updated_at timestamptz not null default now(),
    primary key(tenant_id,reservation_id), unique(tenant_id,effect_id),
    check(status in ('reserved','settled','released'))
);
create table billing.brand_daily_volume (
    tenant_id text not null,brand_id text not null,day date not null,
    volume integer not null default 0,ceiling integer not null,
    primary key(tenant_id,brand_id,day),
    check(volume>=0 and ceiling>=0 and volume<=ceiling)
);
alter table billing.spend_budgets enable row level security;
alter table billing.spend_budgets force row level security;
alter table billing.spend_reservations enable row level security;
alter table billing.spend_reservations force row level security;
alter table billing.brand_daily_volume enable row level security;
alter table billing.brand_daily_volume force row level security;
create policy spend_budgets_tenant on billing.spend_budgets using(tenant_id=current_setting('app.current_org_id',true)) with check(tenant_id=current_setting('app.current_org_id',true));
create policy spend_reservations_tenant on billing.spend_reservations using(tenant_id=current_setting('app.current_org_id',true)) with check(tenant_id=current_setting('app.current_org_id',true));
create policy brand_daily_volume_tenant on billing.brand_daily_volume using(tenant_id=current_setting('app.current_org_id',true)) with check(tenant_id=current_setting('app.current_org_id',true));
grant usage on schema billing to agenttrust_app;
grant select,insert,update on billing.spend_budgets,billing.spend_reservations,billing.brand_daily_volume to agenttrust_app;
