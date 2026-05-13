#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

echo "Git:"
git status --short --branch

echo
echo "Docker mesh:"
docker compose -f infra/compose.yaml ps

echo
echo "Event gateway:"
PID_FILE="${ARGUS_EVENT_GATEWAY_PID_FILE:-/tmp/argus-event-gateway.pid}"
HOST="${ARGUS_EVENT_GATEWAY_HOST:-127.0.0.1}"
PORT="${ARGUS_EVENT_GATEWAY_PORT:-8765}"
HEALTH_URL="http://${HOST}:${PORT}/health"
if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "running pid $(cat "$PID_FILE")"
  curl -fsS "$HEALTH_URL" || true
  echo
elif curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
  echo "responding at $HEALTH_URL without tracked pid"
else
  echo "not running"
fi

echo
echo "Storage worker:"
WORKER_PID_FILE="${ARGUS_STORAGE_WORKER_PID_FILE:-/tmp/argus-storage-worker.pid}"
if [[ -f "$WORKER_PID_FILE" ]] && kill -0 "$(cat "$WORKER_PID_FILE")" 2>/dev/null; then
  echo "running pid $(cat "$WORKER_PID_FILE")"
else
  echo "not running"
fi
