# Tessera Strategy

## Product thesis

Tessera is an open network where a person or agent can request an outcome and safely delegate it to the best available external agent. Tessera is not an agent framework and does not require providers to use its runtime. Eve, n8n, Python, Vercel AI SDK, LangGraph, or any other implementation may participate by publishing a compatible Agent Card and A2A endpoint.

The network earns trust by closing a loop that ordinary discovery and messaging do not close:

`request -> discovery -> offers -> exact approval -> durable execution -> independent verification -> reputation`

Provider self-report is never sufficient for trusted completion. Reputation belongs to a durable Principal and accrues separately for each capability.

## Who it serves

- People and businesses that need an outcome but do not know which agent can deliver it.
- Agent builders who want discovery, demand, negotiation, trust, and reputation without adopting Tessera's internal framework.
- Operators who need tenant isolation, approvals, auditability, recovery, and clear operational state.
- Other orchestrators that want to discover and transact with Tessera-compatible agents over published contracts.

## Product layers

1. **Protocol** — transport-neutral identity, evidence, verification, and reputation vocabulary plus the Tessera A2A trust extension.
2. **Network** — registration, Agent Card discovery, capability search, endpoint grounding, eligibility, and reputation lookup.
3. **Orchestrator** — interpretation, discovery, offer comparison, approval, durable execution supervision, verification, and result presentation.
4. **Console** — the human control plane for requests, offers, approvals, tasks, connections, evidence, and operational status.
5. **Vertical applications** — contacts, campaigns, voice, Slack, Google, Twilio, and future domain experiences built on the core. These are consumers of the network, not the definition of it.

## Near-term strategy

The current priority is consolidation. Until the canonical trusted task flow is complete, secondary vertical development is frozen except for security fixes, data-loss fixes, and work required to exercise the canonical flow.

The consolidation sequence is:

1. Make the current and target architecture explicit.
2. Establish PostgreSQL as the durable production source of truth with strict tenant isolation.
3. Reduce process and persistence divergence behind compatibility boundaries.
4. Remove implicit approval and close independent verification plus reputation.
5. Prove framework neutrality with independently implemented external agents.

## Non-goals for consolidation

- Rewriting Tessera in Eve, TypeScript, or another agent framework.
- Building a competing transport instead of using A2A.
- Introducing Kubernetes, Kafka, OpenSearch, or a service mesh without measurements that justify them.
- Moving real money or presenting negotiated price as escrow.
- Expanding CRM, campaigns, billing, or organization dashboards before the core release gates pass.

## Success measures

- One canonical trusted lifecycle is used by generic and provider-specific requests.
- Every external effect is bound to an exact, unexpired human approval and an idempotency key.
- Every trusted success resolves to independently verified evidence and one per-capability reputation update.
- Production durable state no longer depends on local SQLite files.
- Tenant-owned rows fail closed under non-owner PostgreSQL roles.
- External Eve, Python, and n8n agents pass the same black-box conformance suite.
- Operators can follow a request from interpretation through verification using one correlation chain.

## Decision rule

When evaluating new work, prefer the option that strengthens the framework-neutral trusted delegation loop. Work that adds another vertical path, state store, orchestration variant, or public contract must show why the canonical core cannot serve it first.
