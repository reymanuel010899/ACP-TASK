# RFC-0002: AgentTrust A2A Extension Binding

- **Status:** Draft
- **Date:** 2026-07-14
- **Depends on:** RFC-0001 (core vocabulary), A2A protocol (Agent Card, messages, extensions)
- **Schema:** `schemas/a2a-extension-descriptor.schema.json` (JSON Schema draft-07)
- **Examples:** `examples/agent-card-with-extension.json`, `examples/task-message-with-evidence.json`

> The project name **AgentTrust** is a provisional placeholder, as is the
> `agenttrust.example` domain in all URIs below. Both will be replaced before
> any non-draft release; the *structure* of this binding is what is specified.

The key words MUST, MUST NOT, REQUIRED, SHOULD, SHOULD NOT, and MAY are to be
interpreted as described in RFC 2119.

## 1. Purpose and scope

RFC-0001 defines six transport-agnostic trust objects (Principal, Session,
Capability, Evidence, Verification Result, Reputation Record). This document
binds them to the A2A protocol using A2A's official extension mechanism —
no changes to A2A itself, no new task states, no new endpoints on the agent.
A third-party A2A implementer should be able to add this extension from this
document alone.

The extension is identified everywhere by the single URI:

```
https://agenttrust.example/extensions/trust/v1
```

## 2. Declaration on the Agent Card

An A2A agent advertises itself via its Agent Card, served at
`https://{domain}/.well-known/agent-card.json`. A provider that supports
AgentTrust MUST add one `AgentExtension` object to
`AgentCard.capabilities.extensions[]`:

```json
{
  "uri": "https://agenttrust.example/extensions/trust/v1",
  "description": "AgentTrust trust layer: signed sessions, verifiable evidence, per-capability reputation.",
  "required": false,
  "params": {
    "principal_id": "atp:principal:agents.example.com:terraformsmith",
    "verification_service_url": "https://verify.agenttrust.example/v1"
  }
}
```

- `uri` (REQUIRED): MUST be exactly the extension URI above.
- `required` (OPTIONAL): SHOULD be `false`. This extension is designed to
  degrade gracefully (§4); declaring it `required: true` would force every
  client to understand it and is NOT RECOMMENDED.
- `params.principal_id` (OPTIONAL, RECOMMENDED): the RFC-0001
  `Principal.principal_id` under which this agent signs Sessions, produces
  Evidence, and accrues Reputation Records.
- `params.verification_service_url` (OPTIONAL, RECOMMENDED): HTTPS base URL
  of the verification service where clients can resolve that Principal
  (its `public_key`), fetch Verification Results, and query Reputation
  Records before delegating work.
- Unknown keys inside `params` are permitted (forward compatibility).

The declaration entry is validated by
`#/definitions/agentExtension` of the descriptor schema. AgentTrust does not
constrain the rest of the Agent Card (`name`, `url`, `version`,
`protocolVersion`, `skills[]`, `securitySchemes`/`security`,
`defaultInputModes`/`defaultOutputModes`); those remain governed by A2A.
Providers SHOULD note in each relevant skill description which RFC-0001
`Capability.id` the skill maps to.

## 3. Activation: the `A2A-Extensions` header

Extension activation follows A2A's standard opt-in flow:

1. The client reads the Agent Card and sees the extension declared.
2. On each request where it wants trust data, the client sends the HTTP
   header `A2A-Extensions:` with a comma-separated list of extension URIs
   that includes `https://agenttrust.example/extensions/trust/v1`.
3. A compliant server echoes back the extensions it actually activated
   (per A2A: the `A2A-Extensions` response header). The client MUST treat
   the extension as active only if the server echoed its URI.

If the client did not request the extension, or the server did not activate
it, the server MUST behave as a plain A2A agent for that request (§4).

## 4. Carrying Evidence on messages

When the extension is active, the agent attaches trust data to the A2A
message that reports a task result, using the two standard A2A message
fields:

- `Message.extensions[]` MUST include the extension URI, signalling that
  extension data is present on this message.
- `Message.metadata` MUST contain the key
  `"https://agenttrust.example/extensions/trust/v1"` — the extension URI
  used verbatim as a namespace key — whose value is the **trust metadata
  payload**:

| Field | Type | Req | Meaning |
|---|---|---|---|
| `evidence` | RFC-0001 Evidence | yes | The Evidence bundle for the task (`evidence_id`, `session_id`, `capability_id`, `schema_valid`, `tests_passed`, `artifact_hashes`, `created_at`). |
| `evidence_status` | `"pending"` \| `"verified"` \| `"rejected"` | yes | Verification status at send time. |
| `verification_result` | RFC-0001 Verification Result | no | REQUIRED in practice when status is `verified` or `rejected` (it is what backs the status); absent while `pending`. |

The payload is validated by `#/definitions/trustMetadata` of the descriptor
schema, which `$ref`s the core `evidence.schema.json` and
`verification-result.schema.json`. `additionalProperties` is `false`:
anything else MUST NOT be added at the top level of the payload (use the
`extensions` bag *inside* the core objects instead).

When `verification_result` is present, its `evidence_id` MUST equal
`evidence.evidence_id`, its `verdict` MUST equal `evidence_status`, and its
`principal_id` names the verifier — which SHOULD be resolvable via the
`verification_service_url` declared on the Agent Card. Clients MUST NOT
trust `evidence_status` on its own; it is a convenience mirror of the
verifier's verdict, and the Verification Result (and ultimately the
verifier's signature/reputation) is the authority.

