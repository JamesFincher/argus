#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

PID_FILE="${ARGUS_STORAGE_WORKER_PID_FILE:-/tmp/argus-storage-worker.pid}"
LOG_FILE="${ARGUS_STORAGE_WORKER_LOG_FILE:-/tmp/argus-storage-worker.log}"
ERR_FILE="${ARGUS_STORAGE_WORKER_ERR_FILE:-/tmp/argus-storage-worker.err.log}"
export ARGUS_TIMELINE_DB_PATH="${ARGUS_TIMELINE_DB_PATH:-$HOME/Library/Application Support/Argus/timeline.db}"
export PYTHONPATH="$PWD/services${PYTHONPATH:+:$PYTHONPATH}"

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "Argus storage worker already running: pid $(cat "$PID_FILE")"
  exit 0
fi

rm -f "$PID_FILE"

if [[ -x "$PWD/.venv/bin/python" ]]; then
  nohup "$PWD/.venv/bin/python" -c 'from argus_services.storage_worker import main; raise SystemExit(main())' >"$LOG_FILE" 2>"$ERR_FILE" &
else
  nohup uv run python -c 'from argus_services.storage_worker import main; raise SystemExit(main())' >"$LOG_FILE" 2>"$ERR_FILE" &
fi

echo "$!" > "$PID_FILE"
sleep 0.5

if ! kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "Argus storage worker failed to start; stderr follows:" >&2
  cat "$ERR_FILE" >&2 || true
  exit 1
fi

echo "Argus storage worker started: pid $(cat "$PID_FILE")"
echo "timeline: $ARGUS_TIMELINE_DB_PATH"
echo "stdout: $LOG_FILE"
echo "stderr: $ERR_FILE"
