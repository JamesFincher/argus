#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

exec uv run python -m argus_services.event_gateway --host 127.0.0.1 --port 8765
