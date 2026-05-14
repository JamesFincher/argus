#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

export ARGUS_HOME="${ARGUS_HOME:-$HOME/Library/Application Support/Argus}"
export ARGUS_TIMELINE_DB_PATH="${ARGUS_TIMELINE_DB_PATH:-$ARGUS_HOME/timeline.db}"
if [[ -n "${ARGUS_LANCEDB_PATH:-}" ]]; then
  export ARGUS_LANCEDB_PATH
fi
export PYTHONPATH="$PWD/services${PYTHONPATH:+:$PYTHONPATH}"

exec uv run argus-sensor-mcp "$@"
