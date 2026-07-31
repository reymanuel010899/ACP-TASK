# Orchestrator concierge — runbook

An LLM-driven concierge over the agent ecosystem: it takes a
natural-language request ("necesito enviar un paquete a Santiago"),
discovers candidate apps/agents, ranks them, asks for terms, gets the
user's approval for any spend, executes over the signed rails, and
reports back courteously.

## 1. Start the stack

Each service in its own terminal, with the venv activated
(`source .venv/bin/activate`). Ports are examples; any free port works.

```bash
python -m registry.app --port 8090                                      # Registry (discovery + P2P)
python -m apps.marketplace.server.app --port 8001 --registry-url http://localhost:8090
python -m apps.gig_board.server.app  --port 8002 --registry-url http://localhost:8090
python -m vault.app --port 8003                                         # optional: credentials
python -m agent_marketplace.app --port 8004 --registry-url http://localhost:8090  # optional: agent discovery
```

(See the repo `README.md` and `docs/demo-runbook.md` for the wider demo
topology; `tests/integration/` runs the same servers on ephemeral ports.)

## 2. Ask the concierge

One-shot:

```bash
python -m agents.orchestrator.cli \
    --registry-url http://localhost:8090 \
    --agent-marketplace-url http://localhost:8004 \
    --vault-url http://localhost:8003 \
    --request "necesito enviar un paquete a Santiago"
```

Omit `--request` for an interactive REPL (`salir` or Ctrl-D to quit).
If the request is ambiguous the concierge asks a clarifying question and
waits for your answer on stdin.

## 3. The approval prompt

Every spend passes the approval gate (U23). In the gray zone between
your limits, you are asked interactively:

```
Approval required for action: execute:shipping.package@marketplace
Cost: 5
Details: {'candidate': 'marketplace', 'capability': 'shipping.package', ...}
Approve? [y/N]
```

`y`/`yes`/`s`/`si` approves; anything else denies (safe default). A
denial ends the conversation politely with exit code 0 — nothing is
charged.

## 4. Spend limits

* `--auto-approve-under N` (default `0`): spends strictly below `N` are
  approved silently, without prompting.
* `--hard-ceiling N` (default `20`): spends strictly above `N` are
  refused outright — no prompt, no override.

Everything in between prompts as shown above.

## 5. Offline mode (RuleBrain)

With `ANTHROPIC_API_KEY` set, requests are understood and answered by
Claude. Without it, the CLI prints a one-line notice and falls back to
the deterministic offline `RuleBrain` (keyword mapping, no network, no
key needed) — the whole flow still works.

## 6. Secure mode

Pass `--require-signatures` to generate a fresh ed25519 keypair and sign
every P2P/vault request with a `SessionContext` (`X-AT-*` headers).
Point it at a stack started in secure mode to exercise end-to-end
signature enforcement. `--credential-id ID` tells the agent the work
needs a vault credential; access to it is gated by the same approval
policy, and only a granted/denied boolean ever reaches the brain.

## 7. Conversational Slack

The web Concierge supports bounded public-channel and thread reads, exact
channel posts and thread replies, and one-to-one DMs. Start conservatively:

```bash
TESSERA_SLACK_CONVERSATIONAL_READS_ENABLED=true
TESSERA_SLACK_WRITES_ENABLED=false
TESSERA_SLACK_DMS_ENABLED=false
TESSERA_SLACK_EXECUTION_ENABLED=false
TESSERA_DYNAMIC_EXECUTION_ENABLED=true
python -m web.concierge --port 8130

TESSERA_DYNAMIC_EXECUTION_ENABLED=true \
python -m services.workflow_worker.app
```

The Concierge and worker must share `WORKFLOW_DATABASE`; session, OAuth and
broker services must use their shared configured stores. Configure either
`ANTHROPIC_API_KEY` or `GROQ_API_KEY` for
full natural-language planning. With neither key, the deterministic RuleBrain
supports the documented common Slack phrases and reports its limitation.

Roll out in this order: reads, channel/thread writes, then DMs. Each flag is
independent. `slack.channels.list` remains available when conversational reads
are disabled. Provider execution additionally requires
`TESSERA_SLACK_EXECUTION_ENABLED=true` and worker execution requires
`TESSERA_DYNAMIC_EXECUTION_ENABLED=true`.

Required bot scopes are `channels:read` for channel discovery,
`channels:history` for public-channel reads, `chat:write` for posts/replies,
`users:read` for person resolution, and `im:write` for DMs. An installation
owner must reconnect Slack after adding scopes; tenant members can use a
healthy tenant installation but cannot change its OAuth lifecycle.

For manual acceptance, use a dedicated sandbox workspace and test channel:

1. Ask what one named person wrote in the previous seven days and open every citation.
2. Ask to post without text, answer the one clarification, inspect the exact preview, then approve once.
3. Read a thread and ask “reply there”; confirm the thread and exact text before approval.
4. Resolve two same-named people, choose one, and approve one DM.
5. Disable each rollout flag independently and confirm unrelated public-channel listing still works.

Never paste tokens into chat, fixtures, screenshots, or logs. Inject rate-limit,
missing-scope, and uncertain-outcome failures only in the sandbox.
