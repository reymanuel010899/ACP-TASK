# Tessera Compatibility Contract

**Status:** frozen characterization baseline for consolidation U1

Date: 2026-08-26

This document identifies behavior that consolidation work must preserve, deliberately version, or explicitly deprecate. It does not claim that every current envelope is native A2A v1.

## Stability levels

- **Protocol-stable** — schema/URI changes require a new version and compatibility window.
- **Public-compatible** — routes or payloads may gain fields but cannot silently change meaning or disappear.
- **Legacy-adapted** — current behavior remains available through an adapter while a native A2A representation is introduced.
- **Internal** — may change when its external projections and tests remain stable.
- **Preview** — no compatibility promise beyond preventing data loss and security regressions.

## Frozen public contracts

| Contract | Level | Required behavior |
|---|---|---|
| RFC-0001 core objects and schema `$id`s | Protocol-stable | Existing valid Principal, Session, Capability, Evidence, Verification Result, and Reputation Record fixtures remain valid. Changed shape uses a new schema version. |
| Trust extension URI `https://treessera.com/extensions/trust/v1` | Protocol-stable | URI meaning cannot be silently repurposed. A new incompatible contract uses a new URI/version. |
| Agent Card at `/.well-known/agent-card.json` | Public-compatible | Card declares endpoint, version, capabilities/skills, supported modes, security, and extensions according to its supported A2A version. Credentials never appear in public card data. |
| Trust extension activation/degradation | Protocol-stable | Trust-aware clients opt in; clients that do not opt in receive a valid plain A2A response without Tessera-only requirements. |
| Registry registration and discovery | Public-compatible | Registration validates ownership/authority separately from discovery. Capability search returns registry-grounded card data and reputation without exposing tenant administration data. |
| Current `task.request`, `task.offer`, `task.counter`, `task.accept`, `task.result` exchange | Legacy-adapted | Existing reference agents and fixtures continue through the compatibility gateway until an announced removal. Internal state must not depend on these envelope names. |
| Authentication declared by Agent Card | Public-compatible | Requesters follow the declared scheme, skip providers when credentials are unavailable, and never put dynamic credentials into model context or public cards. |
| Independent verification metadata | Protocol-stable | Provider completion may be plain/provisional; a trusted success requires a valid verifier-bound result. Absence of trust metadata means unknown, not verified or rejected. |

## Canonical semantic invariants

1. A Principal is durable; a Session is short-lived and cannot own reputation.
2. Reputation is indexed by `(principal_id, capability_id)` and zero history is neutral (`verification_rate: null`).
3. Agent endpoint selection is grounded in the registered Agent Card, never invented by a language model or accepted from untrusted task content.
4. An offer is not authorization. Execution requires exact approval bound to actor, tenant, terms/preview hash, expiration, and one-use semantics.
5. Retrying transport cannot create a second provider effect for the same idempotency key.
6. A2A completion and Tessera verification answer different questions. `ProviderCompleted` cannot be presented as trusted success.
7. Provider-authored verification cannot establish independent trust.
8. Discoverability, ownership verification, health, eligibility, and reputation are separate states.

## Current compatibility matrix

| Consumer/provider | Discovery | Task exchange | Trust extension | Expected consolidation behavior |
|---|---|---|---|---|
| Reference Python requester/provider | Registry + Agent Card | Current JSON-RPC/A2A-shaped envelopes | v1 URI and evidence metadata | Must remain green through legacy adapter |
| Tessera Concierge/orchestrator | Registry capability search | Direct provider card URL | Partial; not closed on every result | Move behind gateway without provider-specific endpoint invention |
| Plain A2A client | Agent Card | Supported native A2A version | Not required | Receives valid ordinary A2A behavior |
| Trust-aware A2A client | Agent Card | Supported native A2A version | Opts into a declared version | Receives verification status without new A2A task states |
| Eve agent | Agent Card | Native A2A or compatibility adapter | Optional Tessera extension | Must require no Tessera runtime imports |
| n8n workflow | Adapter-hosted Agent Card and endpoint | Adapter translates workflow invocation/results | Optional Tessera extension | Must pass the same black-box fixtures |

## Characterization fixtures

- `examples/agent-card-with-extension.json`
- `examples/task-message-with-evidence.json`
- `tests/spec/test_a2a_extension_binding.py`
- `tests/agents/test_provider_flow.py`
- `tests/agents/test_requester_flow.py`
- `tests/e2e/test_two_agent_demo.py`
- `tests/e2e/test_competitive_demo.py`

Changes to these fixtures must be reviewed as public-contract changes rather than ordinary refactors.

## Versioning and deprecation

1. Record the old and new representations with fixtures.
2. Add gateway translation and telemetry before changing defaults.
3. Announce a compatibility window and identify affected registrations.
4. Preserve schema `$id` and extension URI meaning; create a new version for incompatibility.
5. Remove a legacy adapter only after usage reaches the accepted threshold and external conformance remains green.

## Preview surfaces

Contacts, campaigns, and voice routing are labeled Preview during consolidation. Their records remain tenant-owned and protected from data loss, but their product APIs are not part of the open agent protocol compatibility promise.

## Registry tenancy boundary

- **Public registry data** — Agent Cards and capability discovery are protocol-facing network data; reading them does not require tenant context.
- **Tenant-private registry data** — ownership, administration, credentials, private endpoints, and mutation authority must require tenant context and remain absent from public discovery payloads.
- A legacy agent with no explicit ownership record may remain discoverable, but it is not administrable by an arbitrary tenant.
- A first-class external agent may also register without Tessera tenant context; it remains discovery-only until an authenticated administrative claim records explicit ownership.
- Moving or claiming ownership is an explicit audited administrative operation, never an inference from a caller-controlled field.
