-- Consent, suppression, and address usability, as three things that move
-- independently. Expand-only.
--
-- The temptation here is one column on the address called `consent_state`,
-- and it is wrong in a way that only shows up in front of a regulator. A
-- person can hold a perfectly valid written grant for marketing SMS to their
-- work mobile *and* have that same number hard-bouncing, *and* have the
-- number itself still sitting unapproved because an agent proposed it this
-- morning. Those are three facts with three owners, three evidentiary
-- standards, and three ways to change. One enum forces them to overwrite each
-- other, and the one that loses is whichever was written last.
--
-- So: three ledgers, each append-only, each carrying who decided and on what
-- basis (KTD12).
--
--   * `consent_records`      -- a legal grant, per (address, channel, purpose)
--   * `address_suppressions` -- an operational block, per (address, channel),
--                               optionally narrowed to one sender
--   * `address_usability_decisions` -- whether the address may be used at all
--
-- And a fourth table that is not an axis but is constantly mistaken for one:
--
--   * `provider_reachability_events` -- what the carrier will currently carry
--
-- A subscriber texting START to a Twilio number makes that number reachable
-- again at the carrier, automatically, before ACP-TASK has heard about it.
-- Reachability is not consent, and a system that stores them in one place
-- will resume marketing to somebody who said STOP and then asked a support
-- question. They are separate rows here so that "we could send" and "we may
-- send" can never be read off the same field (KTD13).
--
-- The asymmetry that runs through all four tables: a restrictive transition
-- self-executes with whatever actor is at hand, including the contact and
-- including the provider, because the cost of a delayed opt-out is a
-- violation. A permissive transition -- granting, un-suppressing, activating
-- a proposed address -- carries a named human and an authority, enforced by
-- check constraint rather than by a code path someone can route around.
--
-- All four are read the same way -- the current state is the newest row --
-- and all four therefore carry `ledger_sequence` alongside `recorded_at`.
-- The two answer different questions. `recorded_at` is when the decision
-- happened, which is what a regulator asks about, and several rows sharing
-- one value is the ordinary case rather than the edge one: an inbound STOP
-- writes one withdrawal per purpose inside a single transaction under a
-- single `now()`. `ledger_sequence` is the order the rows were written, and
-- it is what "newest" has to mean once the timestamps tie.
--
-- The identifier cannot do that job, though it looks as if it could. These
-- keys are ULIDs, and a ULID is only ordered across millisecond boundaries;
-- inside one millisecond its low 80 bits are random. Ordering an opt-out's
-- five withdrawals by identifier is a coin flip, and the coin decides which
-- purpose the address reads as withdrawn for.
--
-- `generated always as identity` rather than `bigserial`: a caller that
-- could supply the value could change which row reads as current without
-- ever updating a row, and these ledgers are append-only precisely so that
-- cannot happen.

-- The address's owning contact becomes structurally referenceable, so a
-- consent record cannot claim to be about a person the address does not
-- belong to. Adding a unique key is expand-only; nothing existing changes.
alter table contacts.contact_addresses
    add constraint contact_addresses_contact_key
    unique (address_id, tenant_id, contact_id);

