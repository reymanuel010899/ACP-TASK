# Slack integration operations

## Required configuration

- `SLACK_CLIENT_ID`, `SLACK_CLIENT_SECRET`, and an HTTPS callback registered in the Slack app.
- KMS-backed vault keyring and a shared `SESSION_DATABASE` for the session, OAuth, broker, and concierge services.
- Enable independently: `TESSERA_SLACK_CONNECT_ENABLED`, `TESSERA_SLACK_EXECUTION_ENABLED`; both default off in production.
- Request only the scopes selected by the user. Scope upgrades start a new OAuth transaction; disconnect tombstones the connection and purges its ciphertext.

## Release gate

Use a dedicated Slack sandbox. Connect two workspaces, read one channel, approve one message, rotate the credential document, disconnect one workspace, and verify the other still works. Do not enable writes until receipts and verification are visible.

## Monitoring and rollback

Watch `slack_oauth_failure`, `slack_refresh_failure`, `broker_tenant_binding_violation`, `slack_rate_limited`, `execution_unknown`, and verification backlog. Healthy means no cross-tenant rejection, stable refresh success, bounded 429 retries, and no duplicate idempotency keys. On a spike, set `TESSERA_SLACK_EXECUTION_ENABLED=false`; queued work becomes `paused_by_policy` and unused leases are not dispatchable.

Never log authorization codes, token documents, upload URLs, message bodies, or raw Slack file content. Preserve only minimized provider identifiers, hashes, timestamps, and signed attestations.
