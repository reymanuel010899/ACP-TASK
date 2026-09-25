# Tessera Current-State Inventory

**Status:** authoritative characterization for consolidation U1

**Captured:** 2026-08-26

Source of truth: executable code and startup configuration on this branch

## Executive finding

The repository contains a credible A2A trust protocol and a broad product implementation, but it does not yet operate as one closed agent-network product. The local stack can start 11 required and 2 conditional processes. Durable state is split between PostgreSQL and multiple SQLite files, and the generic Concierge path still installs an automatic approval callback. Vertical surfaces are therefore useful implementation proofs, but not evidence that the canonical trusted lifecycle is complete.

## Executable process inventory

`scripts/dev-stack.sh` is the authoritative local product startup entrypoint.

| Process | Port | Responsibility | Durable dependencies | Consolidation disposition |
|---|---:|---|---|---|
| `registry` | 8090 | Principals, Agent Cards, capability discovery, reputation views | PostgreSQL; Redis for cache/replay paths | Preserve network responsibility; later front through A2A compatibility boundary |
| `vault` | 8003 | Encrypted credentials and key material | PostgreSQL | Preserve as security boundary |
| `verification` | 8080 | Evidence verdicts and reputation projection | PostgreSQL | Preserve independent execution boundary |
| `runner` | 8110 | Executes the reference provider task path | Registry and verification services | Keep as reference/runtime boundary; do not make it mandatory for external agents |
| `session` | 8120 | Browser/session assertions and account resolution | SQLite by default | Migrate into control-plane PostgreSQL module |
| `oauth` | 8121 | Provider OAuth and connection authority | SQLite by default plus Vault | Migrate durable state; compose into control plane while retaining Vault boundary |
| `action_broker` | 8122 | Authorized provider effects, receipts, limits, rotation | PostgreSQL plus SQLite rate-limit path | Retain isolated effect boundary; normalize persistence |
| `concierge` | 8130 | BFF/orchestrator entrypoint and vertical routing | PostgreSQL plus several SQLite repositories | Become the canonical orchestration/API surface behind control-plane modules |
| `workflow_worker` | background | Claims and executes durable workflow steps | SQLite workflow/action/OAuth stores by default | Preserve execution interface; migrate state and keep separately scalable |
| `twilio_webhook` | 8140 | Twilio event ingestion | SQLite by default | Keep provider ingress boundary; normalize event persistence |
| `frontend` | 3000 | Next.js Console and BFF proxy routes | Browser session state plus backend APIs | Preserve human control plane |
| `voice_bridge` | 8150, conditional | Realtime voice bridge when `XAI_API_KEY` exists | SQLite transcript/session store | Frozen vertical adapter; retain only as isolated integration proof |
| `campaign_worker` | background, conditional | Campaign execution when a factory is configured | SQLite campaign/workflow paths | Frozen vertical worker; no expansion during consolidation |

Additional independently runnable reference or application processes exist under `agents/provider`, `agents/requester`, `apps/marketplace`, `apps/gig_board`, `audit`, and `agent_marketplace`. They are protocol demonstrations or secondary applications and are not required by `scripts/dev-stack.sh`.

## Durable-store inventory

### PostgreSQL-backed production paths

- `libs/db.py` supplies pooled transactions and organization binding.
- Registry, Vault, Audit, capability catalog, marketplace/gig-board, contacts, contact consent/import/permissions, provider control plane, and canonical reputation repositories have PostgreSQL implementations.
- Migrations currently span identity, registry, trust, audit, vault, marketplace, tenant organizations, integrations, contacts, Twilio, spend, campaigns, voice, and directory repairs.

### SQLite-backed production defaults

