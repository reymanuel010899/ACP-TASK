#!/usr/bin/env bash
# Local development stack: every backend service the frontend's BFF proxies to,
# plus the Next.js app over local HTTPS (Slack/Google redirect URIs are
# https://localhost:3000/...).
#
#   scripts/dev-stack.sh up       start everything (default)
#   scripts/dev-stack.sh down     stop everything
#   scripts/dev-stack.sh status   show what is listening
#
# Secrets come from the gitignored .env at the repo root. Logs go to .local/.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="$ROOT/.venv/bin/python"
LOGS="$ROOT/.local"
PIDS="$LOGS/pids"
mkdir -p "$PIDS"

if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/.env"
  set +a
fi
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

# name:port pairs, started in dependency order.
SERVICES=(
  "registry:8090"
  "vault:8003"
  "verification:8080"
  "runner:8110"
  "session:8120"
  "oauth:8121"
  "action_broker:8122"
  "concierge:8130"
  "workflow_worker:0"
  "twilio_webhook:8140"
  "frontend:3000"
)
if [ -n "${XAI_API_KEY:-}" ]; then
  SERVICES+=("voice_bridge:8150")
fi
if [ -n "${CAMPAIGN_WORKER_FACTORY:-}" ]; then
  SERVICES+=("campaign_worker:0")
fi

start_cmd() {
  case "$1" in
    registry)       echo "$PY -m registry.app --port 8090" ;;
    vault)          echo "$PY -m vault.app --port 8003" ;;
    verification)   echo "$PY -m services.verification.app --port 8080" ;;
    runner)         echo "$PY -m runner.app --port 8110 --registry-url $REGISTRY_URL --verification-url $VERIFICATION_URL" ;;
    session)        echo "$PY -m services.session.app --port 8120" ;;
    oauth)          echo "$PY -m services.oauth.app --port 8121" ;;
    # Imported (not `-m`) on purpose: composition.py imports
    # services.action_broker.app, so running it as __main__ would create a
    # second, distinct ActionBroker class and fail the isinstance check.
    action_broker)  echo "$PY $ROOT/scripts/run_action_broker.py --port 8122" ;;
    concierge)      echo "$PY -m web.concierge --port 8130 --registry-url $REGISTRY_URL --vault-url $VAULT_URL --runner-url $RUNNER_URL --action-broker-url $ACTION_BROKER_URL --action-broker-token $TESSERA_ACTION_BROKER_INTERNAL_TOKEN" ;;
    workflow_worker) echo "$PY -m services.workflow_worker.app" ;;
    campaign_worker) echo "$PY -m services.campaign_worker.app --factory $CAMPAIGN_WORKER_FACTORY" ;;
    twilio_webhook)  echo "$PY -m services.twilio_webhook.app --port 8140" ;;
    voice_bridge)    echo "$PY -m services.voice_bridge.app --port 8150" ;;
    frontend)       echo "npm --prefix $ROOT/frontend run dev -- --experimental-https --hostname localhost --port 3000" ;;
  esac
}

port_pid() { lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null | head -1; }

stop_one() {
  local name="$1" port="$2" pid
  pid="$(cat "$PIDS/$name.pid" 2>/dev/null)"
  [ -n "${pid:-}" ] && kill "$pid" 2>/dev/null
  if [ "$port" != "0" ]; then
    pid="$(port_pid "$port")"
    [ -n "${pid:-}" ] && kill "$pid" 2>/dev/null
  fi
  rm -f "$PIDS/$name.pid"
}

wait_for_port() {
  local port="$1" tries="${2:-60}"
  for _ in $(seq 1 "$tries"); do
    [ -n "$(port_pid "$port")" ] && return 0
    sleep 1
  done
  return 1
}

up() {
  for entry in "${SERVICES[@]}"; do
    name="${entry%%:*}"; port="${entry##*:}"
    stop_one "$name" "$port"
  done
  sleep 1

  for entry in "${SERVICES[@]}"; do
    name="${entry%%:*}"; port="${entry##*:}"
    printf '%-16s' "$name"
    # shellcheck disable=SC2086
    nohup $(start_cmd "$name") >"$LOGS/$name.log" 2>&1 &
    echo $! >"$PIDS/$name.pid"
    if [ "$port" = "0" ]; then
      sleep 2
      if kill -0 "$(cat "$PIDS/$name.pid")" 2>/dev/null; then echo "running"; else echo "FAILED  (see .local/$name.log)"; fi
    elif wait_for_port "$port" "$([ "$name" = frontend ] && echo 120 || echo 30)"; then
      echo "http://127.0.0.1:$port"
    else
      echo "FAILED  (see .local/$name.log)"
    fi
  done
  echo
  echo "Frontend: https://localhost:3000  (accept the local dev certificate)"
}

down() {
  for entry in "${SERVICES[@]}"; do
    name="${entry%%:*}"; port="${entry##*:}"
    stop_one "$name" "$port"
    echo "stopped $name"
  done
}

status() {
  for entry in "${SERVICES[@]}"; do
    name="${entry%%:*}"; port="${entry##*:}"
    if [ "$port" = "0" ]; then
      pid="$(cat "$PIDS/$name.pid" 2>/dev/null)"
      if [ -n "${pid:-}" ] && kill -0 "$pid" 2>/dev/null; then printf '%-16s running (pid %s)\n' "$name" "$pid"; else printf '%-16s down\n' "$name"; fi
    elif [ -n "$(port_pid "$port")" ]; then
      printf '%-16s listening on %s\n' "$name" "$port"
    else
      printf '%-16s down\n' "$name"
    fi
  done
}

case "${1:-up}" in
  up) up ;;
  down) down ;;
  status) status ;;
  *) echo "usage: $0 {up|down|status}" >&2; exit 2 ;;
esac
