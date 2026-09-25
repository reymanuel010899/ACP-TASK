# Slack Phase 1 rate-tier measurement

## Decision contract

Phase 1 requires measuring the installed Slack app's actual per-method rate
tier in the test workspace, then choosing explicitly between a Marketplace
listing, AI-search/user-token strategies, or a redesigned low-volume read UX.
That decision is a prerequisite for enabling U4.

The measurement exists because the tier cannot be read from documentation. The
2025 Slack changelog constrains `conversations.history` and
`conversations.replies` for non-Marketplace apps, so the same code can face
either a workable budget or a per-minute ceiling that makes conventional
pagination impossible. Only the installed app in the real workspace answers it.

Two independent quantities decide the outcome:

1. **Per-request message cap** — whether a page is silently truncated. Governs
   whether pagination can complete a bounded read at all.
2. **Requests per minute** — the sustained call budget. Governs whether a
   multi-page read finishes inside a conversational latency budget.

The second dominates. A low per-request cap is inconvenient; a one-request-per-
minute ceiling changes the product.

## Measured environment

| Field | Value |
|---|---|
| Workspace | Airobotix (`T0BG5AUS0TF`), `airobotixespacio.slack.com` |
| Enterprise install | No |
| Bot user | `tessera_local` (`U0BLSQASS3U`), bot `B0BLUNB4DUZ` |
| Connection created | 2026-07-30 |
| Token | Bot token with rotation enabled (`refresh_token` present) |
| Channel under test | `#tessera-test` (`C0BMM8WAD08`), bot is a member |
| Credential path | AWS KMS envelope opened under the broker identity from the Postgres vault — the same path production dispatch uses |
| Measured | 2026-08-03 |

## Results

### Per-request message cap — no cap observed

`conversations.history` against a channel holding 19 messages:

| `limit` requested | Messages returned | `has_more` | Cursor |
|---|---|---|---|
| 200 | 19 | `false` | none |
| 100 | 19 | `false` | none |
| 15 | 15 | `true` | present |

Requesting 200 returned the full 19. A restricted app returns a silently
truncated page instead. The `limit=15` row confirms pagination itself behaves
correctly: it reports `has_more` and issues a usable cursor.

### Requests per minute — no throttling observed

`conversations.history` called in a tight loop with `limit=1`:

| Metric | Value |
|---|---|
| Requests issued | 80 |
| Elapsed | 26.8 s |
| Sustained rate | 3.0 req/s (~180 req/min) |
| `429` responses | 0 |
| `Retry-After` | not reached |

## Outcome

The installed app is **not** on the restricted non-Marketplace tier for
`conversations.history`. Both measured quantities are far from the constrained
case.

This resolves the Phase 1 gate in favour of the simplest option. U4 can be
designed with conventional pagination and ordinary budgets:

- a **Marketplace listing** is not required to unblock reads;
- **user-token or AI-search** strategies are not required, so U6's elevated
  authority profile does not need to move from Phase 3 into Phase 2;
- a **low-volume read UX redesign** is not required.

Those three strategies remain available for other reasons — user-token search
still governs `search.messages`, which no current capability uses — but none of
them is now a prerequisite for U4.

## Limits of this evidence

Two constraints bound how far this result may be carried. Neither invalidates
the outcome above; both must be resolved before the numbers are used to tune
production budgets.

**The rate probe is a burst, not a sustained run.** 80 requests over 26.8
seconds conclusively rules out a one-request-per-minute ceiling, but Slack
permits short bursts. The true sustained ceiling is above 80 requests in that
window and is otherwise unmeasured. Tuning U4's page budgets against a precise
ceiling requires a multi-minute sustained run.

**The reason the 2025 restriction does not apply is unknown.** The connection
was created on 2026-07-30, which should place a non-Marketplace app under the
new-install rules. It is not. The cause may be a workspace plan, an app status,
or a change in Slack's rules since the changelog this plan cites. Building U4
on an unexplained exemption is a standing risk: if the cause is temporary, the
budget assumption moves underneath the design. Confirm the app's listing and
tier status with Slack before freezing U4's rate policy.

**The channel is small.** `#tessera-test` held 19 messages. That is enough to
prove no per-request cap applies and that cursors work, but not enough to
exercise deep multi-page pagination. A channel with several hundred messages is
needed before U4's pagination and partial-result behaviour can be validated end
to end.

## Reproducing

The probe opens the sealed Slack credential through the KMS/vault path, then
calls `conversations.history` directly. It requires the repository `.env`
(`DATABASE_URL`, `MANAGED_OAUTH_KMS_KEY_ID`, and AWS credentials) and a
reachable Postgres vault.

The rate probe deliberately saturates `conversations.history` for the
workspace. It performs reads only — nothing is written or deleted — but the
method stays throttled until the `Retry-After` window elapses. Do not run it
against a production workspace.
