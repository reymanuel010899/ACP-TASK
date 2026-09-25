-- Preserve the provider callback correlation carried by the legacy dispatch
-- ledger. It is written before the network boundary and returned to the
-- connector with the claimed intent.

begin;

alter table orchestrator.dispatch_records
    add column callback_token text;

comment on column orchestrator.dispatch_records.callback_token is
    'Opaque signed callback correlation persisted before provider dispatch';

commit;
