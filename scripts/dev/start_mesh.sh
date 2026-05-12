#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

docker compose -f infra/compose.yaml up -d redis redis-exporter neo4j prometheus grafana
docker compose -f infra/compose.yaml ps
