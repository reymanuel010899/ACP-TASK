# Slack Phase 1 product baseline

## What this is

Phase 1 requires product baselines before any family is promoted, because
Success Metrics are written as improvements "against its baseline". Without a
measured starting point, "completion improved" is unfalsifiable.

The numbers below come from `scripts/slack_phase1_canary.py` driving the real
conversational service — interpretation, grounding, resolver, approval, and
dispatch — against the connected Airobotix workspace. They are not from tests.

Measured 2026-08-03, tenant `org:local`, channel `#tessera-test`, all four
Slack flags enabled.

## Baseline by operation family

| Family | Jobs | Completed | Clarifications/job | Median time-to-outcome |
|---|---|---|---|---|
| `post` (message) | 8 | **8 (100%)** | 0.00 | **1.78–1.80 s** |
| `read` | 8 | **8 (100%)** | 0.00 | **3.06–3.08 s** |

Reads reached 100% only after U4's first slice replaced the LLM-planned read
path. The 0% figure recorded earlier in this document is retained below as the
pre-U4 baseline, because the improvement is the point.

### Message family — complete funnel

Every message job traversed the whole lifecycle and each stage emitted its
outcome event:

```
operation_attempted → previewed → approved → completed
```

Every message was delivered to `#tessera-test` through the approval path,
not through a direct API call. This is the first evidence that the preview,
approval, and dispatch machinery works end to end against a real workspace.

### Read family — 0% before U4, 100% after

**Pre-U4 baseline: every read job failed.** The cause is not Slack and not authority: the
conversational read path builds its workflow by asking the planner brain for a
`WorkflowPlanDraft` (`dynamic_workflow_service.py:285`), and the model returns
drafts that fail schema validation. The resolver-completion event then
exhausts its retries and dead-letters.

This is what U4's execution note already anticipates — "make the durable
bounded pipeline the only conversational read path".

**Post-U4 measurement: 8 of 8 reads complete, median 3.06 s.** The conversational
read now compiles its own step from grounded state, bounded by page size and a
disclosed seven-day window, with no planner call. Reads are slower than writes
because they resolve the channel first and then page; that gap is the honest
starting point for U4's remaining slices.

## Two production fixes verified by this run

Both were found through this traffic and confirmed fixed by it.

**Stranded capability leases** (`d13ff56`). Before: `resolve-slack-channel`
died at `attempt=2` with a UNIQUE violation reported as `execution_unknown`,
which requires reconciliation and stranded the conversation permanently.
After: steps complete at `attempt=1`, and the `execution_unknown` counter held
at 10 across every subsequent run.

**Hanging dead-lettered turns** (`e4d1a08`). Before: a conversation whose
event dead-lettered stayed in `resolving` forever, and read-only polling could
never move it. After: the same failures land in `retryable_failure` with a
recovery need, so the turn ends and can be retried.

## Finding: the language gate does not cover interrogative reads

The U2 gate passed at 100%, but its corpus tests only four read phrasings, all
imperative or bare-channel:

```
"Lee los mensajes de #anuncios."      "#customer-success, latest messages"
"Lee #incidentes y then post there"   "#finanzas"
```

Interrogative forms — the most natural way to ask for a read in Spanish — are
absent, and they currently classify as `unsupported`:

| Utterance | Classified |
|---|---|
| `¿Qué se dijo en #canal?` | `unsupported` |
| `¿Qué se habló en #canal esta semana?` | `unsupported` |
| `Resume el canal #canal` | `summarize` |
| `Lee los últimos mensajes de #canal` | `read` |

The gate result stands — it measured what it measured — but it does not
establish read coverage as broadly as its headline suggests.

Per the gate's own rules, this must not be fixed by adding these cases to the
corpus. It is a general error class (interrogative read intent) and requires a
routing or prompt change validated against a separately authored holdout. The
canary deliberately uses imperative phrasing meanwhile, so that this language
gap is not silently reported as a product failure rate.

## Open: the vault credential disappears

`vault.credentials` emptied five times during this session while
`integration_connections` still reported `status: connected` against a
credential id that no longer existed. Every Slack operation then failed.

### What has been eliminated

Each of these was tested, not assumed:

| Hypothesis | Result |
|---|---|
| Stack restart deletes it | **No** — a controlled down/up left the row intact (1 before, 1 after) |
| Row-level security hides it | **No** — connecting as `postgres`, RLS is neither enabled nor forced |
| A background sweeper deletes it | **No** — 120 s of continuous polling at 0.4 s resolution caught only reconnect-driven transitions |
| The write is never committed | **No** — `store_credential` uses `transaction()`, which commits |
| Shutdown hooks clean up | **No** — `dev-stack.sh down` only kills PIDs; no signal handlers exist |
| Startup runs migrations that reset the schema | **No** — `up` starts processes and nothing else |
| A cascading delete from `identity.principals` | **No** — the foreign key has no `ON DELETE CASCADE`, and all principals remain |

### What remains

Deletion must therefore come from `delete_managed_oauth_credential`, whose only
callers are four explicit paths in `services/oauth/app.py`: connection
conflict, disconnect, revoke, and reconnect-retire.

The leading hypothesis is the conflict path at `services/oauth/app.py:268`,
which deletes the credential it just created and returns 409 when
`upsert_installation` raises `ConnectionConflict`. That would leave exactly
the observed state: a connection pointing at an id the vault never kept. It
has **not** been reproduced, so it stays a hypothesis.

### Why this is now cheaper to hit

Before, the symptom was `provider is temporarily unavailable` after five
retries, which is a lie: nothing was temporary and retrying could never help.
The step now reports `credential_unavailable` on its first attempt, and the
broker logs a traceback for anything it still cannot classify.

## Reproducing

```bash
scripts/slack_phase1_canary.py --jobs 20 --channel tessera-test
scripts/slack_phase1_canary.py --baseline-only        # report only
```

Message jobs post real messages to the target channel. Run against a test
workspace only.

## What this baseline does not yet cover

- **Repeat weekly use** and **failure-followed-by-no-retry-within-session**,
  both listed in Success Metrics, need longitudinal traffic rather than a
  single run.
- **Correction and rejection rates** need jobs that deliberately correct a
  slot or reject a preview; the canary currently approves everything.
- **The chaining-versus-composition comparison** (`--compare`) has not been
  run, so U7's compound-DAG slice remains unscoped.
