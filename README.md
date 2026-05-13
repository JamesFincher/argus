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
shows the audit trail, reports Redis stream status, rolls up sensor
heartbeats/permission state, and exposes pause/resume, scoped forget, and
redacted session-export controls for gateway ingest.
Prometheus text metrics are available from the same loopback service at
`http://127.0.0.1:8765/metrics`.

Run the Redis-to-SQLite storage worker in the foreground:

```sh
scripts/dev/run_storage_worker.sh
```

Or run it in the background:

```sh
scripts/dev/start_storage_worker.sh
scripts/dev/status_stack.sh
```

Set `ARGUS_TIMELINE_DB_PATH` to persist gateway-ingested events into the local
SQLite + FTS5 timeline:

```sh
ARGUS_TIMELINE_DB_PATH="$HOME/Library/Application Support/Argus/timeline.db" \
  scripts/dev/start_event_gateway.sh
```

The Docker Compose stack publishes Redis, Neo4j, Prometheus, and Grafana only
on `127.0.0.1` by default. Redis protected mode is disabled for this local
stack so the host event gateway can write through Docker's loopback-published
port. Redis Streams carry the full event contract so workers can replay, ack,
reclaim, dead-letter, and persist events into SQLite without raw data leaving
the local machine.

Semantic retrieval stores derived perception notes only. The default index uses
deterministic local embeddings for tests and offline operation; the
`LanceDBNoteIndex` backend persists the same raw-free note records to a local
LanceDB path when the optional `lancedb` package is installed.

Neo4j remains optional and disabled by default. `sensor_find_workflow_patterns`
falls back to local timeline transitions unless `ARGUS_NEO4J_ENABLED=1` and a
Neo4j adapter are explicitly configured.

## Hermes MCP Transport

Argus exposes the local sensor tools over stdio JSON-RPC for Hermes. The package
installs three compatible launcher names that all run the same transport:
`argus-mcp-stdio`, `argus-sensor-mcp`, and `hermes-sensor-mcp`.

Minimal tool-list smoke test:

```sh
printf '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}\n' \
  | ARGUS_TIMELINE_DB_PATH="$HOME/Library/Application Support/Argus/timeline.db" \
    uv run argus-sensor-mcp
```

Hermes config can point at the same command:

```yaml
mcp_servers:
  sensor:
    command: "uv"
    args: ["run", "argus-sensor-mcp"]
    env:
      ARGUS_TIMELINE_DB_PATH: "/Users/james/Library/Application Support/Argus/timeline.db"
```

MCP tools return sanitized content by default. Full raw event expansion remains
policy-gated and every agent-facing call records an audit entry in the local
audit store.

## Browser Native Host

`argus-native-host` implements the browser native messaging protocol for Safari
or WebExtension page-context events. It reads framed JSON messages from stdin,
validates HTTP/HTTPS page context, converts them into canonical
`activity.browser_page` events, and posts them to the loopback gateway at
`http://127.0.0.1:8765/events` by default. Override the target only with another
loopback `/events` URL:

```sh
ARGUS_EVENT_GATEWAY_URL="http://127.0.0.1:8765/events" uv run argus-native-host
```

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
