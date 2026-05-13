# Argus

Argus is a local-first sensor and policy system. The repo is currently building
the macOS-first path from `argus_spec.md`: Argus Sensor collects only
user-approved local signals, Argus Core normalizes and redacts them, Argus Mesh
keeps local transport/storage on loopback, and Hermes integration reads
policy-checked summaries/tools instead of raw firehose context.

## Product Map

- **Argus Core:** event envelopes, redaction, perception, policy, MCP tools.
- **Argus Sensor:** native macOS app and future iOS/watchOS collectors.
- **Argus Mesh:** Redis Streams, SQLite/FTS5, optional Neo4j, metrics.
- **ArgusOS:** visible controls, startup/runtime, permissions, packaging.

## Local Checks

Run the full validation set:

```sh
scripts/dev/check_all.sh
```

That runs the spec verifier, infra verifier, Python tests, Swift tests, SQLite
migration load, and Docker Compose config rendering.

Current focused commands:

```sh
swift test
swift build --target ArgusSensorMac
uv run --with pytest pytest -q
python3 scripts/verify_spec.py
scripts/dev/verify_local_infra.py
docker compose -f infra/compose.yaml config
```

## Local Services

Start the loopback-only Argus Mesh scaffold:

```sh
scripts/dev/start_mesh.sh
```

Run the local event gateway on `127.0.0.1:8765`:

```sh
scripts/dev/run_event_gateway.sh
```

Or start it in the background and inspect runtime status:

```sh
scripts/dev/start_event_gateway.sh
scripts/dev/status_stack.sh
```

Open the local ArgusOS dashboard while the gateway is running:

```sh
open http://127.0.0.1:8765/dashboard
```

The dashboard separates raw local events from sanitized Hermes-facing outputs,
shows the audit trail, reports Redis stream status, and exposes pause/resume
controls for gateway ingest.

Set `ARGUS_TIMELINE_DB_PATH` to persist gateway-ingested events into the local
SQLite + FTS5 timeline:

```sh
ARGUS_TIMELINE_DB_PATH="$HOME/Library/Application Support/Argus/timeline.db" \
  scripts/dev/start_event_gateway.sh
```

The Docker Compose stack publishes Redis, Neo4j, Prometheus, and Grafana only
on `127.0.0.1` by default. Redis protected mode is disabled for this local
stack so the host event gateway can write through Docker's loopback-published
port.

## macOS App

Build the macOS Argus Sensor package target:

```sh
swift build --target ArgusSensorMac
```

Package it as a local `.app` bundle:

```sh
scripts/dev/package_macos_app.sh
open "dist/Argus Sensor.app"
```

The app includes permission status, pause/resume controls, a visible menu bar
status item, NSWorkspace/Accessibility event paths, local JSONL spooling, and a
loopback event-gateway sink. It also includes a consent-gated
ScreenCaptureKit/Vision OCR skeleton that redacts before summary.