-- Consent: the legal grant.
--
-- Scoped per (address, channel, purpose) because dropping any one of the
-- three breaks something concrete. Drop the address and opting a personal
-- mobile out silently opts out the work line. Drop the channel and a voice
-- opt-out kills SMS receipts. Drop the purpose -- the one most often left out
-- -- and either a marketing opt-out blocks a delivery notification, or a
-- marketing campaign rides on consent that was only ever given for
-- transactional messages. WhatsApp makes the last one unavoidable: it grades
-- templates as marketing, utility, or authentication, and those grades carry
-- different consent expectations.
--
-- Append-only. The current state is the newest row, and every state it passed
-- through stays legible, because "we had consent at the time" is the entire
-- defence and a mutated row cannot make it.
create table contacts.consent_records (
    consent_record_id       text not null,
    tenant_id               text not null references identity.organizations(organization_id),
    contact_id              text not null,
    address_id              text not null,
    channel                 text not null
                                check (channel in ('sms', 'whatsapp', 'voice', 'email')),
    -- The three WhatsApp template categories, plus the two purposes that
    -- exist independently of WhatsApp. 'transactional' and 'service' are not
    -- the same thing: an order receipt is transactional, an outage notice is
    -- service, and some jurisdictions permit one without the other.
    purpose                 text not null
                                check (purpose in (
                                    'marketing', 'utility', 'authentication',
                                    'transactional', 'service'
                                )),
    state                   text not null
                                check (state in (
                                    'unknown', 'pending_evidence', 'granted',
                                    'expired', 'withdrawn'
                                )),
    -- Which direction this row moves, and therefore what it costs to write.
    -- 'proposed' is the agent's lane: it records that consent is claimed and
    -- unproven, and it makes nothing usable.
    transition_kind         text not null
                                check (transition_kind in (
                                    'permissive', 'restrictive', 'proposed'
                                )),

    -- -- the evidence the regulatory envelope asks for ------------------
    -- How the person said yes. A web form, a recorded call, and a bulk
    -- import are not equally defensible and must not be indistinguishable.
    capture_method          text,
    -- Two timestamps for one moment. The UTC one orders events; the local
    -- one is what a regulator asks about, because "did you call at 21:40" is
    -- a question about the wall clock where the person was.
    captured_at             timestamptz,
    captured_at_local       text,
    capture_timezone        text,
    -- Whose rules applied when it was captured, frozen at capture. Reading
    -- the contact's current jurisdiction would re-judge a 2026 grant under a
    -- 2029 rule.
    jurisdiction            text,
    -- The exact words shown, not a template identifier. Templates get edited.
    disclosure_text         text,
    disclosure_hash         text,
    -- Proof the box started empty. Null where the capture had no box at all
    -- (a recorded call, an inbound keyword); never false under a grant,
    -- because a pre-ticked box is not consent anywhere that has an opinion.
    default_unchecked       boolean,
    legal_basis             text,
    source                  text,
    -- Who keyed it in, which may well be an agent.
    actor_kind              text not null
                                check (actor_kind in (
                                    'human', 'agent', 'system', 'provider',
                                    'contact'
                                )),
    actor_principal_id      text,
    -- Who authorised it. Required in the permissive direction and only
    -- there -- this is KTD13 written as a constraint.
    decided_by_principal_id text,
    decided_by_authority    text,
    expires_at              timestamptz,

    -- How wide a withdrawal reaches. Today a revocation is read against the
    -- program that sent the message; a cross-topic duty lands 31 January
    -- 2027. All three values are legal now so widening the default is a
    -- configuration change and a re-read, not a migration under time
    -- pressure.
    revocation_scope        text not null default 'program'
                                check (revocation_scope in (
                                    'program', 'topic', 'cross_topic'
                                )),

    -- -- retention -------------------------------------------------------
    -- The transient part: the inbound message that carried the opt-out, kept
    -- only long enough to answer "what exactly did they send".
    inbound_message_body    text,
    content_expires_at      timestamptz,
    content_purged_at       timestamptz,
    -- The durable part. Five years is the floor; recorded consent is held
    -- longer because the recording is the evidence. The check below is what
    -- makes the audit outlive the message rather than merely intend to.
    retained_until          timestamptz not null,

    recorded_at             timestamptz not null default now(),
    -- Insertion order, for the ties `recorded_at` leaves. See the head of
    -- this file for why the identifier cannot break them.
    ledger_sequence         bigint generated always as identity,
    primary key (consent_record_id),
    unique (consent_record_id, tenant_id),
    foreign key (contact_id, tenant_id)
        references contacts.contacts(contact_id, tenant_id),
    -- Address, tenant, and owning contact all at once, so a consent record
    -- cannot be filed against a person who does not hold the address.
    foreign key (address_id, tenant_id, contact_id)
        references contacts.contact_addresses(address_id, tenant_id, contact_id),

    -- State and direction agree, structurally. A row cannot claim to be a
    -- restrictive withdrawal while setting the state to granted.
    check (
        (state = 'granted' and transition_kind = 'permissive')
        or (state in ('withdrawn', 'expired') and transition_kind = 'restrictive')
        or (state in ('unknown', 'pending_evidence') and transition_kind = 'proposed')
    ),
    -- The permissive direction always names a human and the authority they
    -- held. An agent proposal lands in 'pending_evidence' and stays there.
    check (
        transition_kind <> 'permissive'
        or (
            decided_by_principal_id is not null
            and decided_by_authority is not null
            and actor_kind = 'human'
        )
    ),
    -- A grant without evidence is not a grant.
    check (
        state <> 'granted'
        or (
            capture_method is not null
            and captured_at is not null
            and captured_at_local is not null
            and jurisdiction is not null
            and disclosure_text is not null
            and legal_basis is not null
        )
    ),
    -- Never on a pre-ticked box.
    check (state <> 'granted' or default_unchecked is distinct from false),
    -- Where there was a form, the proof is mandatory rather than optional.
    check (
        state <> 'granted'
        or capture_method not in ('web_form', 'embedded_form', 'import_form')
        or default_unchecked is true
    ),
    -- The decision outlives its message body. Not by convention -- a row
    -- whose audit expires first cannot be written.
    check (content_expires_at is null or retained_until > content_expires_at),
    check (content_purged_at is null or inbound_message_body is null)
);

