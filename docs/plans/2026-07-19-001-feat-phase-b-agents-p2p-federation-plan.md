---
title: "Phase B: Agents, P2P, and Credential Vault"
type: feat
created: 2026-07-19
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
execution: code
product_contract_source: ce-plan-bootstrap
origin: docs/plans/2026-07-18-001-vision-agenttrust-federated-ecosystem.md
---

# Phase B: Autonomous Agents, P2P Communication, and Encrypted Credentials

## Goal Capsule

Extend the Phase A federated ecosystem to support autonomous agents as first-class principals that can:
1. Register as independent entities with their own reputation
2. Communicate P2P with apps and other agents without always routing through the Registry
3. Securely store and access encrypted credentials managed by users
4. Discover and transact with services across the federated ecosystem
5. Operate across app boundaries with verifiable accountability

**Outcome:** A production-ready foundation for AI agents operating as autonomous participants in a federated, credential-aware economy.

---

## Problem Frame

### Phase A Limitations

**Phase A delivered:**
- User-level federation (Principals, Sessions, cross-app reputation)
- Centralized Registry as coordination hub
- Three web apps (Console, Marketplace, Gig Board) proving the concept
- Basic user-to-user negotiation flows

**Phase A gaps:**
- No autonomous agent support (agents must be human-initiated)
- No P2P communication (all coordination through Registry)
- No credential storage (agents can't access secrets needed for external services)
- No agent marketplace (no way to discover or "hire" agents)
- Registry becomes bottleneck as ecosystem scales (every interaction verified through Registry)
- New apps must implement federation discovery manually
- No way to extend ecosystem to third-party autonomous services

### Why This Matters

1. **Scalability:** P2P eliminates Registry as bottleneck; apps talk directly for operational work, Registry only verifies permissions retroactively
2. **Autonomy:** Agents become economic actors, not human proxies; can make decisions, negotiate, and accrue reputation independently
3. **Security:** Encrypted credential vault allows users to delegate work to agents without exposing secrets
4. **Ecosystem Velocity:** Agent marketplace and federation discovery lower friction for third-party builders to join
5. **Trust at Scale:** Independent reputation layer for agents enables trust without centralized authority

### Gap Examples

- **Today:** User A wants to post a task. Registry must verify User A's permission. User A waits. Registry is queried.
- **Tomorrow (P2P):** User A posts task directly to Marketplace. Marketplace verifies with Registry asynchronously. Faster for user, less Registry load.

- **Today:** Task requires API call to external service. Agent has no way to store API key. Requires human intervention for every task.
- **Tomorrow:** Agent stores encrypted API key in user's vault. Agent can execute work autonomously, decrypt key only when needed.

- **Today:** No way to find or hire an agent to work on your behalf. Requires manual configuration.
- **Tomorrow:** Agent marketplace lets users discover agents, hire them, grant scoped permissions, revoke access.

---

## Success Criteria

### Must-Haves ✅
- [ ] Agents register as Principals in Registry with independent reputation
- [ ] Agent can make autonomous requests (no human initiation) to other apps
- [ ] P2P API contract defined and implemented (apps communicate directly, verify with Registry)
- [ ] Encrypted credential vault operational; agents can retrieve scoped credentials
- [ ] Agent marketplace enables discovery and hiring flow
- [ ] New app can join ecosystem via federation discovery (auto-discovery of Registry, apps)
- [ ] Cross-app agent coordination tested (Agent A in Console hiring Agent B in Marketplace)
- [ ] Credential access audit trail maintained (who accessed what, when)

### Nice-to-Haves 📈
- [ ] Agent-to-agent messaging (beyond request/response)
- [ ] Credential rotation and expiry policies
- [ ] Rate limiting per agent/app
- [ ] Web UI for marketplace (in Console or separate)
- [ ] Credential delegation chains (A delegates to B delegates to C)
- [ ] Transparent KDF migration PBKDF2 → Argon2id (re-derive + re-wrap DEK on next login; enabled by versioned `kdf` metadata from Decision 8)
- [ ] Hardware-backed client key storage (WebCrypto non-extractable keys, Secure Enclave/StrongBox on mobile)

### Out of Scope ❌
- [ ] Production security audit
- [ ] Formal access control policies (can implement MVP policies)
- [ ] Multi-signature or threshold schemes for credentials
- [ ] Advanced recommendation algorithms for marketplace
- [ ] Sophisticated rate limiting or DDoS mitigation
- [ ] Full P2P mesh (star topology with Registry as signaling hub acceptable for Phase B)
- [ ] Autonomous protocol updates (governance deferred)

---

## Architectural Overview

### System Model

```
┌─────────────────────────────────────────────────────────────────┐
│                      Federated Ecosystem                        │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Distributed Apps & Agents                              │  │
│  │  ┌──────────┐    ┌──────────┐    ┌──────────┐          │  │
│  │  │  App 1   │◄──►│  App 2   │◄──►│ Agent A  │  [P2P]   │  │
│  │  │ Console  │    │Marketplace   └──────────┘            │  │
│  │  └────┬─────┘    └────┬─────┘                            │  │
│  │       │               │                                   │  │
│  │  ┌────────────────────────────────┐                      │  │
│  │  │  Agent Coordinator (in App B)  │                      │  │
│  │  └────────────────────────────────┘                      │  │
│  │                                                           │  │
│  └──────────────────────────────────────────────────────────┘  │
│                           ▲                                     │
│                           │ HTTP                                │
│                           ▼                                     │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  Centralized Services                                   │  │
│  │  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐ │  │
│  │  │  Registry   │  │ Verification │  │ Credential     │ │  │
│  │  │             │  │   Service    │  │ Vault Service  │ │  │
│  │  └─────────────┘  └──────────────┘  └────────────────┘ │  │
│  │                                                           │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Key Changes from Phase A

| Aspect | Phase A | Phase B |
|--------|---------|---------|
| **Agents** | Passive skills in apps | First-class Principals with reputation |
| **Communication** | All through Registry | P2P direct, Registry for verification |
| **Credentials** | None (agents can't store secrets) | Encrypted vault, scoped access |
| **Discovery** | Manual app registration | Automatic federation discovery |
| **Agent Lifecycle** | Created by users manually | Can be hired, managed, revoked |
| **Coordination** | User-initiated | Agent-initiated (autonomous) |

---

## Key Technical Decisions

### Decision 1: P2P Architecture Pattern
**Choice:** Star topology with Registry as signaling hub, not full mesh
- Apps maintain direct HTTP connections where possible
- Registry provides endpoint discovery (where to find App B, Agent C)
- P2P is for performance; Registry is still authoritative for permissions

**Rationale:** 
- Simpler to implement than full mesh
- Registry remains source of truth for federation state
- Scalable: N apps don't require N(N-1)/2 connections
- Easier to debug and monitor

**Alternative rejected:** Full mesh → too complex for Phase B, not necessary

### Decision 2: Agent as Principal (not a Service)
**Choice:** Agents are Principals (ed25519 keys) just like users
- Agents have: principal_id, public_key, reputation, sessions
- Agents can be created by users or by apps
- Agent Principals are immutable; reputation accrues independently

**Rationale:**
- Consistent with RFC-0001 (Principal is the unit of trust)
- No special-case logic for "agent vs user" in Registry
- Agents inherit all user-level federation automatically
- Simpler permission model (Principal has permission, agent is a Principal)

**Alternative rejected:** Agents as service objects → creates parallel trust model

### Decision 3: Credential Vault as Separate Service
**Choice:** Dedicated Credential Vault service (separate from Registry)
- Registry holds user/agent principals and reputation (public-side)
- Vault holds encrypted credentials (private-side)
- Vault never exposes plaintext credentials; only returns them in sealed sessions
- User controls vault; revokes access by revoking agent's capability grants

**Rationale:**
- Separation of concerns (reputation vs secrets)
- Vault can have independent security model (HSM, encryption at rest)
- Easier to audit (who requested what credential, when)
- User retains control (can revoke without knowing credential value)

**Alternative rejected:** Credentials in Registry → mixes public and private data

### Decision 4: P2P Verification Model
**Choice:** Apps verify with Registry on permission checks, but communicate P2P for work
- Step 1: Agent A wants to request work from App B
- Step 2: Agent A queries Registry: "Do I have permission to talk to App B?" (permission check)
- Step 3: If yes, Agent A connects directly to App B's P2P endpoint
- Step 4: App B performs work, reports result to Verification Service
- Step 5: Verification Service updates reputation in Registry

**Rationale:**
- Registry stays responsive (not every message goes through it)
- Permission layer centralized and auditable
- Work layer decentralized (faster, less latency)
- Accountability maintained (Verification Service logs all work)

**Alternative rejected:** Trust on first use → no permission layer, harder to revoke

### Decision 5: Credential Access Control (Scopes)
**Choice:** Agents have scoped capabilities; each scope grants access to specific credentials
- User grants Agent: "access.aws" scope → agent can retrieve AWS credentials
- User grants Agent: "access.github" scope → agent can retrieve GitHub token
- Scopes are revocable and auditable

**Rationale:**
- Least privilege (agent only gets credentials it needs)
- User can revoke specific scopes without recreating agent
- Audit trail shows what credentials were accessed
- Compatible with credential rotation

**Alternative rejected:** All-or-nothing (agent can access all credentials or none) → poor security

### Decision 6: Agent Lifecycle Management
**Choice:** Agents created by users, discoverable in marketplace, hired for work
- User creates agent via Console: "Create agent to manage AWS infrastructure"
- Agent appears in marketplace with reputation, pricing, capabilities
- Other users/apps can hire agent for tasks in their scope
- Agent continues to work until revoked by creator or marketplace moderator

**Rationale:**
- Clear ownership model (user creates, user revokes)
- Economic incentive (agents with good reputation earn more work)
- Marketplace enables specialization (agents become SMEs)
- Composable: agents can hire sub-agents for delegated work

**Alternative rejected:** Registry-owned agents → removes user agency

### Decision 7: Federation Discovery Protocol
**Choice:** Pull-based discovery with Registry as signaling hub
- New app queries Registry: "Who else is in the ecosystem?"
- Registry returns list of apps, their endpoints, capabilities
- New app can then P2P connect to other apps for coordination
- Registry can register app and make it discoverable by others

**Rationale:**
- Simple to implement (no pub/sub or gossip protocol needed)
- Registry is already the federation coordinator
- New apps don't need manual configuration
- Low latency (few queries needed)

**Alternative rejected:** Gossip protocol → overkill for Phase B scale

### Decision 8: Key Management — Envelope Encryption + PBKDF2 (MVP)
**Choice:** Three-tier key hierarchy (envelope encryption) with PBKDF2-SHA256 as the MVP KDF

```
Master Password (user)
    ↓ PBKDF2-SHA256, 600,000 iterations (WebCrypto native, client-side only)
KEK (Key Encryption Key) — derived at login, NEVER stored anywhere
    ↓ wraps/unwraps
DEK (Data Encryption Key) — one per user, stored ENCRYPTED in Vault
    ↓ encrypts/decrypts
Data (principal private key, AWS keys, GitHub tokens, ...)
```

**Sub-decisions:**
- **KDF for MVP: PBKDF2-SHA256 with 600k iterations** (OWASP-acceptable), via WebCrypto in the browser and `hashlib.pbkdf2_hmac` in Python. Zero new dependencies, no WASM bundle, works on every browser/mobile.
- **KDF metadata versioned from day 1:** every stored blob carries `{kdf: "pbkdf2-sha256", kdf_params: {iterations: 600000}, salt, nonce}` so a future transparent migration to Argon2id costs nothing (re-derive + re-wrap on next login).
- **Symmetric encryption: XChaCha20-Poly1305** (libsodium/PyNaCl) — authenticated encryption, fast without hardware AES.
- **Ephemeral session keys:** at login, the DEK decrypts the principal private key in memory for milliseconds, derives a short-lived session key (TTL 15 min, renewable), then the private key and DEK are zeroed from memory. Session keys sign all transactions — the real private key almost never exists in decrypted form.
- **Rotation is event-based, not clock-based:** the DEK is re-wrapped (a ~32-byte operation, microseconds) on: password change, login from a new device, agent revocation, anomaly detected in audit log. Safety-net clock rotation: re-wrap every 24h. Data is NEVER re-encrypted — only the envelope rotates.
- **Multi-device flow:** private key lives encrypted in the Vault (not device-local), so the user logs in from any device with username + master password → client derives KEK → unwraps DEK → unwraps private key in memory → signs → discards. No plaintext key ever touches disk or network.
- **Zero-knowledge Vault:** the server stores only wrapped blobs; neither the Vault operator nor an attacker with a full DB dump can decrypt anything without brute-forcing each user's password through 600k PBKDF2 iterations.

**Rationale:**
- Envelope encryption gives max security AND max performance: rotating the envelope is O(32 bytes) regardless of how many credentials the user has — vs re-encrypting everything on naive rotation schemes
- PBKDF2 keeps the MVP dependency-free and debuggable (no WASM in the frontend after Phase A's Vite/CORS pain); envelope encryption makes the KDF choice less critical since attackers only ever obtain wrapped DEKs
- Ephemeral session keys give a smaller exposure window (milliseconds) than any clock-based re-encryption scheme, at ~zero overhead
- Versioned KDF metadata makes the Argon2id upgrade a transparent nice-to-have, not a migration project

**Alternatives rejected:**
- Argon2id for MVP → stronger vs GPU attacks but requires a 200-400KB WASM bundle in the browser, `argon2-cffi` in Python, and slow logins (1-3s) on low-end mobiles; deferred to post-MVP transparent migration
- Per-minute re-encryption of stored credentials → catastrophic Vault overhead at scale (O(users × credentials) crypto ops/min), session desync, broken UX; envelope + ephemeral session keys achieve a strictly smaller exposure window for free
- Device-local private key storage → breaks multi-device login (key trapped on one phone); rejected in favor of Vault-stored wrapped keys

---

## Implementation Units

### U5: Agent Principal Registration & Reputation

**Goal:** Extend Registry to support Agent Principals as first-class entities with independent reputation tracking.

**Requirements:**
- Agent can register as a Principal (ed25519 key) in Registry
- Agent Principal has independent reputation records (separate from user Principal)
- Registry tracks agent-specific metadata: created_by (user Principal), capabilities, pricing
- Agents can issue Sessions (temporary work contexts) just like users
- Reputation accrues independently per agent (not pooled with user)

**Key custody (per Decision 8):**
- The ed25519 keypair is generated **client-side**; only the public key is ever sent to the Registry
- `principal_id` is derived from the public key (fingerprint) — identity is public, authentication is cryptographic
- The private key is stored **wrapped (encrypted) in the Credential Vault**, never on the server in plaintext and never trapped on a single device
- **Multi-device login flow:** user logs in from any device with username + master password → client derives KEK (PBKDF2-600k) → unwraps DEK from Vault → unwraps private key in memory → derives ephemeral session key (TTL 15 min) → private key and DEK zeroed from memory → session key signs all subsequent requests (`session_signature = sign(session_id, session_key)`)
- Registry authenticates requests by verifying signatures against the stored public key — a username alone can never impersonate a Principal

**Dependencies:** None (standalone Registry extension)

**Files:**
- Modify: `registry/app.py` (add agent registration endpoints)
- Modify: `registry/user_index.py` (extend to agent index)
- Create: `registry/agent_index.py` (agent-specific indexing and metadata)
- Create: `registry/schemas/agent-principal.json` (Agent Principal schema)
- Create: `registry/schemas/agent-metadata.json` (agent capabilities, pricing)
- Create: `tests/registry/test_agent_registration.py`

**Approach:**
- Reuse Principal model from RFC-0001, add `agent_metadata` field
- agent_metadata includes: created_by, capabilities (list of capability IDs), pricing (optional)
- Agents can query their own reputation by principal_id
- Agents can issue sessions (same Session model as users)

**Patterns to follow:**
- Mirror user Principal registration pattern
- Same REST endpoint style as existing registry
- Same JSON schema validation

**Test scenarios:**
1. User creates agent → agent registers with created_by=user_principal
2. Agent queries Registry for its reputation → returns {tasks_verified: 0, tasks_rejected: 0}
3. Work completed by agent → Verification Service reports to Registry → agent's reputation updated
4. Multiple agents → each has independent reputation
5. Agent issues session → session carries agent's principal_id and signature
6. Query agents by capability → returns all agents supporting that capability

**Verification:**
- Agent registration endpoint returns agent principal_id
- Agent reputation independently tracked
- Agent can issue valid sessions
- Registry startup includes agent schema migrations

**Verification API Changes:**
- `POST /agents/register` — body `{agent_card, principal_id, created_by, api_key}`
- `GET /agents/{principal_id}` — returns agent metadata and reputation
- `GET /search?agent_capability=<id>` — returns agents supporting capability
- `GET /agents/{principal_id}/reputation?capability=<id>` — agent's reputation for capability

---

### U6: P2P Communication Layer

**Goal:** Enable direct app-to-app communication with Registry-verified permissions.

**Requirements:**
- Apps expose P2P endpoints (distinct from user-facing endpoints)
- Apps can query Registry for other app endpoints
- Agent A can make authenticated requests to Agent B's P2P endpoint
- Registry maintains app registry (where each app is reachable)
- Permission checks happen at Registry before P2P connection allowed

**Dependencies:** U5 (agents must be principals)

**Files:**
- Create: `spec/RFC-0003-p2p-protocol.md` (P2P API contract)
- Modify: `registry/app.py` (add app endpoint registry)
- Modify: `apps/marketplace/server/app.py` (add P2P endpoint)
- Modify: `apps/gig-board/server/app.py` (add P2P endpoint)
- Modify: `web/app.py` (add P2P endpoint if applicable)
- Create: `libs/p2p_client.py` (shared P2P client library)
- Create: `tests/integration/test_p2p_communication.py`

**Approach:**
- Each app registers its P2P endpoint with Registry: `POST /apps/register {app_id, p2p_endpoint, capabilities}`
- P2P endpoint is separate from main app (can be different port/path)
- All P2P requests include: requester_principal_id, session_id, session_signature
- P2P receiver validates signature, checks Registry for permission, processes request
- Permission is a capability grant (Agent A has "request.work" capability for App B)

**Patterns to follow:**
- RFC-0001 Session and signature verification
- REST JSON request/response
- Async where possible (don't block on Registry checks)

**Test scenarios:**
1. App B registers P2P endpoint with Registry
2. Agent A queries Registry: "How do I reach App B?" → gets endpoint
3. Agent A makes P2P request to App B with signed session
4. App B validates signature, queries Registry: "Can Agent A talk to me?" → yes
5. App B processes request, returns result
6. Agent A receives result, submits to Verification Service
7. Verification Service updates Agent A's reputation in Registry
8. Permission denied: Agent A tries to access unauthorized capability → Registry check fails → 403

**Verification:**
- Apps can discover each other via Registry
- P2P communication works without Registry intermediary
- Signatures are validated
- Permission checks enforced

**P2P API Contract (RFC-0003):**
```
Request:
POST {app_p2p_endpoint}/request
{
  "agent_principal_id": "...",
  "session_id": "...",
  "session_signature": "...",  (signed by agent's principal)
  "request_type": "execute.capability",
  "capability_id": "...",
  "input": {...}
}

Response:
{
  "result": {...},
  "evidence_id": "...",
  "verification_requested": true
}
```

---

### U7: Encrypted Credential Vault

**Goal:** Allow users to securely store encrypted credentials and grant agents scoped access.

**Requirements:**
- User can upload credentials (API keys, tokens, passwords) to Vault
- Credentials are encrypted at rest (symmetric encryption with master key derived from user Principal)
- Agents can request access to specific credentials via scoped permissions
- Vault logs all credential access (audit trail)
- Credentials are never sent in plaintext; only exposed in sealed sessions
- User can revoke agent access to credentials without knowing credential values

**Dependencies:** U5 (agents must be principals), Registry (for permission checks)

**Files:**
- Create: `vault/app.py` (Vault service, standalone)
- Create: `vault/crypto.py` (encryption/decryption logic)
- Create: `vault/audit_log.py` (access logging)
- Create: `vault/schemas/credential-storage.json` (schema for stored credentials)
- Create: `vault/schemas/credential-grant.json` (agent→credential permission)
- Create: `libs/vault_client.py` (client library for accessing vault)
- Create: `tests/vault/test_credential_storage.py`
- Create: `tests/vault/test_credential_access.py`

**Approach (envelope encryption per Decision 8):**
- Vault is a standalone HTTP service, zero-knowledge: it stores only wrapped blobs it cannot decrypt
- **Key hierarchy:** master password → PBKDF2-SHA256 (600k iterations, client-side) → KEK (never stored) → wraps per-user DEK (stored encrypted) → DEK encrypts credentials AND the user's principal private key
- Stored blob format (KDF metadata versioned from day 1 for future Argon2id migration):
  ```json
  {
    "encrypted_dek": "...",
    "salt": "...",
    "nonce": "...",
    "kdf": "pbkdf2-sha256",
    "kdf_params": {"iterations": 600000}
  }
  ```
- Symmetric encryption: XChaCha20-Poly1305 (PyNaCl server-side, libsodium.js/WebCrypto client-side)
- Credentials stored as `{metadata, ciphertext, nonce}`; plaintext never reaches the Vault
- When Agent A requests credential: Vault checks if A has "access.{credential_id}" scope, logs access, returns ciphertext that only A's sessions can decrypt
- Credential access control managed by Vault (revocable without credential modification)
- **Rotation (event-based, cheap):** re-wrap the DEK (~32 bytes, microseconds — data itself is never re-encrypted) on: password change, new-device login, agent revocation, audit anomaly. Safety-net: re-wrap every 24h. No per-minute rotation — ephemeral session keys (15-min TTL) already give a smaller exposure window at zero cost
- **Multi-device support:** because the wrapped private key and DEK live in the Vault, the user can log in from any device; nothing key-material ever persists on the device

**Patterns to follow:**
- libsodium/PyNaCl for encryption (XChaCha20-Poly1305 secretbox)
- WebCrypto `deriveKey` (PBKDF2) client-side — native, no WASM bundle
- Audit log: {timestamp, agent_principal_id, credential_id, granted_or_denied}
- Same REST JSON style as Registry and apps

**Test scenarios:**
1. User uploads AWS credential to Vault with master key
2. Vault encrypts and stores; returns credential_id
3. User creates agent and grants it "access.aws" scope
4. Agent A requests AWS credential with session
5. Vault validates agent's session, checks permission, logs access, returns encrypted credential
6. Agent A decrypts credential using its session key (only A's sessions can decrypt)
7. Agent A uses credential to call AWS API
8. User revokes agent's "access.aws" scope → future requests denied
9. Vault audit log shows: {timestamp, agent_A, aws_credential, granted} at [time1], {timestamp, agent_A, aws_credential, denied} at [time2]
10. Multi-device: user registers on device 1, logs in from device 2 with username + master password → KEK derived → DEK unwrapped → private key usable → transactions signed successfully
11. Wrong master password from device 2 → KEK derivation yields wrong key → DEK unwrap fails (Poly1305 auth error) → login rejected, no information leaked
12. Password change → DEK re-wrapped with new KEK → old password no longer unwraps → all credentials still readable with new password (data was never re-encrypted)
13. DEK re-wrap on agent revocation event → audit log records rotation event with trigger reason
14. Stored blob carries `kdf` + `kdf_params` metadata → a blob with unknown KDF version is rejected with a clear error (forward-compatibility check for Argon2id migration)

**Verification:**
- Credentials stored encrypted
- User can grant/revoke access per agent
- Audit trail complete
- Vault survives crashes (data persistent)

**Vault API Contract:**
```
Upload credential:
POST /credentials
{
  "name": "aws-prod",
  "credential_type": "api_key",
  "encrypted_data": "...",  (encrypted with user's master key)
  "user_principal_id": "..."
}
Response: {credential_id, created_at}

Request credential:
POST /credentials/{credential_id}/access
{
  "agent_principal_id": "...",
  "session_id": "...",
  "session_signature": "..."
}
Response: {
  "credential_id": "...",
  "access_granted": true,
  "encrypted_payload": "..."  (encrypted for agent's session)
} or {access_granted: false}

Revoke access:
DELETE /credentials/{credential_id}/grants/{agent_principal_id}
```

---

### U8: Agent Marketplace

**Goal:** Enable discovery and hiring of agents across the federated ecosystem.

**Requirements:**
- Agent Marketplace is a searchable registry where agents advertise their capabilities and pricing
- Users can search for agents by capability, reputation, or pricing
- Users can "hire" agents by granting them scoped capabilities and credentials
- Agents can be rated and reviewed by users who hire them
- Marketplace shows agent reputation, capabilities, pricing, and reviews
- Agents can be disabled or suspended by creator or marketplace moderator

**Dependencies:** U5 (Agent Principals), U7 (Credential Vault), Registry

**Files:**
- Create: `marketplace/agent_marketplace.py` (marketplace service, can be standalone or part of existing app)
- Modify: `web/src/pages/Marketplace/` (add agent marketplace UI to Console)
- Create: `web/src/pages/Marketplace/AgentList.jsx`
- Create: `web/src/pages/Marketplace/AgentDetail.jsx`
- Create: `web/src/pages/Marketplace/HireAgent.jsx`
- Create: `web/src/hooks/useAgentMarketplace.ts`
- Create: `web/src/hooks/useAgentGrants.ts` (manage agent access)
- Create: `tests/marketplace/test_agent_discovery.py`
- Create: `tests/marketplace/test_agent_hiring.py`

**Approach:**
- Marketplace pulls agent listings from Registry (agents query their own metadata and reputation)
- User hires agent by creating a "hiring grant" that specifies:
  - Agent principal_id
  - Scoped capabilities (what work agent can do on user's behalf)
  - Credential scopes (what credentials agent can access)
  - Expiry (when hiring relationship ends)
- Hiring grant stored in Vault as an access control record
- Agent can query its own hiring grants to see who hired it and what work they're authorized to do
- Rating system: after agent completes work, user rates agent in Registry (affects agent's reputation)

**Patterns to follow:**
- Mirror user marketplace patterns if applicable (Marketplace app from Phase A)
- React hooks for state management
- Same HTTP client as existing web apps

**Test scenarios:**
1. Agent A registers in Registry with capabilities: "aws.deploy", "github.commit"
2. User searches marketplace for "aws.deploy" agents
3. User sees Agent A with ⭐⭐⭐⭐ reputation (20 verified tasks)
4. User clicks "Hire" → creates grant: agent_principal=A, capabilities=["aws.deploy"], credential_scopes=["access.aws"], expiry=2026-08-19
5. Agent A checks its hiring grants → sees new hiring from User X
6. Agent A performs task (deploy to AWS)
7. Work is verified; Agent A's reputation increased
8. User rates Agent A ⭐⭐⭐⭐⭐ → affects Agent A's average rating
9. Other users see updated Agent A reputation
10. User revokes hiring grant → Agent A's tasks are denied from then on

**Verification:**
- Agent appears in marketplace after registration
- User can search and find agents
- Hiring flow works (grants created)
- Agent can see its hiring agreements
- Reputation affects search ranking

**Marketplace API:**
```
GET /marketplace/agents?capability=<id>&min_reputation=<x>&sort=reputation
Response: [{agent_principal_id, agent_card, reputation, pricing, reviews}]

GET /marketplace/agents/{agent_principal_id}
Response: {agent_principal_id, capabilities, reputation, pricing, reviews, hiring_details}

POST /marketplace/hiring-grants
{
  "agent_principal_id": "...",
  "user_principal_id": "...",
  "scoped_capabilities": ["aws.deploy", "github.commit"],
  "credential_scopes": ["access.aws", "access.github"],
  "expires_at": "2026-08-19T00:00:00Z"
}
Response: {grant_id, created_at}

POST /marketplace/ratings
{
  "agent_principal_id": "...",
  "rating": 5,
  "review_text": "..."
}
```

---

### U9: Federation Discovery Protocol

**Goal:** Enable new apps to auto-discover the federated ecosystem without manual configuration.

**Requirements:**
- New app queries Registry: "What apps are in the ecosystem?"
- Registry returns list of known apps, their endpoints, capabilities
- New app registers itself with Registry
- New app becomes discoverable by other apps
- New app can query Registry for agents and credentials services
- Apps exchange capability manifests to understand what they offer

**Dependencies:** None (can be done at Registry level)

**Files:**
- Create: `spec/RFC-0004-federation-discovery.md` (federation discovery protocol)
- Modify: `registry/app.py` (add app directory endpoints)
- Create: `registry/app_registry.py` (track registered apps)
- Create: `libs/federation_client.py` (shared client for federation discovery)
- Modify: `apps/marketplace/server/app.py` (call federation discovery on startup)
- Modify: `apps/gig-board/server/app.py` (call federation discovery on startup)
- Create: `tests/integration/test_federation_discovery.py`

**Approach:**
- Registry maintains "app directory" (list of registered apps)
- New app calls `POST /registry/apps/register` with:
  - app_id (unique name)
  - app_endpoint (where to reach this app's main API)
  - p2p_endpoint (where to reach P2P layer)
  - capabilities (list of capability IDs this app supports)
  - agent_marketplace (boolean: does this app run agent marketplace)
  - credential_vault (boolean: does this app provide credential vault)
- Registry returns list of other known apps
- New app can then query:
  - `GET /registry/apps` → all registered apps
  - `GET /registry/apps?capability=<id>` → apps supporting this capability
  - `GET /registry/services` → locate vault and marketplace services

**Patterns to follow:**
- Simple REST queries
- app_id as immutable identifier
- App endpoints are discovered, not hardcoded

**Test scenarios:**
1. New App D starts up
2. App D makes discovery query: "What apps are in this ecosystem?"
3. Registry returns: [Console, Marketplace, Gig Board]
4. App D registers itself: POST /registry/apps/register with app_id="app-d", endpoints, capabilities
5. App D queries agents marketplace: GET /registry/services?type=agent_marketplace → Marketplace app endpoint
6. App D queries credential vault: GET /registry/services?type=credential_vault → Vault endpoint
7. Existing apps query Registry for new apps → they see App D in app directory
8. Other apps can now P2P connect to App D

**Verification:**
- New app can start with just Registry URL (no hardcoded endpoints)
- App is immediately discoverable by others
- Can find vault and marketplace services

**Federation Discovery API (RFC-0004):**
```
Register app:
POST /registry/apps/register
{
  "app_id": "app-d",
  "app_endpoint": "https://app-d.example.com",
  "p2p_endpoint": "https://app-d.example.com/p2p",
  "capabilities": ["task.request", "gig.post"],
  "agent_marketplace": true,
  "credential_vault": false
}
Response: {app_id, registered_at, ecosystem_apps: [Console, Marketplace, Gig Board]}

Query apps:
GET /registry/apps
Response: [{app_id, endpoint, p2p_endpoint, capabilities}]

Query services:
GET /registry/services?type=<type>
where type in [agent_marketplace, credential_vault, verification_service]
Response: {service_type, endpoint, status}
```

---

### U10: Agent-to-App Coordination

**Goal:** Enable agents to autonomously request work from apps and negotiate terms without user intervention.

**Requirements:**
- Agent can query Registry for work opportunities (tasks posted by users)
- Agent can submit requests to apps (P2P) with terms: "I'll complete this task for X reputation"
- Apps present agent requests to users for approval
- User accepts agent's bid → work contract signed (both parties sign)
- Agent performs work → work is verified → both agent and user earn/lose reputation
- Agent can appeal rejected work (if verification is disputed)

**Dependencies:** U5 (agents), U6 (P2P), Verification Service (reputation)

**Files:**
- Modify: `apps/marketplace/server/app.py` (add agent request endpoints)
- Modify: `apps/gig-board/server/app.py` (add agent request endpoints)
- Create: `libs/agent_coordination.py` (shared agent coordination logic)
- Create: `agents/marketplace_coordinator/agent.py` (example agent that coordinates marketplace work)
- Create: `tests/integration/test_agent_work_coordination.py`

**Approach:**
- Apps expose work opportunity listings (tasks, gigs) via P2P endpoints
- Agent can query: `GET /p2p/work-opportunities?capability=<id>&min_reputation=<x>`
- Agent submits request: `POST /p2p/work-requests {agent_principal_id, work_opportunity_id, proposed_terms, session}`
- Work opportunity tracks bids from agents; user can review and accept best bid
- Accepted agent gets temporary permission to access task details (via P2P)
- Agent completes work, submits result to app
- App forwards to Verification Service
- Verification Service updates both user and agent reputation

**Patterns to follow:**
- RFC-0001 Evidence and Verification Result
- Same P2P request/response as U6
- Async flow (agent submits bid, waits for user approval)

**Test scenarios:**
1. User posts task in Marketplace: "Deploy app to AWS, pay 1000 reputation"
2. Agent A queries work opportunities: GET /p2p/work-opportunities?capability=aws.deploy
3. Agent A sees task and submits bid: "I'll do it for 800 reputation, my reputation score: ⭐⭐⭐⭐"
4. Marketplace app notifies User: "Agent A bid 800 reputation"
5. User can see Agent A's reputation, reviews, pricing
6. User accepts Agent A's bid
7. Agent A gets work contract with task details
8. Agent A executes task (calls AWS APIs)
9. Agent A submits result with evidence to Marketplace
10. Marketplace sends to Verification Service
11. Verification Service validates → task complete, Agent A gets +800 reputation, User keeps task completion credit
12. If Agent A's work is disputed, Registry stores dispute record; both parties can appeal

**Verification:**
- Agent can discover work opportunities autonomously
- Agent can submit bids
- User controls acceptance (no work happens without user approval)
- Reputation flows correctly

---

### U11: Cross-App Agent Operations

**Goal:** Prove agents can operate across app boundaries (Agent registered in App A performs work in App B).

**Requirements:**
- Agent registered in Marketplace app can request work from Gig Board app
- Agent's reputation from Marketplace visible in Gig Board
- Agent can bid on gigs from Gig Board
- Work completed in Gig Board updates agent's reputation (visible in Marketplace and Registry)
- Multi-app agent coordination tested end-to-end

**Dependencies:** U5–U10 (everything above)

**Files:**
- Create: `tests/integration/test_cross_app_agent_operations.py`
- Modify: test configs to deploy all apps with independent Registry

**Approach:**
- Existing apps from U10 already support cross-app operations (both use same Registry and P2P protocol)
- This unit is primarily testing/validation that agents work across apps
- Deploy all 3 apps (Console, Marketplace, Gig Board) + Registry + Vault
- Create Agent A in Marketplace, Agent B in Gig Board
- Agent A bids on gig in Gig Board, Agent B bids on task in Marketplace
- Verify reputation updates reflected in both apps

**Test scenarios:**
1. Agent A (principal_id=agent-a) created in Marketplace with capabilities: "aws.deploy"
2. Agent B (principal_id=agent-b) created in Gig Board with capabilities: "design.mockup"
3. User X posts gig in Gig Board: "Design mockups for site"
4. Agent A queries Gig Board for gigs (should find none matching aws.deploy)
5. Agent B queries Gig Board for gigs, finds this one, submits bid
6. User X accepts Agent B's bid, Agent B completes work
7. Agent B's reputation updated in Registry (visible in Marketplace if queried)
8. User Y posts task in Marketplace: "Deploy app to AWS"
9. Agent A queries Marketplace, finds this task, submits bid
10. User Y accepts, Agent A completes work
11. Both Agent A (via Marketplace) and Agent B (via Gig Board) have reputation updated in central Registry
12. Users can verify agents' reputation in their respective apps

**Verification:**
- Agent can work across different apps
- Reputation synchronized across apps
- P2P communication works between different apps
- Registry is single source of truth

---

### U12: Audit & Compliance Logging

**Goal:** Maintain comprehensive audit trails for regulatory compliance, debugging, and accountability.

**Requirements:**
- All agent activities logged: credential access, work requests, bid submissions, work completions
- All registry operations logged: principal registration, reputation updates, permission checks
- Vault logs all credential access with timestamps and grant/deny decisions
- Audit logs are immutable and centralized
- Logs support querying by principal_id, timestamp range, activity type

**Dependencies:** U5–U11 (logging integrated into all above)

**Files:**
- Create: `audit/app.py` (Audit logging service, standalone)
- Create: `audit/audit_log.py` (in-memory + persistent audit store)
- Modify: `registry/app.py` (add audit logging calls)
- Modify: `vault/app.py` (add audit logging calls)
- Modify: `apps/marketplace/server/app.py` (add audit logging calls)
- Modify: `apps/gig-board/server/app.py` (add audit logging calls)
- Create: `tests/audit/test_audit_logging.py`

**Approach:**
- Audit service is a simple HTTP endpoint that all other services can log to
- Each log entry: {timestamp, principal_id, activity_type, resource_id, status (success/failure), details}
- activity_type in: [credential.access, principal.register, reputation.update, permission.check, work.submit, work.complete, agent.hire, agent.revoke]
- Audit logs stored in database; queryable by principal_id, timestamp, activity_type
- Logs are append-only; no deletion or modification

**Patterns to follow:**
- Simple structured logging
- Timestamps in RFC 3339 format
- REST JSON API for querying

**Test scenarios:**
1. Agent A accesses AWS credential → audit log entry: {timestamp, agent-a, credential.access, aws-cred-id, granted}
2. User X grants Agent A hiring agreement → audit log: {timestamp, user-x, agent.hire, agent-a, granted}
3. Agent A submits work in Marketplace → audit log: {timestamp, agent-a, work.submit, task-123, accepted}
4. User Y revokes Agent A's credentials → audit log: {timestamp, user-y, credential.revoke, agent-a, granted}
5. Query audit logs for agent-a: GET /audit?principal_id=agent-a → returns all activities by Agent A
6. Query audit logs for AWS credential access: GET /audit?resource_id=aws-cred-id → shows all access (who, when, granted/denied)

**Verification:**
- All significant events logged
- Logs are queryable
- Audit trail supports compliance verification

**Audit API:**
```
Log activity:
POST /audit
{
  "principal_id": "...",
  "activity_type": "credential.access",
  "resource_id": "...",
  "status": "granted|denied",
  "details": {...}
}

Query logs:
GET /audit?principal_id=<id>&start_time=<t1>&end_time=<t2>&activity_type=<type>
Response: [{timestamp, principal_id, activity_type, resource_id, status, details}]
```

---

## Test Scenarios Per Unit

### U5: Agent Principal Registration

| Test | Input | Expected | Edge Case |
|------|-------|----------|-----------|
| Register agent | agent_card, created_by | agent_principal_id returned | Agent card missing capabilities |
| Agent reputation query | agent_principal_id | {tasks_verified, tasks_rejected, verification_rate} | Non-existent agent → 404 |
| Multiple agents | 3 agents created | Each has independent reputation | Agents with same name/display |
| Agent session issuance | agent_principal_id | Valid session with agent's principal_id | Session expiry enforced |

### U6: P2P Communication

| Test | Input | Expected | Edge Case |
|------|-------|----------|-----------|
| App registration | app_id, endpoints | App discoverable | Duplicate app_id → conflict |
| P2P request | agent_principal_id, session, capability | Request processed | Permission denied → 403 |
| Cross-app request | Agent A (App 1) → App 2 | App 2 processes request | Network timeout → retry |
| Signature validation | Invalid session signature | Request rejected | Signature verification failure |

### U7: Credential Vault

| Test | Input | Expected | Edge Case |
|------|-------|----------|-----------|
| Upload credential | user_principal, encrypted_data | credential_id returned | Encryption failure → 400 |
| Agent access | agent_principal, credential_id, scope | Access granted/denied | Revoked access → denied |
| Audit logging | Credential access | Entry in audit log | Concurrent access logging |
| Credential rotation | New encrypted value | Old credential replaced | In-flight requests affected |

### U8: Agent Marketplace

| Test | Input | Expected | Edge Case |
|------|-------|----------|-----------|
| Agent search | capability, min_reputation | List of agents matching | No agents found → [] |
| Agent hiring | agent_principal, scopes, expiry | grant_id returned | Invalid capability → 422 |
| Agent rating | agent_principal, rating, review | Reputation updated | Duplicate rating (user rates same agent twice) |
| Revoke hiring | grant_id | Agent loses access | Work in progress at revoke time |

### U9: Federation Discovery

| Test | Input | Expected | Edge Case |
|------|-------|----------|-----------|
| App registration | app_id, endpoints | App discoverable to others | Network partition → stale app list |
| Query all apps | (none) | List of all registered apps | Empty ecosystem |
| Query services | service_type=credential_vault | Vault endpoint returned | Vault service down |
| App de-registration | app_id, unregister request | App no longer discoverable | App crashes without unregistering |

### U10: Agent-to-App Coordination

| Test | Input | Expected | Edge Case |
|------|-------|----------|-----------|
| Work opportunity listing | capability=aws.deploy | Tasks matching returned | No matching tasks |
| Agent bid submission | work_opportunity_id, agent_principal | Bid stored, notifies user | User offline (notification queued) |
| User accepts bid | grant_id | Agent gets work contract | Multiple agents bid, user picks one |
| Work completion | result_evidence | Verification requested | Evidence validation fails |

### U11: Cross-App Agent Operations

| Test | Input | Expected | Edge Case |
|------|-------|----------|-----------|
| Agent A (App B) bids on work (App C) | agent_principal, work_id | Bid submitted to App C | Agent not found in App C registry |
| Cross-app reputation visibility | agent_principal | Reputation from both apps | Agent's reputation in App C but not known to App B |
| Multi-app agent work | Agent completes work in App C | Reputation visible in App B | Registry unavailable during work |

### U12: Audit & Compliance Logging

| Test | Input | Expected | Edge Case |
|------|-------|----------|-----------|
| Log credential access | principal_id, credential_id | Entry in audit log | Logging service down → fail closed or queue? |
| Query audit logs | principal_id, timestamp range | Matching entries returned | Massive audit log (performance) |
| Audit immutability | Attempt to modify log | Error (no modification allowed) | Database corruption recovery |

---

## System-Wide Impact

### API Contract Changes

**New Endpoints (Registry):**
- `POST /agents/register` — Register agent Principal
- `GET /agents/{principal_id}` — Get agent metadata and reputation
- `POST /apps/register` — Register app
- `GET /registry/apps` — List all apps in ecosystem
- `GET /registry/services?type=<type>` — Locate services (vault, marketplace)

**New Endpoints (Apps - P2P):**
- `POST /p2p/request` — Receive P2P work request
- `GET /p2p/work-opportunities` — List available work
- `POST /p2p/work-requests` — Submit work bid

**New Services:**
- Credential Vault service (independent HTTP service)
- Audit logging service (independent HTTP service)
- Agent Marketplace (can be part of existing Marketplace app or standalone)

### Data Storage

**Registry:**
- New tables: `agent_principals`, `agent_metadata`, `app_registry`
- Modified tables: `principals` (add type field: user | agent), `reputation_records` (can include agents)

**Vault:**
- New tables: `credentials` (encrypted storage), `credential_grants` (access control), `access_audit_log`
- Database is separate from Registry (dual-database architecture)

**Audit Service:**
- New tables: `audit_log` (immutable log of all activities)

**Apps:**
- Marketplace: new table `work_requests` (bids from agents)
- Gig Board: new table `work_requests` (bids from agents)

### Deployment Topology (Phase B)

```
Production Deployment:

┌─────────────────────────────────────────────────────┐
│ Load Balancer / API Gateway                         │
└─────────────────────────────────────────────────────┘
         ↓              ↓                  ↓
   ┌──────────┐   ┌──────────┐      ┌──────────┐
   │ Console  │   │Marketplace   Gig Board    │
   │ App      │   │ App           App         │
   │ (React)  │   │ (React)       (React)    │
   └────┬─────┘   └────┬──────┘    └────┬─────┘
        │              │               │
        └──────────────┼───────────────┘
                       ↓
        ┌──────────────────────────────┐
        │  Federated Services          │
        │  ├─ Registry                 │
        │  ├─ Credential Vault         │
        │  ├─ Verification Service     │
        │  ├─ Agent Marketplace        │
        │  └─ Audit Logging            │
        │                              │
        │  (All can scale independently)
        └──────────────────────────────┘
```

### User Experience Changes

**User Creating an Agent:**
1. Console: "Create agent" button
2. User specifies: name, capabilities, pricing
3. System generates agent Principal (ed25519 key)
4. Agent registered in Registry, appears in marketplace
5. User can now grant agents credential access and hiring scope

**User Hiring an Agent:**
1. Console: Marketplace tab
2. Search for agents by capability
3. See agent's reputation, pricing, reviews
4. Click "Hire" → specify scopes and expiry
5. Agent notified of hiring, can start accepting work
6. User can revoke anytime

**Agent Performing Work:**
1. Agent (autonomous) queries work opportunities
2. Agent submits bids to suitable work
3. User reviews and accepts bid
4. Agent performs work autonomously (no human intervention)
5. Work verified, reputation updated
6. Agent can bid on more work or be revoked by user

**New App Joining Ecosystem:**
1. New app developer: provide Registry URL
2. New app starts, queries: "What's in this ecosystem?"
3. Registry returns: apps, agents, services
4. New app can immediately P2P connect to other apps
5. No manual configuration or hardcoding

### Security Posture Changes

**Credentials:**
- Phase A: No credential storage
- Phase B: User-controlled encrypted vault; agents can't see plaintext; audit trail maintained

**Agents:**
- Phase A: Manual, supervised by users
- Phase B: Autonomous; scoped permissions; revocable; reputation-based accountability

**Communication:**
- Phase A: All through Registry (single point of verification)
- Phase B: P2P direct, Registry verifies permissions retroactively

**Audit:**
- Phase A: Implicit logs in each app
- Phase B: Central immutable audit log for compliance and debugging

---

## Risks & Mitigations

### Risk 1: P2P Communication Bypasses Audit
**Problem:** Direct app-to-app communication could hide malicious work from verification.
**Mitigation:** All work must eventually be verified (Verification Service logs all work); P2P only speeds up communication, not verification.

### Risk 2: Credential Vault as New Attack Surface
**Problem:** Vault service could be hacked, exposing all user credentials.
**Mitigation:**
- Vault uses strong encryption (NaCl, key derived from user's Principal)
- User's master key never sent to Vault (client-side encryption possible)
- Audit trail enables breach detection and forensics
- Vault can have independent security hardening (HSM, air-gapped backups)

### Risk 3: Agent Autonomy Enables Scale Fraud
**Problem:** Malicious agent could perform thousands of fraudulent tasks before detection.
**Mitigation:**
- Agents must have reputation to be hired (cold start problem, not a concern)
- Verification Service checks all work independently
- User can revoke agent immediately if suspicious
- Audit log enables traceability and recovery

### Risk 4: Registry Becomes Bottleneck for Permission Checks
**Problem:** Every P2P request still queries Registry; doesn't eliminate bottleneck.
**Mitigation:**
- Phase B allows async permission checks (app can proceed optimistically, Registry validates later)
- Phase C can add caching and permission delegation
- Registry can be replicated/sharded if needed

### Risk 5: Federation Discovery Enables Ecosystem-Wide Attack
**Problem:** Bad actor queries Registry, discovers all apps, launches attacks on all.
**Mitigation:**
- App registration requires verification (API key issued by Registry, anti-Sybil)
- Apps can be selective about P2P connections (whitelist/blacklist)
- Rate limiting on P2P endpoints per app
- Audit logs enable quick detection and response

### Risk 6: Credential Rotation Doesn't Invalidate In-Flight Access
**Problem:** User rotates credential while agent is using old one; potential race condition.
**Mitigation:**
- Credential grants are per-version; rotation creates new version
- Old credential access denied after rotation (within deadline)
- Agent must request credential before each work (not cached)
- Audit log shows exact timing of rotation vs access

### Risk 7: Agent Marketplace Enables Spam/Scam
**Problem:** Bad agents spam marketplace with fake credentials, scam users into hiring them.
**Mitigation:**
- Agent registration requires API key (anti-Sybil)
- User ratings are public (enables community policing)
- Reputation threshold for work acceptance (cold start: agents start at neutral)
- Marketplace can flag/suspend suspicious agents

### Risk 8: Audit Log Privacy Concerns
**Problem:** Audit log exposes who accessed what credentials, when; potential privacy leak.
**Mitigation:**
- Audit log access restricted (users can only see their own logs, admins see all)
- Queries are per-principal; no whole-log dumps
- GDPR compliance: right to data deletion (anonymize old logs)
- Encryption at rest for audit logs

---

## Dependencies & Sequencing

### Dependency Graph

```
U5 (Agent Registration)
  ↓
U6 (P2P Communication) ← depends on U5
  ↓
U7 (Credential Vault) ← depends on U5, (optional U6)
  ↓
U8 (Agent Marketplace) ← depends on U5, U7
  ↓
U9 (Federation Discovery) ← depends on U5, U6
  ↓
U10 (Agent Coordination) ← depends on U5, U6, U7, U8
  ↓
U11 (Cross-App Operations) ← depends on U5–U10
  ↓
U12 (Audit Logging) ← can be added retroactively to U5–U11
```

### Recommended Sequencing

1. **U5** (1-2 weeks) — Agent registration in Registry. Unblocks most units.
2. **U6** (2 weeks) — P2P communication layer. Enables direct app coordination.
3. **U7** (2 weeks) — Credential Vault. Unblocks autonomous agents.
4. **U8** (1 week) — Agent Marketplace. Builds on U5 + U7.
5. **U9** (1 week) — Federation discovery. Can run in parallel with U5–U8.
6. **U10** (2 weeks) — Agent coordination logic. Integrates U5–U9.
7. **U11** (1 week) — Cross-app validation. Tests U5–U10 together.
8. **U12** (1 week) — Audit logging. Add to all services incrementally.

**Total Estimate:** 10-12 weeks for MVP (parallel work possible)

---

## Known Unknowns (Deferred to Phase C)

1. **P2P Mesh Topology:** Can we go full peer-to-peer without Registry? Defer to Phase C.
2. **Agent Communication Standards:** How do agents negotiate with each other directly? MVP: only human-initiated.
3. **Delegation Chains:** Can Agent A delegate work to Agent B? MVP: no delegation, only direct work.
4. **Privacy Boundaries:** Can users choose which agents can see which credentials? MVP: all-or-nothing per agent.
5. **Formal Governance:** Who controls protocol evolution? Defer to Phase C.
6. **Multi-Signature Credentials:** Can multiple agents share credential access? MVP: single agent per grant.
7. **Credential Expiry Policies:** Auto-rotation, TTL management? MVP: manual rotation.
8. **Rate Limiting & Quotas:** How many requests per agent per day? MVP: no limits.

---

## Definition of Done (Phase B Complete)

- [ ] Agent can register as Principal in Registry (U5)
- [ ] Agent has independent reputation tracking (U5)
- [ ] Apps can discover each other via Registry (U6)
- [ ] P2P communication works between apps (U6)
- [ ] User can store encrypted credentials in Vault (U7)
- [ ] Agent can request credential access (U7)
- [ ] Credential access is auditable (U7)
- [ ] Agents appear in marketplace (U8)
- [ ] Users can hire agents with scoped permissions (U8)
- [ ] New app can join ecosystem via Registry (U9)
- [ ] Agent can autonomously bid on work (U10)
- [ ] User accepts agent bid → work contract signed (U10)
- [ ] Agent work is verified and reputation updated (U10)
- [ ] Agent works across multiple apps (U11)
- [ ] All activities logged in central audit system (U12)
- [ ] End-to-end integration tests all pass
- [ ] No single point of failure (Registry optional for ops, not required)
- [ ] Agents with good reputation can earn work autonomously
- [ ] Users can revoke agent access anytime
- [ ] Audit logs support compliance queries

---

## Success Metrics (Phase B Proof)

- ✅ Agent creates 10+ bids, wins 5+, earns reputation
- ✅ Agent-to-agent transaction (Agent A's work triggers Agent B's work) succeeds
- ✅ User stores AWS credential, grants to Agent A → Agent A uses credential autonomously
- ✅ New App D joins ecosystem → discovers apps and agents automatically
- ✅ Cross-app agent work: Agent (Marketplace) completes task (Gig Board), reputation visible in both
- ✅ Audit trail tracks 100+ events, queryable by principal_id
- ✅ Registry survives failure; P2P continues (eventually re-syncs)
- ✅ Agent reputation correlates with work quality (high-rep agents win more bids)

---

## References & Related Documents

### RFCs & Specs
- **RFC-0001:** Core Vocabulary (Principal, Session, Capability, Evidence, VerificationResult, ReputationRecord)
- **RFC-0002:** A2A Extension Binding (transport layer)
- **RFC-0003 (new):** P2P Protocol (direct app-to-app communication)
- **RFC-0004 (new):** Federation Discovery (app registry and ecosystem discovery)

### Existing Code
- `registry/app.py` — Registry service (extend for U5, U6, U9)
- `registry/user_index.py` — User Principal index (mirror for agent index U5)
- `registry/index_store.py` — Capability search index
- `agents/provider/agent.py` — Example agent (reference for autonomous agents U10)
- `apps/marketplace/server/app.py` — Marketplace backend (extend for U8, U10)
- `apps/gig-board/server/app.py` — Gig Board backend (extend for U10)

### New Services
- `vault/app.py` (U7) — Credential Vault service
- `audit/app.py` (U12) — Audit logging service
- `marketplace/agent_marketplace.py` (U8) — Agent marketplace service (could be part of existing Marketplace app)

### Test Files
- `tests/registry/test_agent_registration.py` (U5)
- `tests/integration/test_p2p_communication.py` (U6)
- `tests/vault/test_credential_storage.py` (U7)
- `tests/marketplace/test_agent_discovery.py` (U8)
- `tests/integration/test_federation_discovery.py` (U9)
- `tests/integration/test_agent_work_coordination.py` (U10)
- `tests/integration/test_cross_app_agent_operations.py` (U11)
- `tests/audit/test_audit_logging.py` (U12)

### Configuration & Deployment
- `docker-compose.yml` (extend to include Vault, Audit service)
- Deployment docs: `registry/DEPLOYMENT.md`, `DEPLOYMENT.md` (update for new services)
- CI/CD: `.github/workflows/` (add tests for new services)

---

## Execution Notes

### Key Implementation Principles

1. **Minimal Code:** Use existing patterns from Phase A; extend, don't rebuild.
2. **Interfaces First:** Define all API contracts (RFCs) before coding.
3. **Integration Early:** Get services talking to each other in week 2-3; don't do silos.
4. **Test Continuously:** Write integration tests as each unit is built.
5. **Security Conscious:** Audit logs first, add them incrementally (not as afterthought).
6. **Decoupled Services:** Vault, Audit, and Marketplace can be developed in parallel.

### Critical Path

1. U5 first (unblocks everything)
2. U6 immediately after (enables P2P)
3. U7 and U9 can run in parallel (both needed for autonomy)
4. U10 brings it all together
5. U11 is validation

### Parallel Tracks (Recommended)

**Track A:** Registry & P2P (U5 → U6 → U9)
**Track B:** Vault & Marketplace (U7 → U8)
**Track C:** Coordination & Testing (U10 → U11)
**Track D:** Observability (U12, integrated throughout)

Each track can have a separate developer/pair. Sync points: end of U5, end of U8, start of U10.

---

## Appendix: Sample Data Flows

### Flow 1: User Hires Agent

```
1. User navigates to Console → Marketplace tab
2. User searches "aws.deploy" agents
3. Registry returns: [Agent A ⭐⭐⭐⭐, Agent B ⭐⭐⭐]
4. User clicks Agent A "Hire"
5. Console creates hiring grant:
   {agent_principal: A, scopes: [access.aws], expiry: 2026-08-19}
6. Grant sent to Vault, stored in credential_grants table
7. Console notifies Agent A: "You've been hired by User X"
8. Agent A can now request access to User X's AWS credential

Audit trail:
- {timestamp, user-x, agent.hire, agent-a, granted}
- Agent A's reputation increases (hiring count metric)
```

### Flow 2: Agent Performs Autonomous Work

```
1. Agent A queries Marketplace: GET /p2p/work-opportunities?capability=aws.deploy
2. Marketplace returns: [Task 1: Deploy app, pay 1000 rep; Task 2: ...]
3. Agent A selects Task 1, submits bid:
   POST /p2p/work-requests
   {agent_principal: A, work_id: 1, proposed_terms: 800 rep, session: ...}
4. Marketplace app stores bid, notifies User (Task author)
5. User reviews Agent A's reputation (⭐⭐⭐⭐), clicks "Accept"
6. Marketplace app sends work contract to Agent A
7. Agent A requests AWS credential from Vault:
   POST /credentials/aws-cred-id/access {agent_principal: A, session}
8. Vault checks: Agent A has "access.aws" scope from User X → granted
9. Vault logs: {timestamp, agent-a, credential.access, aws-cred-id, granted}
10. Vault returns encrypted credential (only Agent A's session can decrypt)
11. Agent A decrypts credential, uses it to deploy app to AWS
12. Agent A collects evidence (CloudFormation logs, etc.)
13. Agent A submits work completion:
    POST /p2p/task-complete
    {agent_principal: A, task_id: 1, evidence, session}
14. Marketplace sends evidence to Verification Service
15. Verification Service validates → work accepted
16. Verification Service updates reputation: Agent A +800 rep
17. Registry notifies all apps: Agent A's reputation updated
18. Marketplace shows Task 1 complete, Agent A credited
19. Gig Board queries Registry: Agent A's reputation → includes this task

Audit trail:
- {timestamp, agent-a, work.submit, task-1, accepted}
- {timestamp, agent-a, credential.access, aws-cred-id, granted}
- {timestamp, agent-a, work.complete, task-1, verified}
- {timestamp, agent-a, reputation.update, task-1, +800}
```

### Flow 3: New App Joins Ecosystem

```
1. Developer deploys App D with configuration: REGISTRY_URL=https://registry.example.com
2. App D startup:
   GET /registry/apps → returns [Console, Marketplace, Gig Board]
3. App D registers itself:
   POST /registry/apps/register
   {app_id: app-d, app_endpoint: https://app-d.example.com, p2p_endpoint: https://app-d.example.com/p2p, capabilities: [service.execute]}
4. Registry adds App D to app directory
5. App D queries: GET /registry/services?type=credential_vault → Vault URL
6. App D queries: GET /registry/services?type=agent_marketplace → Marketplace URL
7. App D now can:
   - P2P connect to other apps
   - Use Vault for credential management
   - Integrate Agent Marketplace for discovering agents
8. Other apps query Registry: GET /registry/apps → they see App D
9. Agents from Marketplace can now bid on work in App D
10. Users can see agents in App D marketplace (if queried)

Audit trail:
- {timestamp, app-d, app.register, app-d, granted}
```

---

## Conclusion

Phase B transforms AgentTrust from a user-federation protocol into a full autonomous-agent platform with P2P coordination and encrypted credential management. The architecture maintains backward compatibility with Phase A (apps still work, users still sign in) while adding autonomous economic actors (agents) and decentralized communication (P2P).

The implementation is phased to enable parallel work and early validation. By the end of Phase B, the ecosystem should support:
- Users owning agents that work autonomously
- Agents discovering and negotiating work independently
- Cross-app agent operations with transparent reputation
- Encrypted credentials managed by users, accessed by agents
- New apps joining the ecosystem with zero manual configuration
- Complete audit trails for compliance and debugging

This foundation enables Phase C (governance, scale, sustainability) and positions AgentTrust as a genuine open ecosystem for autonomous agents.

---

## Next Steps (Phase C Conceptual)

1. **Governance:** Establish RFC process, steering committee, protocol versioning
2. **Scale:** Add caching, sharding, multi-region registries
3. **Privacy:** Implement privacy-preserving reputation (zero-knowledge proofs)
4. **Sustainability:** Define revenue models for registries and services
5. **Standards:** Publish open-source SDKs for third-party integrations
6. **Community:** Invite external developers to build apps and agents
