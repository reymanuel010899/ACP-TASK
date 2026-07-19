---
title: "Phase A: Federated Multi-App Validation (3 Web Apps)"
type: feat
created: 2026-07-18
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
execution: code
product_contract_source: ce-plan-bootstrap
origin: docs/plans/2026-07-18-001-vision-agenttrust-federated-ecosystem.md
---

# Phase A: Federated Multi-App Validation

## Goal Capsule

Enable three independent web applications (Web Console + App B + App C) to coexist on the AgentTrust federation protocol, proving that users can:
1. Create an identity once (Principal ed25519)
2. Join any of the 3 apps with that same identity
3. See their reputation flow correctly between apps
4. Communicate (users in App B can request work from users in App C)

**Outcome:** A working, deployable proof-of-concept that demonstrates the federated ecosystem vision is technically sound and user-viable.

---

## Problem Frame

**Current State:**
- Web console works standalone
- Agent coordination works (provider ↔ requester)
- User/reputation layer exists only locally per app

**Gap:**
- No proof that multiple apps can coexist on the same protocol
- No validation that reputation flows between apps
- No evidence users can maintain portable identity

**Risk of Not Doing This:**
- Vision remains theoretical
- Unknown unknowns about federation complexity
- First third-party app builder will hit undiscovered walls

---

## Success Criteria

### Must-Haves ✅
- [ ] User A creates account in Web Console with Principal ed25519_xyz
- [ ] User A logs into App B using the same Principal → sees their reputation from Console
- [ ] User A logs into App C using the same Principal → sees combined reputation from Console + B
- [ ] User B (in App B) discovers User C (in App C) and requests work
- [ ] Verification service validates the work
- [ ] Both User B and User C see reputation update in their respective apps
- [ ] At least one independent registry instance exists (not owned by any one app)

### Nice-to-Haves 📈
- [ ] Apps have basic UI differentiation (so it's obvious they're different)
- [ ] Reputation display shows breakdown (which app contributed)
- [ ] Basic user search across apps
- [ ] Error recovery flows (lost key scenario)

### Out of Scope ❌
- [ ] Production security hardening
- [ ] Sophisticated UX/design
- [ ] Scalability to 1000s of users
- [ ] Advanced moderation/safety features
- [ ] Performance optimization

---

## Architecture Overview

### Three Apps

```
┌──────────────────────────────────────────────────────────┐
│                   Shared Registry (Federated)             │
│  ├─ Principal Directory (ed25519 mappings)              │
│  ├─ Reputation Records (verified work outcomes)         │
│  └─ User Metadata (created at, last active, etc)        │
└──────────────────────────────────────────────────────────┘
         ↑                    ↑                    ↑
         │                    │                    │
    ┌────────┐          ┌────────┐          ┌────────┐
    │ App 1  │          │ App 2  │          │ App 3  │
    │ Console│          │App "B" │          │App "C" │
    │ (React)│          │(React) │          │(React) │
    │        │          │        │          │        │
    │Users:  │          │Users:  │          │Users:  │
    │- juan  │          │- maria │          │- pedro │
    │- maria │          │- pedro │          │- juan  │
    └────────┘          └────────┘          └────────┘
```

### API Contract Between Apps

Each app implements:
1. **User session endpoint** — POST `/auth/register` or `/auth/login` with Principal
2. **Registry query** — GET `/registry/user/{principal_id}` to fetch reputation
3. **Reputation update hook** — POST `/registry/user/{principal_id}/update` to report new reputation
4. **User discovery** — GET `/users/search?q=...` (optional, for finding users in other apps)

Registry is a **shared service** that all 3 apps query:
- Stores Principals and reputation records
- Independent verification service validates reputation claims
- Each app trusts the registry; registry trusts verification service

---

## Implementation Units

### U1. Registry Extension for User-Level Reputation

**Goal:** Extend the existing registry (`registry/app.py`) to support user Principals in addition to agent Principals.

**Requirements:**
- Registry stores user Principals (ed25519 keys) mapped to user metadata
- Registry tracks reputation records keyed by Principal (not app)
- Registry provides endpoints for:
  - User registration (add new Principal)
  - User lookup (get reputation by Principal)
  - Reputation update (record verified work)

**Dependencies:** None (can be done first)

**Files:**
- Modify: `registry/app.py` (extend schema, add user endpoints)
- Create: `registry/schemas/user-principal.json` (new schema)
- Create: `registry/schemas/user-reputation-record.json`
- Create: `tests/registry/test_user_endpoints.py`

**Approach:**
- Add new database tables/models for `user_principals` and `user_reputation_records`
- Reuse existing verification-record structure; extend it with user Principal field
- Ensure backward compatibility with agent-level Principals

