#!/usr/bin/env bash
set -euo pipefail

PID_FILE="${ARGUS_EVENT_GATEWAY_PID_FILE:-/tmp/argus-event-gateway.pid}"
HOST="${ARGUS_EVENT_GATEWAY_HOST:-127.0.0.1}"
PORT="${ARGUS_EVENT_GATEWAY_PORT:-8765}"
HEALTH_URL="http://${HOST}:${PORT}/health"

if [[ ! -f "$PID_FILE" ]]; then
  if curl -fsS "$HEALTH_URL" >/dev/null 2>&1 && command -v lsof >/dev/null 2>&1; then
    PID="$(lsof -nP -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | head -n 1 || true)"
    if [[ -n "$PID" ]]; then
      kill "$PID"
      echo "Stopped Argus event gateway: pid $PID"
      exit 0
    fi
  fi

  echo "Argus event gateway is not running."
  exit 0
fi

PID="$(cat "$PID_FILE")"
if kill -0 "$PID" 2>/dev/null; then
  kill "$PID"
  echo "Stopped Argus event gateway: pid $PID"
else
  echo "Argus event gateway pid file was stale: $PID"
fi

rm -f "$PID_FILE"
