#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

PID_FILE="${ARGUS_EVENT_GATEWAY_PID_FILE:-/tmp/argus-event-gateway.pid}"
LOG_FILE="${ARGUS_EVENT_GATEWAY_LOG_FILE:-/tmp/argus-event-gateway.log}"
ERR_FILE="${ARGUS_EVENT_GATEWAY_ERR_FILE:-/tmp/argus-event-gateway.err.log}"
HOST="${ARGUS_EVENT_GATEWAY_HOST:-127.0.0.1}"
PORT="${ARGUS_EVENT_GATEWAY_PORT:-8765}"
HEALTH_URL="http://${HOST}:${PORT}/health"

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
    echo "Argus event gateway already running: pid $(cat "$PID_FILE")"
    exit 0
  fi

  echo "Argus event gateway pid $(cat "$PID_FILE") is alive but $HEALTH_URL is not healthy." >&2
  exit 1
fi

rm -f "$PID_FILE"

if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
  if command -v lsof >/dev/null 2>&1; then
    EXISTING_PID="$(lsof -nP -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | head -n 1 || true)"
    if [[ -n "$EXISTING_PID" ]]; then
      echo "$EXISTING_PID" > "$PID_FILE"
      echo "Argus event gateway already responding: pid $EXISTING_PID"
      exit 0
    fi
  fi

  echo "Argus event gateway already responding at $HEALTH_URL"
  exit 0
fi

ARGUS_EVENT_GATEWAY_HOST="$HOST" ARGUS_EVENT_GATEWAY_PORT="$PORT" PYTHONPATH="$PWD/services${PYTHONPATH:+:$PYTHONPATH}" \
  nohup uv run python -c 'import os; from argus_services.event_gateway import run; run(host=os.environ["ARGUS_EVENT_GATEWAY_HOST"], port=int(os.environ["ARGUS_EVENT_GATEWAY_PORT"]))' \
  >"$LOG_FILE" \
  2>"$ERR_FILE" &

echo "$!" > "$PID_FILE"
sleep 0.5

if ! kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "Argus event gateway failed to start; stderr follows:" >&2
  cat "$ERR_FILE" >&2 || true
  exit 1
fi

echo "Argus event gateway started: pid $(cat "$PID_FILE")"
echo "stdout: $LOG_FILE"
echo "stderr: $ERR_FILE"