**Patterns to follow:**
- Mirror existing agent registry patterns (`registry/app.py` line structure)
- Use same JSON schema validation as agent layer
- Same REST endpoint style as existing registry

**Test scenarios:**
1. Register a new user Principal → returns Principal ID
2. Query non-existent Principal → returns 404
3. Query existing Principal → returns reputation records
4. Add reputation record for Principal → stored correctly
5. Multiple records for same Principal → aggregated correctly

**Verification:**
- All test scenarios pass
- Registry startup includes user schema migrations
- Existing agent endpoints still work (no regression)

---

### U2. App 1 (Web Console) — User Session Layer

**Goal:** Extend existing web console to let users log in with Principal instead of username/password.

**Requirements:**
- User can register with a generated or imported Principal (ed25519 key)
- User can log in with their Principal
- Session is tied to Principal, survives app restarts
- User sees their reputation on dashboard

**Dependencies:** U1 (registry user endpoints must exist)

**Files:**
- Modify: `web/app.py` (add user session routes)
- Modify: `mobile/lib/features/profile/screens/profile_screen.dart` → no, wait, this is web console React
- Create: `web/src/pages/Auth/RegisterPrincipal.jsx` (register with key)
- Create: `web/src/pages/Auth/LoginPrincipal.jsx` (log in with key)
- Create: `web/src/hooks/useUserSession.ts` (session management)
- Create: `web/src/components/ReputationDisplay.jsx` (show reputation)
- Create: `tests/web/test_user_auth.py`

**Approach:**
- User registration: generate or paste ed25519 key → POST `/auth/register` to registry
- User login: paste ed25519 key → POST `/auth/login` → validate with registry
- Store session in localStorage (Principal ID + session token)
- Fetch reputation from registry on app load

**Patterns to follow:**
- Existing web console auth patterns (if any)
- React hooks for state (useUserSession, useReputation)
- Same HTTP client as existing console code

**Test scenarios:**
1. User registers with new Principal → account created in registry
2. User logs in with valid Principal → session created
3. User logs in with invalid Principal → auth fails
4. User sees reputation on dashboard after login
5. User closes and reopens app → session persists
6. User logs out → session cleared

**Verification:**
- User can complete register → login → view dashboard flow
- Session persists across page reloads
- Reputation display matches registry records

---

### U3. App 2 (Task Marketplace) — New React App

**Goal:** Build a minimal task marketplace app where users can post and accept tasks. Proves federation by letting users from Console connect with App B users.

**Requirements:**
- Users log in with Principal (reuse U2 pattern)
- User can post a task (text description + payment)
- User can see tasks posted by other users
- User can accept a task → creates a negotiation with task author
- Negotiation outcome gets reported to registry as reputation