-- The read order, carried into the index that serves it, so "newest row"
-- never falls back to whatever the planner happened to return.
create index consent_records_current
    on contacts.consent_records(
        tenant_id, address_id, channel, purpose,
        recorded_at desc, ledger_sequence desc
    );
create index consent_records_by_contact
    on contacts.consent_records(tenant_id, contact_id, recorded_at desc);
-- The purge sweep's working set: bodies that are due and still present.
create index consent_records_content_expiry
    on contacts.consent_records(content_expires_at)
    where content_purged_at is null and inbound_message_body is not null;

-- Suppression: the operational block.
--
-- Deliberately not scoped by purpose. That is the difference between the two
-- axes in one line: withdrawing marketing consent is a statement about one
-- purpose, while a hard bounce or an inbound STOP is a statement about the
-- address itself and stops everything on that channel. Folding purpose in
-- here would let a marketing unsubscribe silently swallow a password reset.
--
-- `sender_id` narrows it where the provider does. Twilio's STOP is scoped to
-- the sender the subscriber replied to, not to every number the account owns;
-- an administrator's block usually is account-wide, and leaves this null.
create table contacts.address_suppressions (
    suppression_id          text not null,
    tenant_id               text not null references identity.organizations(organization_id),
    address_id              text not null,
    channel                 text not null
                                check (channel in ('sms', 'whatsapp', 'voice', 'email')),
    sender_id               text,
    state                   text not null
                                check (state in (
                                    'none',
                                    'suppressed_by_optout',
                                    'suppressed_by_bounce',
                                    'suppressed_by_admin',
                                    'suppressed_by_provider'
                                )),
    transition_kind         text not null
                                check (transition_kind in ('permissive', 'restrictive')),
    reason_code             text,
    source                  text not null,
    actor_kind              text not null
                                check (actor_kind in (
                                    'human', 'agent', 'system', 'provider',
                                    'contact'
                                )),
    actor_principal_id      text,
    decided_by_principal_id text,
    decided_by_authority    text,
    -- Kept beyond any message body. An opt-out we cannot prove we honoured
    -- is the same as an opt-out we did not honour.
    retained_until          timestamptz not null,
    recorded_at             timestamptz not null default now(),
    ledger_sequence         bigint generated always as identity,
    primary key (suppression_id),
    unique (suppression_id, tenant_id),
    foreign key (address_id, tenant_id)
        references contacts.contact_addresses(address_id, tenant_id),
    -- Lifting is the only permissive move here, and it is the only one that
    -- needs anybody's permission.
    check ((state = 'none') = (transition_kind = 'permissive')),
    -- Administrator, and nobody else. Not the agent that noticed the bounce
    -- cleared, and not the contact manager who can otherwise edit the whole
    -- record -- un-suppressing is the one action that resumes sending to
    -- somebody who was blocked, and it does not get delegated.
    check (
        transition_kind <> 'permissive'
        or (
            decided_by_principal_id is not null
            and decided_by_authority = 'administer'
            and actor_kind = 'human'
        )
    )
);

