# AgentTrust

> The project's brand is **Tessera** and its domain is **`treessera.com`**
> (the `treessera` spelling matches the registered PyPI package, since bare
> `tessera` was taken). All protocol URIs — the trust extension and schema
> `$id`s — now use `treessera.com`. "AgentTrust" remains the working name of
> the *protocol* described here; the SDK ships as `treessera`.

A **trust / verification / reputation layer for AI agents**, built as an
official **[A2A](https://a2a-protocol.org/) extension** — not a rival
protocol. A2A (Google, now under the Linux Foundation) and MCP already solved
agent **discovery** and **tool-calling**. Neither defines:

- **durable identity** — a long-lived entity that accrues reputation across
  tasks, separate from the throwaway session that runs a single task;
- **evidence-backed result verification** — a task is not "done" until an
  *independent* verifier validates the evidence; self-reporting never counts;
- **portable, per-capability reputation** — a score that travels across
  platforms instead of living inside one marketplace.

Tessera's product direction is broader than this reference protocol: it is an
open network where a person or orchestrator can discover independently built
agents, compare offers, approve exact work, supervise durable execution, and
accept success only after independent verification. Agents do **not** need to
use Tessera's runtime; they join through a compatible Agent Card and A2A
endpoint. See [`STRATEGY.md`](STRATEGY.md), the
[`current-state inventory`](docs/architecture/current-state-inventory.md),
the [`target architecture`](docs/architecture/target-architecture.md), and
the [`compatibility contract`](docs/architecture/compatibility-contract.md).

Building a rival messaging protocol would fight A2A/MCP on ground they already
own and risk the fate of FIPA ACL (1997), which "never survived contact with
the open internet." So AgentTrust rides on top of A2A's documented extension
mechanism, exactly as prior extensions (`a2a-x402` for payments, an OID4VP
credential extension) already do.

## The two ideas

1. **Principal vs Session.** A `Principal` is a durable ed25519 identity that
   accrues reputation. A `Session` is a short-lived, disposable working
   context, cryptographically signed by its issuing Principal. Reputation is
   anchored to the Principal, never to the ephemeral Session.
2. **Verification gates completion.** Reputation only moves when an
   independent Verification Result validates the submitted Evidence. A
   provider saying "done" is not enough.

## Competitive pricing

Providers compete on price. A requester asks several qualified providers for
offers, runs a single counter-offer round with the cheapest, and closes with
the fair-price winner. Two rules keep it honest:

- **Trust gates price.** A provider must clear a per-capability reputation
  floor to be eligible; only then does price compete. Fitness is judged from
  verified facts (reputation, a re-checkable portfolio of verified work),
  never from a provider's self-reported internals.
- **The floor is private.** Each provider has a minimum (reservation) price it
  never publishes — it is not in the Agent Card, the offer, or any counter
  response. A counter below it is declined. Publishing the floor would collapse
  competition, so the schemas forbid it from crossing the wire.

No real money moves — price is a negotiated number (escrow/payment is a
separate, deferred concern). See RFC-0002 §6.

## Authentication & security (optional)

Everything here is **opt-in** — the network runs open by default, and open and
authenticating providers coexist in one network.

- **Provider auth.** A provider may require a bearer token, declared via A2A's
  standard `securitySchemes`/`security` on its Agent Card (no new mechanism).
  It validates the `Authorization: Bearer` header before doing any work; the
  requester reads the scheme, presents its configured token, and simply skips
  any authenticating provider it has no token for. Auth (access) is orthogonal
  to the trust layer (identity). See RFC-0002 §7.
- **Admin gating.** The registry's key-minting endpoint can require an admin
  token (`--admin-token`).
- **Rate limiting.** Basic per-IP fixed-window limiting on the public
  endpoints (`--rate-limit N`), returning 429 past the cap.

Deferred to production: TLS/HTTPS, token/key rotation, OAuth2/OIDC, a token
issuer, and staking-based Sybil resistance.

## Layout

```
schemas/     Six transport-agnostic JSON Schemas (the core vocabulary, RFC-0001)
spec/        RFC-0001 (core vocabulary) and RFC-0002 (how it binds to A2A)
examples/    Spec-faithful example artifacts (validated in CI)
registry/    Reference registry — capability search, federatable (U4)
services/    Verification & reputation service (U3)
agents/      Two independently-built demo agents: provider (U6) + requester (U5)
tests/       Per-unit tests + the end-to-end two-agent demo (tests/e2e, U7)
docs/        The plan and the demo runbook
```

### Core vocabulary (RFC-0001)

Six objects, each a draft-07 JSON Schema, independent of any transport:
**Principal**, **Session**, **Capability**, **Evidence**,
**Verification Result**, **Reputation Record**. Keeping them transport-agnostic
preserves the option of an MCP or standalone binding later without a redesign.

### A2A binding (RFC-0002)

The trust objects travel over A2A via a single extension URI declared in
`AgentCard.capabilities.extensions[]`; clients opt in with the
`A2A-Extensions` header; verification status rides as extension metadata
alongside A2A's native `TaskState`. No changes to A2A, no new task states, no
new endpoints — a third-party A2A implementer can add the extension from
RFC-0002 alone. Clients that do not opt in still get a valid A2A response
(graceful degradation).

## Run the demo

The reference implementation is **two agents built independently** — a
requester and a provider — that exercise the full cycle (discovery →
negotiation → execution → evidence → independent verification → reputation
update) with **zero shared code beyond the published spec and schemas**.

The protocol reference stores (registry, vault, audit, verification service,
marketplace/gig-board/agent_marketplace) persist to PostgreSQL 16, with Redis
for deliberately ephemeral state. The broader Console product still has
SQLite-backed session, OAuth, workflow, action, campaign, communications, and
voice paths; those are an explicit consolidation target and must not be
mistaken for the production target architecture. Bring PostgreSQL and Redis up
and apply the schema before running the reference demo:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

docker compose -f infra/docker-compose.yml up -d   # Postgres 16 + Redis 7
psql "$DATABASE_URL" -f infra/roles.sql             # least-privilege roles (idempotent)
python -m tools.migrate                             # apply pending migrations (idempotent)

pytest                        # full suite, including the e2e two-agent demo
pytest tests/e2e -q           # just the two-agent demo (four separate processes)
```

### Strict tenant-isolation verification

Tenant-owned PostgreSQL data uses the single transaction-local setting
`app.current_org_id` and fails closed when it is absent. Agent Cards and
capability discovery remain public; agent ownership is private tenant data.

Run the real RLS release gate against a dedicated test database, never a live
development database:

```bash
createdb agenttrust_test
psql -d agenttrust_test -v ON_ERROR_STOP=1 -f infra/roles.sql
DATABASE_URL=postgresql:///agenttrust_test python -m tools.migrate
TESSERA_ALLOW_SHARED_TEST_DATABASE=1 DATABASE_URL=postgresql:///agenttrust_test \
  pytest -q tests/lib/test_multi_tenancy.py \
           tests/integration/test_strict_tenant_isolation.py
```

The test asserts that runtime roles are neither table owners nor
`BYPASSRLS`. Legacy rows without an organization remain preserved but are
visible only to an administrative repair connection; see
[`docs/runbooks/tenant-quarantine.md`](docs/runbooks/tenant-quarantine.md).

To run it by hand — four processes, one command each — see
[`docs/demo-runbook.md`](docs/demo-runbook.md). The demo task is Terraform
generation: emit an HCL module deploying two containers behind an AWS
Application Load Balancer.

## Scope of this reference

**In scope:** the A2A extension positioning, the Principal/Session identity
model, the federatable reference registry, and the two-agent demo.

**Deliberately deferred** (documented, not built here):

- escrow / payment holding and the business model (commission on verified
  tasks vs. open-source-first);
- multi-hop delegation / subcontracting between agents;
- an MCP binding, or any non-A2A binding of the core vocabulary;
- broader federation across multiple independent registries;
- full Sybil resistance (staking, attestation aggregation) — v1 uses only
  cheap registry-issued invite keys as friction (KTD8), and even ERC-8004
  leaves permissionless Sybil resistance an open problem;
- automatic key rotation — v1 has local key generation plus a
  manually-populated revocation list.

Design rationale and the full unit breakdown live in
[`docs/plans/2026-07-14-001-feat-agent-trust-protocol-plan.md`](docs/plans/2026-07-14-001-feat-agent-trust-protocol-plan.md).

## Status

The RFCs and schemas are draft public contracts with characterization tests.
The reference two-agent flow is implemented. The Console is an active preview:
its integrations and vertical applications exercise useful paths, but the
canonical `request -> discovery -> offer -> approval -> execution ->
verification -> reputation` lifecycle is not yet closed across every product
path. Secondary vertical development is frozen during the architecture
consolidation described in the
[`active plan`](docs/plans/2026-08-25-001-refactor-core-architecture-consolidation-plan.md).

## Secure provider orchestration

Tessera supports tenant-bound Google and Slack connections through its OAuth service, encrypted credential vault, action broker, signed receipts, and revisioned workflow engine. Dynamic workflows are compiled from the live capability catalog; provider combinations are not encoded as named scenarios. Keep Slack and dynamic execution disabled until the sandbox gates in [the Slack runbook](docs/operations/slack-integration-runbook.md) and [the orchestrator runbook](docs/operations/dynamic-orchestrator-runbook.md) pass.

### Local HTTPS Slack Concierge

Copy `.env.example` to `.env`, fill credentials only in the ignored local file,
and register the exact HTTPS callback shown there in the Slack app. Start the
session, OAuth, action-broker, Concierge, workflow-worker, and frontend
services against the same local databases. Run the frontend with Next.js local
HTTPS support:

```bash
cd frontend
npm run dev -- --experimental-https --hostname localhost --port 3000
```

Open `https://localhost:3000`, accept the local development certificate, sign
in, and reconnect Slack after adding scopes. The safe rollout order and manual
F1–F4 sandbox script are documented in
[`agents/orchestrator/README.md`](agents/orchestrator/README.md#7-conversational-slack).
Keep all three conversational flags off until focused tests pass; enable reads,
then writes, then DMs. Existing public-channel listing is independent of these
flags.
# ACP