**Graceful degradation.** For any request where the extension is not active,
the server MUST omit both the metadata key and the URI in
`Message.extensions[]`. The resulting message is a perfectly ordinary A2A
message (`kind`, `messageId`, `role`, `parts[]`, optional `taskId` /
`contextId` / `metadata`) — clients unaware of AgentTrust never see it.
Conversely, extension-aware clients MUST treat the *absence* of the metadata
key as "no trust data" (status unknown), never as `pending` or `rejected`.

See `examples/task-message-with-evidence.json` for a complete task result
message carrying a `verified` payload.

## 5. Relation to A2A task states

A2A defines the task states SUBMITTED, WORKING, INPUT_REQUIRED,
AUTH_REQUIRED, COMPLETED, FAILED, CANCELED, and REJECTED. None of them means
"independently verified", and this binding deliberately adds **no new task
state**. Verification rides orthogonally as `evidence_status`:

| A2A TaskState | `evidence_status` | Trust-layer reading |
|---|---|---|
| COMPLETED | `verified` | Genuinely complete: output independently verified. |
| COMPLETED | `pending` | Complete per A2A; verification not finished. Treat as provisional. |
| COMPLETED | `rejected` | **Not genuinely complete.** The agent claims success but an independent verifier rejected the evidence. Trust-aware clients MUST NOT treat this task as successful, and it counts as `tasks_rejected` in the Reputation Record. |
| COMPLETED | *(absent)* | Plain A2A completion; no trust statement either way. |

A task MAY thus be COMPLETED at the A2A level while being a failure at the
trust level; the two layers never contradict each other because they answer
different questions ("did the agent finish?" vs. "does the work check out?").
`evidence_status` MUST NOT influence A2A state-machine handling.

## 6. Competitive negotiation

The base binding closes a task in a single offer round
(`task.request` → `task.offer` → `task.accept`). This section extends that to
a **competitive** negotiation so price can settle by competition rather than
by taking the first offer. It adds one optional message (`task.counter`) and a
priced Offer body; it adds no new A2A task state.

### 6.1 Message cycle

```
task.request  → task.offer      (provider quotes a public price)
[task.counter → task.offer]     (optional: one round, requester proposes a lower price)
task.accept                     (requester closes at the standing price)
```

The counter round is **optional and single**. A requester MAY send exactly one
`task.counter` per task before accepting; there is no unbounded haggling.

### 6.2 Offer body (`schemas/offer.schema.json`)

`task.offer` carries a public `price` and `currency`
(`$id: https://agenttrust.example/schemas/offer.schema.json`). The price is a
demo-scale number; **no real funds move** — escrow/payment is out of scope for
this binding (a payment extension such as `a2a-x402` is the natural future
home).

### 6.3 Counter body (`schemas/counter-offer.schema.json`)

`task.counter` carries the `task_id` and a `proposed_price`. On receiving it a
provider MUST respond with an updated `task.offer`: it accepts the proposal
(offering at `proposed_price`) **iff** the proposal meets or exceeds its
private reservation; otherwise it holds its floor (re-offering at a price no
lower than that reservation).

### 6.4 The private-reservation rule (normative)

A provider's minimum acceptable price (its reservation/floor) is **private**.
It MUST NOT appear in the Agent Card, in any `task.offer`, in any
`task.counter` response, or in any other serialized message. Both negotiation
schemas set `additionalProperties: false`, so a leaked reservation field is a
validation error by construction. Publishing the floor would collapse
competition — every requester would simply propose exactly the floor.

### 6.5 Reputation-gated selection

Which provider wins is a **requester-side** decision, not a wire concern. A
trust-aware requester SHOULD gate candidates by a per-capability reputation
floor (§Reputation) before letting price compete, and MAY re-check a
candidate's verified-evidence portfolio. Fitness is judged only from verified
facts (reputation, portfolio) — never from a provider's self-reported
internals.

### 6.6 Graceful degradation

`task.counter` is optional. A provider that does not implement it still closes
via `task.request` → `task.offer` → `task.accept`, and a requester that does
not negotiate competitively still uses the single-offer path. Negotiation
never breaks the extension's opt-in, degrade-gracefully contract (§3).

## 7. Descriptor schema

`schemas/a2a-extension-descriptor.schema.json`
(`$id: https://agenttrust.example/schemas/a2a-extension-descriptor.schema.json`)
validates both shapes this binding introduces:

- `#/definitions/agentExtension` — the Agent Card declaration entry (§2);
- `#/definitions/trustMetadata` — the message metadata payload (§4).

The root schema is a `oneOf` of the two, so any AgentTrust-shaped fragment
can be checked against the schema as a whole. Relative `$ref`s
(`evidence.schema.json`, `verification-result.schema.json`) resolve against
the `$id` base `https://agenttrust.example/schemas/`; offline validators
SHOULD preload the sibling schema files into their resolver rather than
fetching them.

## 8. Compliance

An implementation is RFC-0002 compliant if: (a) its Agent Card declaration
entry validates against `#/definitions/agentExtension`; (b) it activates the
extension only for clients that opted in via `A2A-Extensions` and echoes the
activation; (c) every trust metadata payload it emits validates against
`#/definitions/trustMetadata`, appears only under the namespaced metadata
key with the URI mirrored in `Message.extensions[]`, and satisfies the
cross-field rules of §4; and (d) it emits plain A2A messages, with no trust
keys, whenever the extension is inactive.
