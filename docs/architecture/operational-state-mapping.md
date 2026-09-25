# Operational State Migration Mapping

**Status:** authoritative characterization for consolidation U3

**Captured:** 2026-08-26

This document maps each production SQLite store to its PostgreSQL authority.
It is a migration contract, not permission to keep both stores authoritative.
SQLite remains the source only until the corresponding family cutover marker
is activated. Rows without provable ownership are quarantined; ownership is
never inferred from a provider identifier, address, display name, or request.

## Domain families and cutover order

| Family | SQLite implementation | Production composition roots | PostgreSQL target | Cutover order |
|---|---|---|---|---:|
| Sessions | `services/session/repository.py` | `services/session/app.py`, `services/oauth/app.py`, `services/action_broker/composition.py`, `web/concierge.py` | `identity.web_sessions`, `identity.consumed_identity_proofs` | 1 |
| OAuth and provider authority | `services/oauth/repository.py` | `services/oauth/app.py`, `services/action_broker/composition.py`, `services/workflow_worker/app.py`, `web/concierge.py`, `scripts/slack_phase1_canary.py` | `integrations.oauth_transactions`, existing `integrations.connections`, authority/control-plane tables, `voice.transfer_routes` | 1 |
| Workflow and conversation execution | `agents/orchestrator/workflow_repository.py`, `agents/orchestrator/conversation_state.py` | `services/workflow_worker/app.py`, `services/oauth/app.py`, `web/concierge.py`, `scripts/slack_phase1_canary.py` | existing `orchestrator.workflow_*`, `orchestrator.concierge_*`, resolver, outbox, and projection tables | 2 |
| Action authorization and leases | `agents/orchestrator/action_repository.py` | `services/action_broker/composition.py`, `services/workflow_worker/app.py` | `orchestrator.action_proposals`, `orchestrator.capability_leases` | 2 |
| Dispatch ledger | `agents/orchestrator/dispatch_ledger.py` | orchestrator dispatch paths | `orchestrator.dispatch_records` | 2 |
| Campaigns | `agents/orchestrator/campaign_repository.py` | `web/concierge.py`, `services/campaign_worker/app.py` | existing `campaign.campaigns`, cohort, effects, audit, and throughput tables | 3 |
| Spend | `libs/spend_ledger.py` | campaign and communications execution | existing `billing.spend_budgets`, reservations, and brand volume tables | 3 |
| Twilio events | `libs/twilio_events.py` | `services/twilio_webhook/app.py` | `twilio.events`, `twilio.delivery_verdicts` | 3 |
| WhatsApp windows and templates | `libs/whatsapp_state.py` | communications execution | existing `twilio.whatsapp_session_windows`, `twilio.whatsapp_templates` | 3 |
| Durable throughput | `services/action_broker/rate_limits.py` | action broker and campaign worker | existing `campaign.throughput_limits` | 3 |
| Voice sessions and transcripts | `services/voice_bridge/app.py` | `services/voice_bridge/app.py` | `voice.sessions`, `voice.transcript_events`; existing routing/work-item tables | 3 |

`libs/transfer_routing.py` is already connection-agnostic and does not import
SQLite. It remains part of family 3 because its callers must receive a
tenant-bound PostgreSQL connection and its route queries must preserve the
existing ordering and availability semantics.

The production local-path selectors frozen for removal are
`SESSION_DATABASE`, `OAUTH_DATABASE`, `WORKFLOW_DATABASE`, `ACTION_DATABASE`,
`CAMPAIGN_DATABASE`, `TWILIO_EVENT_DATABASE`, and
`VOICE_TRANSCRIPT_DATABASE`. Deployment-only aliases such as
`TESSERA_SESSION_DATABASE_PATH`, `TESSERA_OAUTH_DATABASE_PATH`, and
`TESSERA_ACTION_DATABASE_PATH` have the same disposition: U7 replaces them
with the shared PostgreSQL configuration rather than introducing new aliases.

## Field and invariant mapping

### Sessions

| SQLite state | PostgreSQL representation | Transformation and invariant |
|---|---|---|
| `web_sessions.session_hash` | `identity.web_sessions.session_hash` | Preserve the SHA-256 digest exactly; raw session IDs never enter storage or reports. |
| principal, CSRF hash, creation/touch/authentication times | same semantic fields | Convert epoch seconds to `timestamptz`; preserve the original instant and CSRF digest. |
| absolute expiry and revocation | same semantic fields | Active means not revoked, before absolute expiry, and inside the configured idle window. |
| `consumed_identity_proofs` | `identity.consumed_identity_proofs` | Proof hash remains globally consume-once; concurrent insert has one winner. |

