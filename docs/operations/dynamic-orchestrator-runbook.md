# Dynamic orchestrator operations

## Rollout order

1. Set `APP_ENV=production`, `TESSERA_WORKFLOW_KMS_KEY_ID`, and grant the concierge and workflow-worker identities `GenerateDataKey` and `Decrypt` only for the `purpose=workflow-content` encryption context. Production startup fails closed without the key.
2. Enable provider connection UI for an allowlisted tenant.
3. Enable individual provider reads and writes.
4. Run `TESSERA_DYNAMIC_PLANNER_SHADOW=true`; compare compiled plans but execute no dynamic workflow.
5. Enable capability families per tenant from the control plane, one account at a time, only after adversarial fixtures meet the gate. Families land disabled, so an account not yet reviewed executes nothing without anyone maintaining a separate allowlist.

The compiler accepts at most ten steps and only exact trusted descriptor versions, healthy tenant-bound connection snapshots, valid scopes, acyclic dependencies, authorized data flows, and explicit identity links. Model output never grants authority.

## Operational signals

Track plan rejection by reason, blocker rate, approval conversion, workflow latency, retry count, unknown outcomes, reconciliation age, verification backlog, duplicate-prevention hits, connection health, and tenant-binding violations. Alert immediately on any cross-tenant access, credential material in logs, repeated write idempotency keys, or execution while its family is disabled or its account is stopped.

Workflow inputs and outputs are envelope-encrypted with a tenant/revision/step/field KMS context. Terminal content expires after 30 days by default and the worker destroys recoverable ciphertext after expiry while retaining minimized receipts and hashes. Monitor the purge count and alert when expired terminal content remains.

## Recovery

- Retry only steps classified safe; reconcile ambiguous writes before another dispatch.
- A changed recipient, connection, descriptor, payload, or graph creates a new revision and needs new approval.
- Cancellation preserves completed receipts and stops only undispatched work.
- Disable dynamic execution to pause queued steps. Re-enable only after live connection, scope, descriptor, expiry, and approval revalidation.

## Post-deploy validation

Owner: integrations on-call. Window: first 60 minutes, then 24 hours. Search the signals above every 10 minutes. Roll back the relevant server-side flag if error rate exceeds 2%, any unknown write remains unreconciled for 15 minutes, or any security invariant fires.
