# Deep Research Alignment

This crosswalk tracks the May 2026 deep-research report against the current
Argus repo. The goal is to keep the implementation aligned with the report
without pretending that future sensor collectors or release packaging are done
before they are functional.

| Report item | Current status | Evidence |
|---|---|---|
| Hybrid local-first architecture: sensors to Argus, not directly to Hermes | Matched | Event gateway, SQLite timeline/audit, MCP tools, plugin hooks, and dashboard are local-first and loopback-oriented. |
| No prompt firehose | Matched | `pre_llm_call` pulls `sensor_get_recent_notes`; raw detail is exposed through MCP tools only. |
| Hermes plugin entry-point group should be `hermes_agent.plugins` | Matched | `pyproject.toml` publishes `hermes_agent.plugins`; legacy `hermes.plugins` remains for compatibility. |
| Hermes `pre_tool_call` veto shape should be `{"action": "block", "message": "..."}` | Matched | `argus_services.hermes_plugin` uses that shape; tests cover the blocked return. |
| Detail-on-demand should use local stdio MCP | Matched | `argus-sensor-mcp` implements stdio JSON-RPC and `scripts/verify_hermes_runtime.py` exercises `hermes mcp add/test`. |
| MCP tool surface should stay narrow | Matched | The server exposes summary, expansion, timeline search, workflow search, pause, forget, and brief export only. |
| Raw data should stay local and audited | Matched | Gateway ingest records raw local events and audit details locally; MCP/plugin-facing calls record sanitized output or raw-access decisions. |
| Operator dashboard should show raw, sanitized, audit, Redis, and sensor controls | Matched | `/dashboard` and `/dashboard.json` separate raw events, sanitized Hermes outputs, audit records, Redis status, sensor health, permission state, and controls. |
| Redis Streams should be the live local replay/fan-out bus while SQLite remains durable truth | Matched | Redis stream publisher/consumer/replay/DLQ behavior exists and is tested; the current live gateway path expects Redis, while the no-external-service smoke path remains for isolated verification. |
| SQLite + FTS5 should be durable timeline/audit store | Matched | `SQLiteTimelineStore` and `SQLiteAuditLog` back local timeline, FTS search, and audit records. |
| LanceDB should store derived notes, not raw data | Matched | `LanceDBNoteIndex` stores note records and metadata for retrieval when installed. |
| Neo4j should remain optional | Matched | Workflow pattern lookup falls back to local timeline transitions unless explicitly configured. |
| Browser/page context should use native messaging into the gateway | Matched | `argus-native-host` converts page-context messages to `activity.browser_page` events and posts to loopback `/events`. |
| macOS sensors must be consent-first and visible | Matched for MVP | The macOS app has permission status, pause/resume controls, NSWorkspace/Accessibility event paths, local spooling, gateway sink, and one-shot ScreenCaptureKit/Vision OCR fallback. |
| Full install prompts should be explicit and helpful | Matched in docs | See `docs/hermes-setup.md` for environment setup, MCP add/test prompts, plugin boundary, safe Hermes smoke prompts, browser host prompt, and troubleshooting. |

## Fixed In This Pass

- Replaced stale spec examples that returned `{"block": true, "reason": "..."}`
  with Hermes' current `{"action": "block", "message": "..."}` veto shape.
- Replaced stale `uvx hermes-sensor-mcp` setup language with the verified
  `hermes mcp add argus-sensor --command uv --args run argus-sensor-mcp` flow.
- Added a full Hermes setup guide with expected answers, safe prompts, and the
  plugin environment boundary.
- Updated `deep-research-report.md` so it reflects the fixed Hermes contract,
  current MCP setup, Redis live-stack expectation, dashboard audit split, and
  current macOS sensor maturity.
- Added spec-verifier coverage for the setup and alignment docs so these
  requirements fail fast if removed.

## Intentional Remaining Deltas

These are not placeholders; they are the next functional work items after the
MVP spine:

- A Redis-backed live-stack variant of the full E2E smoke that runs gateway,
  Redis, storage worker, dashboard, native host, MCP raw gating, and forget
  controls together.
- Fresh-install macOS permission verification on a clean machine, including
  Accessibility and Screen Recording prompts.
- Developer ID signing and notarization for a user-installable macOS build.
- Additional P1/P2 collectors such as MailKit, File Provider, DeviceActivity,
  HealthKit, WatchConnectivity, and richer home/device events.
- Full Hermes prompt-level verification that the enabled plugin injects ambient
  context inside a real Hermes session. The MCP path is live-verified today; the
  plugin package contract is tested, but `hermes plugins list` must show `argus`
  in the actual runtime environment before claiming hook enablement.