create index address_suppressions_current
    on contacts.address_suppressions(
        tenant_id, address_id, channel, recorded_at desc, ledger_sequence desc
    );

-- Address usability: whether this destination may be used at all.
--
-- R12 says an agent-proposed number stays unavailable until an authorised
-- human approves it, and that is a fact about the number rather than about
-- the person or their consent. A brand-new number with a signed marketing
-- grant attached is still not sendable until somebody confirms the digits are
-- right, because the grant proves the person agreed, not that the agent
-- transcribed correctly.
--
-- Absence of any row means 'proposed'. That is the fail-closed reading, and
-- it is the one that makes an address written by some future import path
-- unusable until a human looks at it, rather than usable because nobody
-- thought to write a decision.
create table contacts.address_usability_decisions (
    usability_decision_id    text not null,
    tenant_id                text not null references identity.organizations(organization_id),
    address_id               text not null,
    state                    text not null
                                 check (state in ('proposed', 'active', 'retired')),
    transition_kind          text not null
                                 check (transition_kind in (
                                     'permissive', 'restrictive', 'proposed'
                                 )),
    proposed_by_actor_kind   text
                                 check (proposed_by_actor_kind is null
                                        or proposed_by_actor_kind in (
                                            'human', 'agent', 'system',
                                            'provider', 'contact'
                                        )),
    proposed_by_principal_id text,
    decided_by_principal_id  text,
    decided_by_authority     text,
    reason                   text,
    retained_until           timestamptz not null,
    recorded_at              timestamptz not null default now(),
    ledger_sequence          bigint generated always as identity,
    primary key (usability_decision_id),
    unique (usability_decision_id, tenant_id),
    foreign key (address_id, tenant_id)
        references contacts.contact_addresses(address_id, tenant_id),
    check (
        (state = 'active' and transition_kind = 'permissive')
        or (state = 'retired' and transition_kind = 'restrictive')
        or (state = 'proposed' and transition_kind = 'proposed')
    ),
    check (
        transition_kind <> 'permissive'
        or (
            decided_by_principal_id is not null
            and decided_by_authority in ('manage_contacts', 'administer')
        )
    )
);

create index address_usability_current
    on contacts.address_usability_decisions(
        tenant_id, address_id, recorded_at desc, ledger_sequence desc
    );

-- Provider reachability: what the carrier will currently carry.
--
-- This table has no consent column and no suppression column, and that is the
-- point. Twilio answers STOP and START itself, without asking us, and the
-- START restores delivery at the carrier the instant it arrives. If that fact
-- shared a field with consent, a subscriber who opted out of marketing and
-- later texted START to reopen a support thread would find the campaign
-- resumed. Here the restart is observable on its own terms, and the consent
-- ledger and the suppression ledger both keep saying no.
create table contacts.provider_reachability_events (
    reachability_event_id text not null,
    tenant_id             text not null references identity.organizations(organization_id),
    address_id            text not null,
    channel               text not null
                              check (channel in ('sms', 'whatsapp', 'voice', 'email')),
    sender_id             text,
    state                 text not null
                              check (state in ('reachable', 'blocked_by_provider')),
    -- STOP, START, UNSTOP, and their siblings, where the provider told us
    -- which one it acted on.
    provider_keyword      text,
    source                text not null
                              check (source in (
                                  'provider_webhook', 'provider_api', 'operator'
                              )),
    retained_until        timestamptz not null,
    recorded_at           timestamptz not null default now(),
    ledger_sequence       bigint generated always as identity,
    primary key (reachability_event_id),
    unique (reachability_event_id, tenant_id),
    foreign key (address_id, tenant_id)
        references contacts.contact_addresses(address_id, tenant_id)
);

create index provider_reachability_current
    on contacts.provider_reachability_events(
        tenant_id, address_id, channel, recorded_at desc, ledger_sequence desc
    );

