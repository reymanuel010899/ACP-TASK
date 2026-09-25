create table twilio.whatsapp_session_windows (
    tenant_id text not null,address_id text not null,sender_id text not null,
    opened_at timestamptz not null,expires_at timestamptz not null,
    source_event_key text not null,updated_at timestamptz not null default now(),
    primary key(tenant_id,address_id,sender_id),
    check(expires_at=opened_at+interval '24 hours')
);
create table twilio.whatsapp_templates (
    tenant_id text not null,content_sid text not null,sender_id text not null,
    name text not null,language text not null,category text not null,
    status text not null,quality text,variables jsonb not null default '[]',
    updated_at timestamptz not null default now(),
    primary key(tenant_id,content_sid,sender_id),
    check(content_sid ~ '^HX[0-9a-fA-F]{32}$'),
    check(category in ('marketing','utility','authentication')),
    check(status in ('unsubmitted','pending','approved','paused','disabled','rejected'))
);
alter table twilio.whatsapp_session_windows enable row level security;
alter table twilio.whatsapp_session_windows force row level security;
alter table twilio.whatsapp_templates enable row level security;
alter table twilio.whatsapp_templates force row level security;
create policy whatsapp_windows_tenant on twilio.whatsapp_session_windows using(tenant_id=current_setting('app.current_org_id',true)) with check(tenant_id=current_setting('app.current_org_id',true));
create policy whatsapp_templates_tenant on twilio.whatsapp_templates using(tenant_id=current_setting('app.current_org_id',true)) with check(tenant_id=current_setting('app.current_org_id',true));
grant select,insert,update on twilio.whatsapp_session_windows,twilio.whatsapp_templates to agenttrust_app;
