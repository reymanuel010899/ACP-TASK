# RFC-0004: AgentTrust Federation Discovery

- **Status:** Draft
- **Date:** 2026-07-19
- **Depends on:** RFC-0001 (core vocabulary), RFC-0003 (P2P communication protocol)
- **Implements:** Phase B unit U9 (ecosystem discovery + shared-service lookup)

> The project name **AgentTrust** is a provisional placeholder, as is the
> `treessera.com` domain. Both will be replaced before any non-draft
> release; the *structure* of this protocol is what is specified.

The key words MUST, MUST NOT, REQUIRED, SHOULD, SHOULD NOT, and MAY are to be
interpreted as described in RFC 2119.

## 1. Motivation

RFC-0003 lets a requester reach an app it already knows by `app_id`. It does
not answer the bootstrap question: **how does a new app learn who else
exists?** Federation discovery closes that gap with a **pull-based** model:
the Registry is a *directory*, never a broadcaster. Nothing is pushed to
members when the ecosystem changes; each participant pulls what it needs,
when it needs it. A new app therefore joins the ecosystem knowing exactly
one thing — the Registry URL — and from that single fact it:

1. **registers** itself (RFC-0003 registration, extended below);
2. **discovers** every other registered app *in the registration response
   itself* (one round-trip, no second call);
3. **locates shared services** — the credential vault, the agent
   marketplace, the verification service — by *type* rather than by
   well-known `app_id` or hardcoded URL.

The Registry remains a signaling hub (RFC-0003 §1): it answers "who exists
and where", and all subsequent traffic flows directly between participants.

## 2. Registration with service flags (Registry)

### `POST /apps/register` (extends RFC-0003 §2)

```json
{
  "app_id": "vault",
  "app_endpoint": "http://vault.example:8003",
  "p2p_endpoint": "http://vault.example:8003",
  "capabilities": [],
  "credential_vault": true
}
```

- The RFC-0003 fields and semantics are unchanged: `app_id`,
  `app_endpoint`, and `p2p_endpoint` are REQUIRED non-empty strings;
  re-registration updates in place, preserving `registered_at`.
- Three OPTIONAL boolean **service flags**, each defaulting to `false`,
  mark the registrant as a provider of a shared service:
  `agent_marketplace`, `credential_vault`, `verification_service`.
  A non-boolean flag → **422**.
- `capabilities` MUST still be a list of strings, but MAY now be **empty**:
  a standalone service (a vault is not an "app" offering P2P capabilities)
  registers as a directory entry with `capabilities: []` and the relevant
  flag set.
- The stored record gains a `services` object mapping each service type to
  its boolean; re-registration replaces the flags along with the endpoints.

### Response: the ecosystem in one round-trip

```json
{
  "app": {"app_id": "vault", "...": "..."},
  "ecosystem_apps": [
    {"app_id": "marketplace", "app_endpoint": "...", "p2p_endpoint": "...",
     "capabilities": ["marketplace.tasks", "p2p.ping"], "services": {"...": false},
     "registered_at": "...", "updated_at": "..."}
  ]
}
```

`ecosystem_apps` lists every OTHER registered record (the registrant is
excluded), so a joining app discovers the whole ecosystem without a second
request. The very first app in an empty ecosystem receives
`"ecosystem_apps": []`.

## 3. Capability filtering (Registry)

### `GET /apps?capability=<id>`

Without the parameter, behavior is exactly RFC-0003 §3 (all registered
apps). With it, only apps whose `capabilities` include the given id are
returned; an unknown capability yields **200** `{"apps": []}` — filtering
is a query, not an existence assertion, so it MUST NOT 404.

## 4. Service lookup (Registry)

### `GET /services?type=<service_type>`

`service_type` MUST be one of `agent_marketplace`, `credential_vault`,
`verification_service`. Response:

```json
{
  "service_type": "credential_vault",
  "services": [
    {"app_id": "vault",
     "endpoint": "http://vault.example:8003",
     "p2p_endpoint": "http://vault.example:8003"}
  ]
}
```

- **200** with `"services": []` when nobody provides the type (again: a
  query, not an assertion).
- **400** when `type` is missing or not one of the three known values —
  an unknown *service type* is a caller error, unlike an unknown
  capability, because the type vocabulary is fixed by this RFC.
- Multiple providers MAY be returned (ordered by `app_id`); clients that
  need exactly one SHOULD take the first.

## 5. Federation client (join flow)

The reference client (`libs/federation_client.py`, `FederationClient`)
wraps the surface above:

- `register_app(app_id, app_endpoint, p2p_endpoint, capabilities,
  **service_flags)` → the registration body, including `ecosystem_apps`.
- `discover_apps(capability=None)` → registered apps, optionally filtered.
- `find_service(service_type)` → the first provider
  (`{app_id, endpoint, p2p_endpoint}`) or `None`.
- `join_ecosystem(app_id, ...)` → register + locate the shared services in
  one call: `{"ecosystem_apps": [...], "vault": ... | None,
  "agent_marketplace": ... | None}`.

Every failure mode — registry unreachable, non-200 answer, malformed body —
raises a single clean `FederationError`. **Startup registration MUST be
non-fatal**: an app started while the Registry is down MUST still boot and
serve its own API (it simply stays undiscoverable until it re-registers,
typically on next restart). The reference apps
(`apps/marketplace/server/app.py`, `apps/gig-board/server/app.py`) register
through the federation client at startup and log
`Discovered ecosystem: [...]`; the vault registers itself as a
`credential_vault` service (with `capabilities: []`) when started with
`--registry-url`.

## 6. Error codes (summary)

| Code | Where | Meaning |
| ---- | ----- | ------- |
| 422  | Registry | Missing/invalid registration fields, or a non-boolean service flag |
| 400  | Registry | Missing or unknown `type` on `GET /services` |
| 200 + `[]` | Registry | Unknown capability filter, or no provider of a valid service type |
| —    | client | Any transport/HTTP failure surfaces as `FederationError`; startup callers treat it as non-fatal |

## 7. Reference implementation

- Registry: `registry/app_registry.py` (`SERVICE_TYPES`, `services` flags,
  `list_apps(capability)`, `find_services`), routes in `registry/app.py`
  (`register_app` with `ecosystem_apps`, `GET /apps?capability=`,
  `GET /services`).
- Client: `libs/federation_client.py` (`FederationClient`,
  `FederationError`).
- Apps: `register_with_registry` in `apps/marketplace/server/app.py` and
  `apps/gig-board/server/app.py`; vault service registration in
  `vault/app.py` (`--registry-url`).
- Tests: `tests/integration/test_federation_discovery.py`.
