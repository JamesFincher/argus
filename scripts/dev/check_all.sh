#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

python3 scripts/verify_spec.py
scripts/dev/verify_local_infra.py
uv run --with pytest pytest -q
swift test
sqlite3 :memory: < storage/sqlite/migrations/001_timeline_fts5.sql
docker compose -f infra/compose.yaml config >/tmp/argus-compose-config.txt

echo "Argus checks passed."
