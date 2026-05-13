#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

export ARGUS_TIMELINE_DB_PATH="${ARGUS_TIMELINE_DB_PATH:-$HOME/Library/Application Support/Argus/timeline.db}"
export PYTHONPATH="$PWD/services${PYTHONPATH:+:$PYTHONPATH}"

if [[ -x "$PWD/.venv/bin/python" ]]; then
  exec "$PWD/.venv/bin/python" -c 'from argus_services.storage_worker import main; raise SystemExit(main())' "$@"
fi

exec uv run python -c 'from argus_services.storage_worker import main; raise SystemExit(main())' "$@"
