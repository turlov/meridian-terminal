#!/usr/bin/env bash
# Start a built binary headless on a spare port, check the dashboard and the API answer,
# then stop it. Usage: bash packaging/smoke_test.sh <path-to-binary> [port]
set -euo pipefail
BIN="$1"
PORT="${2:-8791}"
MERIDIAN_HOME="$(mktemp -d)"
export MERIDIAN_HOME

"$BIN" version
TOKEN="$("$BIN" token)"
"$BIN" headless --port "$PORT" > "$MERIDIAN_HOME/smoke.log" 2>&1 &
PID=$!
trap 'kill "$PID" 2>/dev/null || true; wait "$PID" 2>/dev/null || true' EXIT

for _ in $(seq 1 60); do
  if curl -fs "http://127.0.0.1:$PORT/" >/dev/null 2>&1; then break; fi
  if ! kill -0 "$PID" 2>/dev/null; then
    echo "The binary exited early (is Meridian Terminal already running? Quit it first):"
    cat "$MERIDIAN_HOME/smoke.log"
    exit 1
  fi
  sleep 0.5
done
curl -fs "http://127.0.0.1:$PORT/" | grep -q "Meridian Terminal"
curl -fs "http://127.0.0.1:$PORT/static/vendor/lightweight-charts.standalone.production.js" >/dev/null
curl -fs "http://127.0.0.1:$PORT/static/js/app.js" | grep -q "connectWS"
STATE="$(curl -fs -H "X-Token: $TOKEN" "http://127.0.0.1:$PORT/api/state")"
echo "$STATE" | grep -q '"demo": true'
code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/api/state")"
[ "$code" = "401" ] || { echo "API answered $code without a token"; exit 1; }
echo "smoke test passed ($BIN)"
