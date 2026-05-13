#!/usr/bin/env bash
set -euo pipefail

PID_FILE="${ARGUS_STORAGE_WORKER_PID_FILE:-/tmp/argus-storage-worker.pid}"

if [[ ! -f "$PID_FILE" ]]; then
  echo "Argus storage worker is not running."
  exit 0
fi

PID="$(cat "$PID_FILE")"
if kill -0 "$PID" 2>/dev/null; then
  kill "$PID"
  echo "Stopped Argus storage worker: pid $PID"
else
  echo "Argus storage worker pid file was stale: $PID"
fi

rm -f "$PID_FILE"