Session rows are not tenant-owned themselves because authentication must
resolve the principal before an organization is selected. Authorization after
session resolution is still tenant-bound through organization membership.

### OAuth and provider authority

| SQLite state | PostgreSQL representation | Transformation and invariant |
|---|---|---|
| one-use OAuth state, PKCE verifier, requested scopes/capabilities | `integrations.oauth_transactions` | Hashes remain hashes; sensitive verifier material is encrypted or retained only for its short TTL. Consumption is atomic. |
| legacy `oauth_connections` | canonical `integrations.connections` plus `integrations.legacy_connection_map` | Resolve tenant and owner membership; conflicting provider ownership is quarantined, never reassigned. |
| `integration_connections` | existing `integrations.connections` | JSON text becomes `jsonb`; timestamps become `timestamptz`; credential IDs remain Vault references. |
| Slack authority/delegation | existing `integrations.slack_authority_profiles` and delegation tables | Preserve stable IDs, scope sets, expiry, status, consent owner, and revocation. |
| control-plane state/families/senders | existing provider control-plane tables | Preserve tenant stop and narrow enablement decisions atomically. |
| voice routes | existing `voice.transfer_routes` | Replace-per-tenant remains atomic and ordered by priority and route ID. |

### Workflows, actions, conversations, and dispatch

- Existing workflow, revision, step, approval, lease, receipt, attestation,
  conversation, resolver, outbox, and projection identifiers are preserved.
- SQLite JSON text becomes PostgreSQL `jsonb`; encrypted content remains
  encoded by the existing content-crypto boundary before persistence.
- The `(tenant_id, aggregate, version)`, idempotency, attempt, and active-lease
  constraints remain authoritative under concurrent workers.
- Queue claims use row locks; expired claims are recoverable. A provider write
  that may have happened remains `execution_unknown` until reconciliation.
- Legacy action rows carrying the sentinel tenant `legacy` cannot be assigned
  automatically. They require an administrative ownership decision or remain
  quarantined and unavailable to tenant runtime roles.
- Dispatch keys remain unique per tenant. Repeated identical payloads return
  the established result; a changed payload for the same key is a conflict.

### Campaigns, spend, communications, and voice

- Campaign definition, cohort, envelope, effect, and audit hashes are
  preserved. Boolean-like SQLite integers become PostgreSQL booleans or the
  target check-constrained representation without changing semantics.
- Spend values remain integer micros. Reservation/effect uniqueness and
  non-negative totals are database invariants; concurrent reservation cannot
  exceed the selected ceiling.
- Twilio event keys are tenant-scoped idempotency keys. Verdict movement is
  monotonic and duplicate webhooks do not create duplicate events.
- WhatsApp windows preserve sender/address scope and exact expiry instants;
  template variables become `jsonb` without reordering semantic content.
- Voice session and transcript payloads are tenant-owned sensitive content.
  Reports expose IDs, counts, digests, and reason codes, not transcript text.

## Ownership and quarantine rules

| Classification | Import rule |
|---|---|
| Explicit tenant ID with valid organization and referenced principals | Eligible after foreign-key and semantic validation. |
| Tenant derivable only from a valid canonical connection or workflow foreign key | Eligible only when that relationship is unique and recorded in the import report. |
| Missing, `legacy`, conflicting, or caller-supplied tenant | Quarantine; no automatic ownership assignment. |
| Missing referenced principal, credential, capability, connection, workflow, contact, or sender | Quarantine until the authoritative dependency exists. |
| Corrupt encrypted content or unsupported state | Quarantine without logging or materializing the sensitive payload. |

The administrative disposition process follows
`docs/runbooks/tenant-quarantine.md` and is intentionally unavailable to
ordinary tenant roles.

## Import normalization

- Read source files in SQLite read-only mode and never execute schema repair on
  them.
- Fingerprint the source file, SQLite schema, and each normalized record.
- Convert epoch seconds to UTC instants; reject ambiguous or out-of-range
  values instead of guessing a timezone.
- Parse JSON with duplicate-key rejection and emit canonical semantic hashes.
- Write through tenant-bound PostgreSQL adapters using stable source keys.
- Persist checkpoints, counts, hashes, conflicts, and quarantine reason codes.
- Never place raw tokens, PKCE verifiers, credentials, message bodies,
  destinations, transcripts, or contact data in reports or logs.

## Authority and rollback

Each family moves through `sqlite_authoritative`, `importing`, `ready`, and
`postgres_authoritative`. Before the final marker, a failed import can be
abandoned because SQLite was opened read-only and PostgreSQL received no
production-only writes. The marker flips only after a write quiescence, final
delta, and semantic parity report. After the marker, rollback means deploying
older application code that still uses PostgreSQL; stale SQLite is never
reactivated as an authority.
