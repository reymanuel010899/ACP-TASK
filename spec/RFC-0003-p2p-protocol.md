# RFC-0003: AgentTrust P2P Communication Protocol

- **Status:** Draft
- **Date:** 2026-07-19
- **Depends on:** RFC-0001 (core vocabulary), RFC-0002 (A2A extension binding)
- **Implements:** Phase B unit U6 (Registry app registration + direct app-to-app requests)

> The project name **AgentTrust** is a provisional placeholder, as is the
> `agenttrust.example` domain. Both will be replaced before any non-draft
> release; the *structure* of this protocol is what is specified.

The key words MUST, MUST NOT, REQUIRED, SHOULD, SHOULD NOT, and MAY are to be
interpreted as described in RFC 2119.

## 1. Motivation and topology

Apps and agents in the ecosystem need to talk to each other directly —
without routing every payload through a central service. Per the Phase B
plan (Decisions 1 and 4), the network is a **star topology for signaling
only**: the Registry is the hub where apps publish their endpoints and where
permission verdicts are issued, but **P2P traffic itself flows directly
between requester and target app**. The Registry never proxies, stores, or
inspects P2P request payloads.

The flow has three legs:

1. **Registration** — an app publishes its endpoints and capabilities to
   the Registry (`POST /apps/register`), typically at startup.
2. **Discovery** — a requester resolves the target app's `p2p_endpoint`
   through the Registry (`GET /apps/{app_id}`).
3. **Direct request** — the requester POSTs to
   `{p2p_endpoint}/p2p/request` on the target app; the target app checks
   permission with the Registry (`POST /p2p/permissions/check`) before
   processing.

## 2. App registration (Registry)

### `POST /apps/register`

```json
{
  "app_id": "marketplace",
  "app_endpoint": "http://apps.example:8001",
  "p2p_endpoint": "http://apps.example:8001",
  "capabilities": ["marketplace.tasks", "p2p.ping"]
}
```

- All four fields are REQUIRED; `capabilities` MUST be a list of non-empty
  strings. Missing/invalid fields → **422**.
- Response: **200** `{"app": {app_id, app_endpoint, p2p_endpoint,
  capabilities, registered_at, updated_at}}`.
- **Re-registration is not an error.** Apps restart often; registering an
  existing `app_id` updates the endpoints and capabilities in place,
  preserves `registered_at`, and bumps `updated_at`.
- `p2p_endpoint` is the base URL at which the app accepts
  `POST {p2p_endpoint}/p2p/request`. It MAY equal `app_endpoint`.

## 3. Endpoint discovery (Registry)

- `GET /apps` → **200** `{"apps": [...]}` — all registered apps.
- `GET /apps/{app_id}` → **200** `{"app": {...}}`, or **404** if the
  app_id is unknown.

Requesters MUST resolve the target's `p2p_endpoint` via discovery and then
communicate with the app directly; they MUST NOT expect the Registry to
forward requests (the Registry has no `/p2p/request` route).

*Scope note:* U9 (federation discovery) will extend this surface with
service-type discovery and capability manifests; this RFC only specifies
the minimal register/lookup surface P2P needs.

## 4. Permission check (Registry)

### `POST /p2p/permissions/check`

```json
{
  "requester_principal_id": "user:alice",
  "target_app_id": "marketplace",
  "capability_id": "p2p.ping"
}
```

Response is always **200** with a verdict (422 only for malformed input):

```json
{"allowed": true, "reason": "..."}
```

MVP permission model — `allowed` is `true` iff ALL of:

1. the requester principal exists in the Registry (as a **user or agent**
   Principal);
2. the target app is registered;
3. `capability_id` is among the target app's declared `capabilities`.

Any failing condition yields `{"allowed": false, "reason": "..."}` with a
human-readable reason (unknown principal, unregistered app, or unsupported
capability). Later phases MAY tighten this model (reputation thresholds,
per-principal grants) without changing the wire shape.

## 5. Direct P2P request (target app)

### `POST {p2p_endpoint}/p2p/request`

```json
{
  "requester_principal_id": "user:alice",
  "session_id": "sess-123",
  "request_type": "ping",
  "capability_id": "p2p.ping",
  "input": {}
}
```

- `requester_principal_id`, `request_type`, and `capability_id` are
  REQUIRED non-empty strings; `session_id` and `input` are OPTIONAL.
- Processing flow on the target app:
  1. Validate required fields → **422** on failure.
  2. If the app is configured with a Registry URL, call
     `POST {registry}/p2p/permissions/check`. Denied → **403**
     `{"error": "permission denied", "reason": "..."}`. The app fails
     **closed**: an unreachable Registry → **502**. An app with NO
     Registry configured (standalone mode) skips the check and processes
     the request.
  3. Dispatch on `request_type`. Unknown type → **400**.
- Success response: **200**

```json
{
  "result": {"pong": true, "app_id": "marketplace"},
  "evidence_id": "0d9c2f2a-..."
}
```

`evidence_id` is a UUID identifying this exchange for the evidence/
verification layer (RFC-0001). The only request type in this RFC is
`"ping"` (liveness/handshake); U10 adds real work request types, which
plug into the same dispatch without changing this envelope.

## 6. Error codes (summary)

| Code | Where | Meaning |
| ---- | ----- | ------- |
| 403  | target app | Permission denied by Registry verdict (body carries `error` + `reason`) |
| 422  | Registry & app | Missing or invalid required fields |
| 400  | target app | Unknown `request_type` |
| 404  | Registry | Unknown `app_id` on discovery |
| 502  | target app | Registry configured but unreachable for the permission check (fail closed) |

## 7. Reference implementation

- Registry: `registry/app_registry.py` (`AppRegistry`), routes in
  `registry/app.py`.
- Apps: `handle_p2p_request` / `register_with_registry` in
  `apps/marketplace/server/app.py` and `apps/gig-board/server/app.py`.
- Client: `libs/p2p_client.py` (`P2PClient.discover_app`,
  `P2PClient.check_permission`, `P2PClient.p2p_request`).
- Tests: `tests/integration/test_p2p_communication.py`.
