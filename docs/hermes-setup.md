# Argus Hermes Setup

This is the verified setup path for connecting Argus to Hermes/Gengar on this
Mac. Use the MCP path first; it is the live-tested integration surface. The
plugin path is packaged and contract-tested, but it only becomes visible to
Hermes after Argus is installed into the same Python environment that Hermes
scans for entry-point plugins.

## 1. Prepare Local Argus Paths

Argus keeps raw sensor data local. Use one explicit data directory so the
gateway, MCP server, plugin, and dashboard all read from the same timeline and
audit store:

```sh
export ARGUS_HOME="$HOME/Library/Application Support/Argus"
mkdir -p "$ARGUS_HOME"

export ARGUS_TIMELINE_DB_PATH="$ARGUS_HOME/timeline.db"
export ARGUS_LANCEDB_PATH="$ARGUS_HOME/notes.lancedb"
export ARGUS_APPROVAL_TOKEN="$(uuidgen | tr '[:upper:]' '[:lower:]')"
```

Do not commit `ARGUS_APPROVAL_TOKEN`. It is only for explicit full raw event
expansion; sanitized summaries and redacted tool results do not require it.

## 2. Install Argus For Local Commands

From the repository root:

```sh
uv sync
uv pip install -e /Users/james/code/argus/argus
```

The package installs these MCP-compatible launcher names:

- `argus-mcp-stdio`
- `argus-sensor-mcp`
- `hermes-sensor-mcp`

They all start the same stdio MCP server. Use `argus-sensor-mcp` in new setup
commands so the name clearly matches the Argus sensor system.

## 3. Start The Local Argus Stack

For the local services:

```sh
scripts/dev/start_mesh.sh
scripts/dev/start_event_gateway.sh
scripts/dev/start_storage_worker.sh
scripts/dev/status_stack.sh
```

Open the operator dashboard:

```sh
open http://127.0.0.1:8765/dashboard
```

The dashboard has separate sections for raw local events, sanitized
Hermes-facing outputs, the audit trail, Redis status, sensor health, permission
state, pause/resume, scoped forget, and redacted session export.

## 4. Add Argus MCP To Hermes

The verified local CLI shape is:

```sh
hermes mcp add argus-sensor \
  --command uv \
  --env "ARGUS_TIMELINE_DB_PATH=$ARGUS_TIMELINE_DB_PATH" \
  --env "ARGUS_LANCEDB_PATH=$ARGUS_LANCEDB_PATH" \
  --env "ARGUS_APPROVAL_TOKEN=$ARGUS_APPROVAL_TOKEN" \
  --args run argus-sensor-mcp
```

If Hermes asks whether to add the server, answer `Y`.

Then verify discovery:

```sh
hermes mcp test argus-sensor
hermes mcp list
uv run python scripts/verify_hermes_runtime.py
```

Expected Argus tools include:

- `sensor_get_recent_notes`
- `sensor_expand_event`
- `sensor_timeline_search`
- `sensor_find_workflow_patterns`
- `sensor_pause_scope`
- `sensor_forget_scope`
- `sensor_export_session_brief`

If Hermes cannot find `uv`, re-add the MCP server with an absolute command:

```sh
hermes mcp remove argus-sensor
hermes mcp add argus-sensor \
  --command "$(command -v uv)" \
  --env "ARGUS_TIMELINE_DB_PATH=$ARGUS_TIMELINE_DB_PATH" \
  --env "ARGUS_LANCEDB_PATH=$ARGUS_LANCEDB_PATH" \
  --env "ARGUS_APPROVAL_TOKEN=$ARGUS_APPROVAL_TOKEN" \
  --args run argus-sensor-mcp
```

## 5. Plugin Hook Setup

Argus publishes both Hermes plugin entry-point groups:

- `hermes_agent.plugins:argus = argus_services.hermes_plugin:register`
- `hermes.plugins:argus = argus_services.hermes_plugin:register`

The current contract-tested hooks are:

- `pre_llm_call`: returns a short sanitized ambient context from
  `sensor_get_recent_notes`.
- `pre_tool_call`: blocks sensitive tool arguments and returns Hermes'
  documented veto shape, `{"action": "block", "message": "..."}`, when full raw
  `sensor_expand_event` access is not approved.

After installing Argus into the Python environment that Hermes scans, check
plugin discovery:

```sh
hermes plugins list
hermes plugins enable argus
```

`hermes plugins list` should show `argus` as an entry-point plugin before the
enable command is useful. If `argus` does not appear, keep using the MCP path
and fix the environment mismatch before relying on hook injection. The runtime
verifier intentionally checks package entry points and live MCP add/test; it
does not claim that the current Hermes executable has already enabled the Argus
plugin in its own runtime environment.

## 6. Safe Hermes Smoke Prompts

Use these after MCP discovery succeeds:

```text
What recent Argus sensor notes are available? Use Argus tools if needed and
summarize only sanitized context.
```

```text
Search Argus timeline for browser_page activity and give me the safe summary
with event IDs. Do not reveal raw payloads.
```

```text
Try to expand an Argus event in full raw mode without approval. Explain the
policy result and do not reveal raw data.
```

Full raw expansion should stay blocked unless the operator intentionally passes
the matching `ARGUS_APPROVAL_TOKEN` for a specific low-risk event.

## 7. Browser Native Messaging Prompt

When installing the browser native host, use the exact extension origin:

```sh
python scripts/install_native_messaging_host.py install \
  --host-path "$(command -v argus-native-host)" \
  --allowed-origin "chrome-extension://<extension-id>/" \
  --browser chrome
```

The allowed origin must include the trailing slash and must match the extension
ID shown by the browser.

## 8. Troubleshooting

- `hermes mcp test argus-sensor` does not list Argus tools: re-run the `mcp add`
  command and make sure `--args run argus-sensor-mcp` appears after all `--env`
  entries.
- `ARGUS_TIMELINE_DB_PATH` contains spaces: quote every env assignment exactly
  as shown above.
- Raw expansion returns an approval error: this is expected without
  `approval_token`; use sanitized summaries or redacted expansion by default.
- `Hermes Python packages visible to this verifier: MISSING`: this means the
  verifier's Python process cannot import Hermes internals. That does not block
  MCP verification as long as the `hermes` command itself can add and test the
  Argus MCP server.
- `argus` is missing from `hermes plugins list`: Argus is not installed into the
  plugin environment Hermes scans. The MCP setup is still the supported primary
  path while that environment is corrected.
