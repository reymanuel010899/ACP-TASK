# RFC-0001: AgentTrust Core Vocabulary

- **Status:** Draft
- **Date:** 2026-07-14
- **Schemas:** `schemas/*.schema.json` (JSON Schema draft-07)

> The project name **AgentTrust** is a provisional placeholder.

## 1. Purpose and scope

This document defines the six core objects of the AgentTrust trust layer for
AI agents: **Principal**, **Session**, **Capability**, **Evidence**,
**Verification Result**, and **Reputation Record**. The vocabulary is
transport-agnostic: it does not depend on A2A or any other protocol. Binding
to A2A is specified separately (RFC-0002).

The key words MUST, MUST NOT, REQUIRED, SHOULD, and MAY are to be interpreted
as described in RFC 2119.

## 2. Conventions

- Every object is a JSON object validated by a draft-07 JSON Schema whose
  `$id` is `https://treessera.com/schemas/<name>.schema.json`.
- `additionalProperties` is `false` on every object. Unknown top-level fields
  are a validation error. Extensions MUST be placed in the optional
  `extensions` object present on every type; keys inside it SHOULD be
  namespaced (e.g. `"vendor.example/trace_id"`).
- Timestamps are RFC 3339 strings (`format: date-time`), e.g.
  `2026-07-14T10:00:00Z`.
- Cryptographic material uses **ed25519**. Public keys are the raw 32-byte
  key in standard base64 with padding (exactly 44 characters). Signatures are
  the raw 64-byte signature in standard base64 with padding (exactly 88
  characters). The schemas enforce these lengths syntactically; signature
  *verification* is out of scope for schema validation and MUST be performed
  by consumers.

## 3. Objects

### 3.1 Principal (`principal.schema.json`)

A long-lived cryptographic identity: an agent, an operator, or a verifier.

| Field | Type | Req | Meaning |
|---|---|---|---|
| `principal_id` | string | yes | Stable, globally unique identifier. |
| `public_key` | string (base64, 44 chars) | yes | ed25519 public key. |
| `key_algorithm` | `"ed25519"` | no | Only `ed25519` is defined here. |
| `display_name` | string | no | Human-readable; not unique, not trusted. |

A Principal is the anchor of all trust statements: Sessions are signed by it,
Verification Results name the verifier by it, Reputation Records score it.

### 3.2 Session (`session.schema.json`)

A short-lived working context in which an agent performs tasks. A Session
MUST carry a signed link to its issuing Principal — an unsigned session is
schema-invalid, not merely untrusted.

| Field | Type | Req | Meaning |
|---|---|---|---|
| `session_id` | string | yes | Unique session identifier. |
| `principal_id` | string | yes | Issuing Principal's `principal_id`. |
| `issued_at` | date-time | no | Issue time. |
| `expires_at` | date-time | yes | Session is invalid after this instant. |
| `principal_signature` | string (base64, 88 chars) | yes | ed25519 signature by the Principal over the canonical session claims (`session_id`, `principal_id`, `issued_at`, `expires_at`). |

Consumers MUST verify `principal_signature` against the Principal's
`public_key` and MUST reject sessions past `expires_at`.

### 3.3 Capability (`capability.schema.json`)

A named, versioned skill an agent claims, e.g. `terraform.generate`. It is
the unit against which Evidence is produced and reputation accrues.

| Field | Type | Req | Meaning |
|---|---|---|---|
| `id` | string | yes | Dot-namespaced identifier, lowercase (`^[a-z0-9][a-z0-9_-]*(\.[a-z0-9][a-z0-9_-]*)+$`). |
| `version` | string | yes | Version of the capability contract (semver recommended). |
| `description` | string | yes | Human-readable purpose. |
| `input_schema` | object | no | JSON Schema for valid task inputs. |
| `output_schema` | object | no | JSON Schema for valid task outputs. |

### 3.4 Evidence (`evidence.schema.json`)

A machine-checkable claim bundle produced when a Capability is exercised
inside a Session.

| Field | Type | Req | Meaning |
|---|---|---|---|
| `evidence_id` | string | yes | Unique identifier of the bundle. |
| `session_id` | string | yes | Session under which the work ran. |
| `capability_id` | string | yes | `Capability.id` that was exercised. |
| `schema_valid` | boolean | yes | Output validated against the capability's `output_schema`. |
| `tests_passed` | boolean | yes | The task's acceptance tests passed. |
| `artifact_hashes` | object | yes | Map filename → lowercase hex sha256 of the artifact content. MAY be empty (`{}`) if no file artifacts were produced, but the field itself is REQUIRED. |
| `created_at` | date-time | no | When the evidence was produced. |

Evidence of a *failed* run (`schema_valid: false` or `tests_passed: false`)
is still well-formed Evidence; failure is expressed in the booleans and in
the eventual Verification Result, never by malforming the object.

### 3.5 Verification Result (`verification-result.schema.json`)

The outcome of an independent verifier Principal checking one Evidence
bundle.

| Field | Type | Req | Meaning |
|---|---|---|---|
| `result_id` | string | no | Unique identifier of the result. |
| `evidence_id` | string | yes | The Evidence that was verified. |
| `principal_id` | string | yes | The *verifier* Principal. |
| `verdict` | `"verified"` \| `"rejected"` | yes | Binary outcome. There is no neutral verdict; if a verifier cannot decide, it withholds the result. |
| `reasoning` | string (non-empty) | yes | Why the verdict was reached. |
| `verified_at` | date-time | no | When verification completed. |

A verifier SHOULD independently recompute `artifact_hashes`, re-run schema
validation, and re-execute tests where possible, rather than trusting the
booleans asserted in the Evidence.

### 3.6 Reputation Record (`reputation-record.schema.json`)

Aggregated verification history, indexed by the pair
(`principal_id`, `capability_id`): reputation is per-capability, not global.

| Field | Type | Req | Meaning |
|---|---|---|---|
| `principal_id` | string | yes | The Principal being scored. |
| `capability_id` | string | yes | The Capability being scored on. |
| `tasks_verified` | integer ≥ 0 | yes | Count of `verified` verdicts. |
| `tasks_rejected` | integer ≥ 0 | yes | Count of `rejected` verdicts. |
| `verification_rate` | number in [0, 1] or `null` | yes | `tasks_verified / (tasks_verified + tasks_rejected)`. |
| `updated_at` | date-time | yes | Last update time. |

#### The neutral-reputation rule

A Principal with **zero completed tasks** for a capability is **neutral, not
failed-by-default**. Its record MUST be
`tasks_verified: 0, tasks_rejected: 0, verification_rate: null`.
`null` means "no data"; `0.0` means "everything it did was rejected" — the
two MUST NOT be conflated. Whenever both counts are 0, `verification_rate`
MUST be `null`; whenever any count is positive, it MUST be the derived
number. (The schema cannot enforce the arithmetic; producers MUST.)

## 4. Referential integrity

Objects reference each other by identifier only (`session_id`,
`capability_id`, `evidence_id`, `principal_id`). Schema validation checks
shape, not existence: resolving a reference to the actual object is the job
of the registry/verification layer, which MUST reject dangling references.

## 5. Compliance

An implementation is RFC-0001 compliant if every object it emits validates
against the corresponding schema, its Sessions carry valid ed25519 signatures
verifiable with the issuing Principal's key, and its Reputation Records obey
the neutral-reputation rule of §3.6.