**Dependencies:** U1, U2 (use Console's auth pattern)

**Files:**
- Create: `apps/marketplace/` (new React app)
- Create: `apps/marketplace/src/pages/Auth/` (copy from Console)
- Create: `apps/marketplace/src/pages/Tasks/PostTask.jsx`
- Create: `apps/marketplace/src/pages/Tasks/TaskList.jsx`
- Create: `apps/marketplace/src/pages/Tasks/TaskDetail.jsx`
- Create: `apps/marketplace/src/pages/Chat/NegotiationThread.jsx`
- Create: `apps/marketplace/src/hooks/useTasks.ts`
- Create: `apps/marketplace/src/hooks/useNegotiation.ts`
- Create: `tests/marketplace/test_task_flow.py`

**Approach:**
- Tasks stored in App B's own database (not shared registry)
- User discovery via registry (find users by Principal)
- Negotiation: task author ↔ worker, outcome verified, reputation reported to registry
- Minimal UI: plain React forms, no design system

**Patterns to follow:**
- Mirror Console's useUserSession hook
- Same HTTP client
- Same registry interaction pattern

**Test scenarios:**
1. User (from Console) logs into Marketplace using Principal → their reputation visible
2. User posts a task
3. Different user (from Console or Marketplace) discovers task and accepts
4. Task is completed; outcome reported to registry
5. Both users' reputation updated in registry
6. User logs back into Console → sees reputation increase from Marketplace work

**Verification:**
- Can complete task lifecycle (post → accept → complete → reputation update)
- Reputation flows from Marketplace to registry
- Users can discover each other across apps

---

### U4. App 3 (Gig Board) — Different Domain to Prove Ecosystem

**Goal:** Build a second non-marketplace app (e.g., project collaboration board, service directory, or skill marketplace) to prove federation works across different domains.

**Requirements:**
- Same Principal-based auth as Apps 1-2
- Different feature set (not another marketplace)
- Users from other apps can interact
- Reputation accrues and is visible in all apps

**Dependencies:** U1, U2, U3 (follow the same patterns)

**Files:**
- Create: `apps/gig-board/` (new React app, similar structure to Marketplace)
- Create: `apps/gig-board/src/pages/...` (minimal feature set for domain)
- Create: `tests/gig-board/test_gig_flow.py`

**Approach:**
- Choose a different feature domain (e.g., service providers offering skills, or projects seeking collaborators)
- Same auth/session/reputation patterns as Apps 1-2
- Minimal implementation: enough to show interaction with other apps

**Patterns to follow:**
- Identical to U3 (reuse App B structure)

**Test scenarios:**
1. Cross-app interaction (user from Console collaborates with user from Marketplace, visible in Gig Board)
2. Reputation flows to all apps
3. User can log into any app and see complete reputation history

**Verification:**
- Can complete task flow
- Reputation visible in all 3 apps
- Cross-app user interaction works

---

### U5. Independent Registry Instance

**Goal:** Deploy at least one registry instance that is NOT owned/controlled by any app. Proves registry can exist independently.

**Requirements:**
- Registry runs on separate host/process from all 3 apps
- All 3 apps connect to it
- Registry has its own database
- Registry enforces schema validation
- Reputation records survive app crashes

**Dependencies:** U1 (registry extension must be done)

**Files:**
- Deploy existing `registry/app.py` to independent host
- Create: `registry/docker-compose.yml` (for easy deployment)
- Create: `registry/README.md` (deployment instructions)
- Create: `tests/integration/test_all_3_apps_with_independent_registry.py`

**Approach:**
- Use Docker or similar to run registry in isolated environment
- Configure all 3 apps to point to same registry instance
- Database is the single source of truth for reputation

**Patterns to follow:**
- Existing deployment patterns (if any)

**Test scenarios:**
1. Registry starts correctly with empty database
2. App 1 registers user, App 2 can query it
3. Registry survives App 1 restart
4. Reputation records persist across app restarts
5. Multiple apps write reputation simultaneously without conflict

**Verification:**
- Registry is running on independent host
- All 3 apps successfully query it
- Reputation persists
- No app can corrupt registry

---

### U6. End-to-End Federation Test Suite

**Goal:** Write comprehensive tests that prove federation works across all 3 apps.

**Requirements:**
- Test user flow: register in Console → log into Marketplace → see reputation → complete task → log into Gig Board → see updated reputation
- Test cross-app discovery: user in App B discovers user in App C
- Test reputation aggregation: work in App B affects reputation visible in Apps 1 and 3
- Test failure recovery: app crash doesn't lose reputation or user state

**Dependencies:** U1–U5 (all apps built and deployed)

**Files:**
- Create: `tests/integration/test_federation_end_to_end.py` (comprehensive flows)
- Create: `tests/integration/conftest.py` (shared fixtures)

**Approach:**
- Use integration test framework (pytest + requests)
- Simulate user journeys across apps
- Verify registry state at each step

**Test scenarios:**
1. **User Portability:** Register in Console → login in Marketplace → login in Gig Board with same Principal → success
2. **Reputation Flow:** Complete task in Marketplace → reputation updates in registry → visible in Console and Gig Board
3. **Cross-App Discovery:** User A in Console searches for User B → finds User B from Marketplace
4. **Simultaneous Users:** Multiple users in different apps → all reputation recorded correctly
5. **App Failure Recovery:** Kill App B → restart → reputation intact, users can still log in

**Verification:**
- All test scenarios pass
- No race conditions with concurrent operations
- Reputation accuracy maintained

---

## System-Wide Impact

### Data Storage
- Registry gains user Principal table and reputation records table
- Each app has local task/negotiation storage (not shared)
- All reputation is canonical in registry

### API Contract Changes
- New registry endpoints: `/auth/register`, `/auth/login`, `/user/{principal}/reputation`
- Apps communicate via standard HTTP REST
- No changes to agent-level APIs (backward compatible)

### Deployment Topology
- Registry: independent service (Docker, or local process)
- App 1 (Console): connect to registry at startup
- App 2 (Marketplace): connect to registry at startup
- App 3 (Gig Board): connect to registry at startup
- Verification service: existing (no changes)

### User Experience
- First time: "Create account" → generates/pastes ed25519 key
- Subsequent logins: "Log in" → paste key → instant access to all reputation
- No username/password; identity is the key

---

## Technical Decisions

### Decision 1: Shared Registry vs Embedded Registries
**Choice:** Shared, independent registry instance
**Rationale:** Proves federation works; registry is neutral third party
**Alternative:** Each app embeds registry → easier to build, but doesn't prove federation

### Decision 2: Principal Format
**Choice:** ed25519 (existing AgentTrust standard)
**Rationale:** Already defined, cryptographically sound, agents use it
**Alternative:** UUID or username → weaker identity semantics

### Decision 3: React Stack for All Apps
**Choice:** React for Apps 2-3 (matching Console)
**Rationale:** Faster to build, reuse patterns, no framework switching friction
**Alternative:** Different frameworks → more realistic but slower to execute

### Decision 4: Local Task Storage
**Choice:** Each app stores its own tasks (not shared registry)
**Rationale:** Apps own their data; registry is only reputation keeper
**Alternative:** Shared task registry → more complex, not necessary for Phase A

---

## Known Unknowns (Deferred to Implementation)

1. **User Recovery:** If user loses their ed25519 key, can they recover the account? Scope: out of Phase A, plan for Phase B
2. **Privacy Boundaries:** Should App 1 know what App 2 users are doing? Currently full transparency; may need per-app privacy scopes in Phase B
3. **Conflict Resolution:** If App B and App C disagree on reputation for same user, how is it resolved? Scope: out of Phase A
4. **Search/Discovery UX:** How should users find each other across apps? Current plan: simple search; Phase B can improve

---

## Risks & Mitigations

### Risk 1: Registry Becomes Bottleneck
**Problem:** All 3 apps query registry constantly; single point of failure
**Mitigation:** Phase A uses basic REST API; Phase B can add caching, eventually sharding

### Risk 2: Data Consistency Issues
**Problem:** Multiple apps write reputation simultaneously → race conditions
**Mitigation:** Registry uses database transactions; each write is atomic

### Risk 3: User Confusion (Key Management)
**Problem:** Users lose their ed25519 keys or paste wrong key
**Mitigation:** Phase A: minimal UX, clear warning; Phase B: key recovery, backup mechanisms

### Risk 4: First Third-Party App Builder Hits Walls
**Problem:** Apps 2-3 built by same team; real third-party app may expose undiscovered gaps
**Mitigation:** Comprehensive documentation; clear API contract; prepare for Phase B fixes based on feedback

---

## Success Metrics (Proof-of-Concept)

- ✅ User can log into 3 different apps with same Principal
- ✅ Reputation correctly aggregates across all 3 apps
- ✅ Users can interact across app boundaries (task posted in App B completed by user in App C)
- ✅ Registry survives app crashes; reputation is durable
- ✅ All integration tests pass
- ✅ Independent registry instance runs without app interference

---

## Scope Boundaries

### Explicitly Deferred to Phase B (Later)
- User key recovery flows
- Advanced privacy boundaries (per-app reputation filtering)
- Performance optimization (caching, CDN, load balancing)
- Advanced search and recommendation
- Sophisticated moderation/safety
- Third-party SDK/library
- Formal governance model

### Explicitly Out of Scope
- Mobile app updates (Phase A is web-only for speed)
- Blockchain or distributed ledger (centralized registry sufficient)
- Advanced cryptography beyond ed25519
- Multi-signature or threshold schemes
- Formal security audit

---

## Execution Approach

**Phase A is a **proof sprint**, not a product.**

- Build fast, validate the architecture
- MVP UI acceptable
- Focus on federation logic, not polish
- Iterate based on what fails
- Document discoveries for Phase B

**Timeline Estimate:** 4-6 weeks for MVP from start to "all tests passing"

**Sequencing:**
1. U1 (Registry) — 1 week — unblocks everything
2. U2 (Console auth) — 1 week — reuses existing code
3. U3 (Marketplace) — 2 weeks — new app, same patterns
4. U4 (Gig Board) — 1 week — copy Marketplace, different features
5. U5 (Independent registry) — 1 week — deployment, Docker
6. U6 (End-to-end tests) — 1 week — validate everything together

---

## Definition of Done

Phase A is complete when:

- [ ] User can register in Console with Principal
- [ ] User can log into Marketplace with same Principal and see their reputation
- [ ] User can log into Gig Board and see combined reputation
- [ ] User A (Marketplace) and User B (Gig Board) can interact; reputation updates
- [ ] All reputation changes are visible in Console, Marketplace, and Gig Board
- [ ] Independent registry instance exists and all 3 apps successfully connect to it
- [ ] End-to-end integration tests all pass
- [ ] No single app can corrupt or fake reputation
- [ ] Federation works; proof-of-concept is validated

---

## Next Steps After Phase A

- Gather learnings from Phase A
- Document what broke, what surprised you
- Plan Phase B: stabilization, documentation, prepare for external builders
- Invite first external developer to build App 4 on the protocol

---

## References

- **Vision Document:** `docs/plans/2026-07-18-001-vision-agenttrust-federated-ecosystem.md`
- **Existing Registry:** `registry/app.py`
- **Existing Web Console:** `web/app.py`
- **Agent Coordination (Baseline):** `agents/provider/agent.py`, `agents/requester/agent.py`
- **RFC-0001 Core Vocabulary** — Principal, Session, Capability, Evidence, VerificationResult, ReputationRecord
- **RFC-0002 A2A Extension Binding** — Transport layer (unchanged for Phase A)