-- Append-only, reusing the function 0013 already installed for the
-- orchestrator's audit tables rather than minting a second copy of one
-- `raise`.
create trigger address_suppressions_append_only
before update or delete on contacts.address_suppressions
for each row execute function orchestrator.reject_append_only_mutation();
create trigger address_usability_decisions_append_only
before update or delete on contacts.address_usability_decisions
for each row execute function orchestrator.reject_append_only_mutation();
create trigger provider_reachability_events_append_only
before update or delete on contacts.provider_reachability_events
for each row execute function orchestrator.reject_append_only_mutation();

-- The consent ledger is append-only with exactly one hole in it, and the hole
-- is shaped so nothing can be smuggled through: the retention purge may
-- redact the inbound message body and stamp `content_purged_at`, and may
-- touch nothing else. Every field that carries the decision or its
-- provenance is compared and any change is refused, so "the audit outlives
-- the message" holds even against a purge job that is handed the wrong
-- update statement.
create function contacts.reject_consent_record_mutation()
returns trigger language plpgsql as $$
begin
    if tg_op = 'DELETE' then
        raise exception 'contacts.consent_records is append-only';
    end if;
    if new.consent_record_id is distinct from old.consent_record_id
        or new.tenant_id is distinct from old.tenant_id
        or new.contact_id is distinct from old.contact_id
        or new.address_id is distinct from old.address_id
        or new.channel is distinct from old.channel
        or new.purpose is distinct from old.purpose
        or new.state is distinct from old.state
        or new.transition_kind is distinct from old.transition_kind
        or new.capture_method is distinct from old.capture_method
        or new.captured_at is distinct from old.captured_at
        or new.captured_at_local is distinct from old.captured_at_local
        or new.capture_timezone is distinct from old.capture_timezone
        or new.jurisdiction is distinct from old.jurisdiction
        or new.disclosure_text is distinct from old.disclosure_text
        or new.disclosure_hash is distinct from old.disclosure_hash
        or new.default_unchecked is distinct from old.default_unchecked
        or new.legal_basis is distinct from old.legal_basis
        or new.source is distinct from old.source
        or new.actor_kind is distinct from old.actor_kind
        or new.actor_principal_id is distinct from old.actor_principal_id
        or new.decided_by_principal_id is distinct from old.decided_by_principal_id
        or new.decided_by_authority is distinct from old.decided_by_authority
        or new.expires_at is distinct from old.expires_at
        or new.revocation_scope is distinct from old.revocation_scope
        or new.retained_until is distinct from old.retained_until
        or new.recorded_at is distinct from old.recorded_at
        -- Which row is current is part of the decision, not metadata beside
        -- it. The purge never names this column, so an untouched identity
        -- value arrives here equal to itself and the redaction passes; a
        -- statement that did name it would be refused twice over, since
        -- `generated always` rejects the assignment before the trigger runs.
        or new.ledger_sequence is distinct from old.ledger_sequence
    then
        raise exception 'contacts.consent_records is append-only';
    end if;
    if new.inbound_message_body is not null then
        raise exception 'a consent content purge must redact the message body';
    end if;
    if new.content_purged_at is null then
        raise exception 'a consent content purge must stamp content_purged_at';
    end if;
    return new;
end;
$$;

create trigger consent_records_append_only
before update or delete on contacts.consent_records
for each row execute function contacts.reject_consent_record_mutation();

-- Forced row-level security, the same block every table in this system uses.
-- These four tables carry the most sensitive derivative of the directory --
-- not just who somebody is, but what they refused -- so the same three
-- mechanisms apply without exception: FORCE, tenant-carrying references, and
-- tenant-scoped keys.
do $$
declare table_name text;
begin
    foreach table_name in array array[
        'consent_records', 'address_suppressions',
        'address_usability_decisions', 'provider_reachability_events'
    ] loop
        execute format('alter table contacts.%I enable row level security', table_name);
        execute format('alter table contacts.%I force row level security', table_name);
        execute format(
            'create policy %I on contacts.%I using '
            '(tenant_id = current_setting(''app.current_org_id'', true)) '
            'with check (tenant_id = current_setting(''app.current_org_id'', true))',
            table_name || '_tenant_isolation', table_name
        );
    end loop;
end $$;
