# Twilio integration qualification and canary runbook

## Purpose

Promote SMS, WhatsApp and voice independently. A connected account is not a
promotion signal. Each family needs a clean language gate and one real canary
effect from a dedicated Twilio test subaccount to a pre-verified destination.

## Preconditions

1. Use a dedicated Twilio test subaccount. Its SID must be present in both
   `TWILIO_CANARY_ACCOUNT_SID` and
   `TWILIO_CANARY_DEDICATED_SUBACCOUNT_SID`.
2. Put destinations only in
   `TWILIO_CANARY_VERIFIED_DESTINATIONS_JSON`. The canary deliberately has no
   `--to` option.
3. Configure status callbacks on a public HTTPS origin and confirm signature
   validation is active.
4. Keep the target family disabled for production tenants during qualification.
5. For WhatsApp free-form, verify an open customer-service session window.
6. For voice, use a dated Grok model, a 30-second maximum, recording disabled,
   and the canary-only opening script.

Example secret names (values remain local):

```bash
TWILIO_CANARY_ACCOUNT_SID=
TWILIO_CANARY_DEDICATED_SUBACCOUNT_SID=
TWILIO_CANARY_AUTH_TOKEN=
TWILIO_CANARY_VERIFIED_DESTINATIONS_JSON='{"sms":"+...","whatsapp":"+...","voice":"+..."}'
TWILIO_CANARY_STATUS_CALLBACK=https://...
TWILIO_CANARY_SMS_FROM=+...
TWILIO_CANARY_WHATSAPP_FROM=+...
TWILIO_CANARY_WHATSAPP_SESSION_OPEN=true
TWILIO_CANARY_VOICE_FROM=+...
TWILIO_CANARY_TWIML_URL=https://...
TWILIO_CANARY_PINNED_VOICE_MODEL=grok-voice-YYYY-MM-DD
TWILIO_CANARY_ENABLED=true
```

## Procedure

Run the static and live language gates first, following
`docs/operations/twilio-language-gate.md`. Stop on any failure.

Preview the selected family without provider I/O:

```bash
.venv/bin/python scripts/twilio_canary.py --family sms
```

The output must say `mode=dry-run` and show only the last four destination
digits. Then execute exactly one effect:

```bash
.venv/bin/python scripts/twilio_canary.py \
  --family sms \
  --execute \
  --confirm-spend I_UNDERSTAND_THIS_COSTS_MONEY
```

Repeat separately for `whatsapp` and `voice`. Never batch families into one
approval. Record the `provider_id`, initial status and final signed callback
status, but not the full destination or auth token.

## Healthy signals

- exactly one provider ID for the invocation;
- callback tenant resolves from the called/sending identity;
- terminal verdict is delivered/completed, or a truthful busy/no-answer result;
- spend reservation settles to actual cost;
- no duplicate dispatch-ledger row;
- voice ends by 30 seconds and creates no recording;
- unknown inbound activity remains in the tenant's unfiled branch.

## Failure and rollback

Keep or return the family to disabled when any of these occurs:

- language or destination threshold misses;
- authority violation or model transport fallback;
- destination is not present in the verified allowlist;
- more than one provider effect, missing terminal callback, or inconclusive
  reconciliation;
- cross-tenant attribution, signature failure, recording without consent, or
  spend above the reservation.

Use the durable tenant emergency stop for evidence of duplicate, cross-tenant,
consent or spend defects. Preserve provider receipts and internal audit IDs,
reconcile uncertain outcomes, and do not retry an unknown write manually.

## Promotion record

For each family record date, tenant/test subaccount, model, corpus and holdout
metrics, canary provider ID, terminal verdict, settled cost, reviewer, and
decision. On 2026-08-07 the automation and static gates are present, but no
credentialed live language run or paid canary was performed; all families
therefore remain **NO-GO by this runbook** until that evidence exists.

