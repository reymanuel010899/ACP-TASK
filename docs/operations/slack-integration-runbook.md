# Slack integration operations

## Required configuration

- `SLACK_CLIENT_ID`, `SLACK_CLIENT_SECRET`, and an HTTPS callback registered in the Slack app.
- KMS-backed vault keyring and a shared `SESSION_DATABASE` for the session, OAuth, broker, and concierge services.
- Capability families are per-tenant control-plane state, not configuration. Every family lands disabled; an administrator enables each one from Integrations (`POST /oauth/control-plane`), and the change takes effect on the next dispatch with no restart.
- Request only the scopes selected by the user. Scope upgrades start a new OAuth transaction; disconnect tombstones the connection and purges its ciphertext.

## Release gate

Use a dedicated Slack sandbox. Connect two workspaces, read one channel, approve one message, rotate the credential document, disconnect one workspace, and verify the other still works. Do not enable writes until receipts and verification are visible.

## Monitoring and rollback

Watch `slack_oauth_failure`, `slack_refresh_failure`, `broker_tenant_binding_violation`, `slack_rate_limited`, `execution_unknown`, and verification backlog. Healthy means no cross-tenant rejection, stable refresh success, bounded 429 retries, and no duplicate idempotency keys. On a spike affecting one family, disable that family for the affected account; on a spike affecting the whole account, use the emergency stop. Either way queued work becomes `paused_by_policy` rather than failing, unused leases are not dispatchable, and the same refusal is enforced at the broker, so no other caller can route around it. Both switches gate writes only: reconciliation still runs, so effects already in flight reach a verdict and the dispatched-versus-prevented counts stay truthful. Re-enabling releases the parked work on the next worker tick.

Never log authorization codes, token documents, upload URLs, message bodies, or raw Slack file content. Preserve only minimized provider identifiers, hashes, timestamps, and signed attestations.