| Store | Implementation/default |
|---|---|
| Sessions | `services/session/repository.py`; `SESSION_DATABASE=tessera-sessions.db` |
| OAuth/connections | `services/oauth/repository.py`; `OAUTH_DATABASE=tessera-oauth.db` |
| Workflows | `agents/orchestrator/workflow_repository.py`; `WORKFLOW_DATABASE=tessera-workflows.db` |
| Actions | `agents/orchestrator/action_repository.py`; `ACTION_DATABASE=tessera-actions.db` |
| Conversation state | `agents/orchestrator/conversation_state.py` |
| Dispatch ledger | `agents/orchestrator/dispatch_ledger.py` |
| Campaigns | `agents/orchestrator/campaign_repository.py` |
| Spend ledger | `libs/spend_ledger.py` |
| Twilio events | `libs/twilio_events.py`; `TWILIO_EVENT_DATABASE=tessera-twilio-events.db` |
| WhatsApp state | `libs/whatsapp_state.py` |
| Transfer routing | `libs/transfer_routing.py` |
| Distributed rate limits | `services/action_broker/rate_limits.py` |
| Voice sessions/transcripts | `services/voice_bridge/app.py`; `VOICE_TRANSCRIPT_DATABASE=tessera-voice.db` |

SQLite remains valid for isolated unit tests and disposable examples. It is not a production scaling target.

## Public contract inventory

The contracts to characterize and preserve before refactoring are:

- RFC-0001 objects: Principal, Session, Capability, Evidence, Verification Result, and Reputation Record.
- RFC-0002 trust extension URI: `https://treessera.com/extensions/trust/v1`.
- Agent Card discovery at `/.well-known/agent-card.json`.
- Registry registration, search, Principal, capability, reputation, and federation routes documented in `registry/app.py` and `registry/DEPLOYMENT.md`.
- Current provider exchange: `task.request -> task.offer -> optional task.counter -> task.accept -> task.result` over the current JSON-RPC/A2A-shaped endpoint.
- Graceful degradation when a client does not activate the trust extension.
- Frontend BFF routes under `frontend/src/app/api/`, which proxy browser requests to backend services.

The current custom task envelopes are compatibility inputs, not a declaration that Tessera already implements every A2A v1 operation.

## Canonical flow status

| Stage | Current evidence | Status |
|---|---|---|
| Interpret outcome | `agents/orchestrator/brain.py`, Concierge catalog injection | Implemented with provider-specific branches |
| Discover agents | Registry capability search and `agents/orchestrator/tools.py` | Implemented |
| Compare/negotiates offers | Requester/orchestrator offer and counter flows | Implemented in reference/generic paths |
| Exact human approval | Approval models and UI cards exist | Divergent; generic Concierge still uses `always_approve_callback` |
| Durable execution | Workflow worker, leases, action broker, receipts | Implemented but SQLite-backed in key paths |
| Independent verification | Verification service and reference e2e flow | Implemented in reference path, not closed after every Console result |
| Reputation update | PostgreSQL and verifier projections exist | Present but not universally coupled to canonical completion |
| User-visible trusted result | Result presenters and Console projections | Partial; some paths can report provider success before independent verification |

## Product-surface classification

| Surface | Classification | Policy during consolidation |
|---|---|---|
| Agents, capabilities, tasks, approvals, evidence/audit | Core | May change only to close the canonical trusted flow |
| Registry, A2A contracts, Principal identity, verification, reputation | Protocol/network core | Preserve compatibility; add conformance tests before modification |
| Integrations and credential Vault | Supporting core | Security and compatibility work allowed |
| Contacts, campaigns, voice routing | Preview verticals | Frozen except data-loss, security, and canonical-flow proof work |
| Marketplace, organizations, contracts, negotiations, disputes, billing dashboards | Mixed demo/product surfaces | Do not present fixture data as live; no feature expansion in consolidation |
| Slack, Google, Twilio | External action adapters | Maintain existing behavior; new providers require a separate decision |

## Known architectural risks

- Multiple processes share concepts without one control-plane composition or health view.
- Multiple SQLite stores prevent safe horizontal scaling and consistent RLS.
- Tenant context and legacy `NULL` ownership policies are not yet uniformly fail-closed.
- Automatic generic approval can authorize effects without exact human intent.
- Provider completion and trusted completion are not consistently separated in product paths.
- Static/demo surfaces can make product maturity appear greater than the backing data.
- Protocol drafts, implemented database migrations, and README status have drifted apart.

## Update rule

Any change that adds a deployable process, durable store, public contract, or product surface must update this inventory and `tests/architecture/test_architecture_contracts.py` in the same change.
