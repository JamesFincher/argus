#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

export PYTHONPATH="$PWD/services${PYTHONPATH:+:$PYTHONPATH}"
exec uv run python -c 'from argus_services.event_gateway import run; run(host="127.0.0.1", port=8765)'
