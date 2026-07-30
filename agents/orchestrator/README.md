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
