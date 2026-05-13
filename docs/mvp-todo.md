# Argus MVP TODO

This backlog is the working definition of "MVP" for Argus. An item is not done
because a file exists; it is done only when the implementation works locally,
has tests or a repeatable verification command, and does not depend on pseudo
features or placeholder functions.

## MVP Definition

Argus MVP is a local-only macOS sensor system that can:

1. Collect user-approved macOS context from real sensors.
2. Normalize events into the canonical Argus envelope.
3. Store raw local data and a full audit trail locally.
4. Redact, canonicalize, and expose only sanitized summaries to Hermes by default.
5. Allow Hermes to retrieve details through policy-checked tools.
6. Provide visible operator controls for pause, resume, forget, export, and health.
7. Install and run repeatably on macOS without hidden capture behavior.

## Current Functional Baseline

Done:

- Python service modules have full production-module test coverage.
- Event gateway accepts canonical envelopes on loopback and publishes Redis Streams.
- SQLite + FTS5 timeline/audit storage is functional.
- Redis stream publisher/consumer/replay/dead-letter behavior is tested.
- Dashboard shows raw events, sanitized Hermes outputs, audit trail, Redis status,
  permissions, heartbeats, pause/resume/forget/export controls.
- Policy gate redacts or blocks common sensitive material.
- Perception worker emits derived notes and now canonicalizes overlapping signals.
- MCP-style in-process tool surface exposes required sensor tools.
- MCP stdio transport exposes the same tool surface through console scripts:
  `argus-mcp-stdio`, `argus-sensor-mcp`, and `hermes-sensor-mcp`.
- Hermes plugin entry point is packaged under `hermes.plugins`, uses env-backed
  local stores by default, and enforces pre-LLM/pre-tool policies in tests.
- Swift Argus Core has canonical gateway envelope, UUIDv7 IDs, privacy filtering,
  local buffer/spool, loopback gateway sink, permission models, and OCR policy.
- macOS app can manually capture frontmost window/focused-field events when
  permissions are available.
- macOS app now starts a visible active runtime loop with heartbeat emission,
  periodic structural snapshots, pause shutdown, and sink error events.
- Native messaging host converts Safari/WebExtension `page_context` messages into
  canonical browser-page events and posts them to the loopback gateway.
- Native messaging manifest install/uninstall tooling writes per-user
  Chromium-family manifests for packaged `argus-native-host` executables.
- `argus-mvp-smoke` verifies native messaging, loopback gateway, SQLite
  raw/audit storage, perception notes, and MCP stdio raw-access gating together.
- ScreenCaptureKit + Vision OCR fallback captures a single screen frame, filters
  low-confidence text, and emits redacted `activity.screen_frame_ocr` events.
- Local macOS packaging produces `dist/Argus Sensor.app` and a DMG with the
  native messaging installer, packaged `argus-native-host` wrapper, service
  modules, browser extension scaffold, and signing-ready entitlements.
- Live Hermes/Gengar verification now checks Argus MCP stdio tools, raw-access
  blocking, and `hermes mcp add/test` against an isolated Hermes home.

Not yet MVP:

- Developer ID signing and notarization on a release certificate.
- Manual fresh-install macOS permission verification for Screen Recording,
  Accessibility, and packaged browser native messaging.
- Redis-backed live-stack variant of the full E2E smoke.

## P0: Hermes Tool Transport

Owner: parallel worker.

Goal: Hermes can launch an Argus MCP server process and call tools without
embedding Python objects in-process.

Status: implemented with live Hermes/Gengar MCP add/test verification.

Tasks:

- Add console scripts: `argus-mcp-stdio`, `argus-sensor-mcp`, and
  `hermes-sensor-mcp`.
- Implement JSON-RPC stdio handling for:
  - `initialize`
  - `tools/list`
  - `tools/call`
  - clean error responses for invalid JSON, unknown methods, and unknown tools.
- Expose JSON schemas for:
  - `sensor_get_recent_notes`
  - `sensor_timeline_search`
  - `sensor_expand_event`
  - `sensor_find_workflow_patterns`
  - `sensor_pause_scope`
  - `sensor_forget_scope`
  - `sensor_export_session_brief`
- Wire the server to persistent local stores from environment variables:
  - `ARGUS_TIMELINE_DB_PATH`
  - optional LanceDB path
  - optional Neo4j feature flag
- Add tests for request/response frames and tool calls.
- Add README instructions for Hermes config.

Done when:

- `uv run argus-sensor-mcp` can serve one JSON-RPC tool-list and tool-call flow.
- Tests verify schemas and policy-gated raw expansion.
- No MCP behavior is only represented by `LocalMCPServer` unit calls.

## P0: Hermes Plugin Packaging

Owner: local/integration after MCP worker.

Goal: Hermes can discover the plugin through package metadata.

Status: implemented for package metadata and env-backed local store wiring; the
live verifier now checks package entry points before launching Hermes MCP tests.

Tasks:

- Add a `hermes_agent.plugins` entry point if Hermes expects that group.
- Add a safe plugin config path for approval token and store paths.
- Ensure `register(ctx)` uses the same persistent store wiring as MCP.
- Add tests that inspect package metadata or exported entry points.
- Document install and rollback commands.

Done when:

- A local install exposes the Argus plugin entry point.
- `pre_llm_call` uses persisted sensor notes, not an empty in-memory store.
- `pre_tool_call` blocks unsafe tool args and gated raw expansion in integration tests.

## P0: Safari Native Messaging Bridge

Owner: parallel worker.

Goal: Safari/WebExtension page context becomes real `activity.browser_page`
events in Argus Core.

Status: host, manifest installer, and tests are implemented for the local
Chromium-family native messaging path. Safari App Extension packaging remains
part of the broader macOS packaging work.

Tasks:

- Implement native messaging stdin/stdout frame handling.
- Validate incoming payloads:
  - `type == "page_context"`
  - `href` is HTTP/HTTPS
  - `domain` is present or derived from URL
  - `title` and `selection` are strings or empty.
- Convert page context to canonical Argus gateway envelope:
  - `event_type = activity.browser_page`
  - `source_platform = macos`
  - `sensor_id = safari_webext`
  - include URL, domain, title, selection text, browser name.
- POST to `http://127.0.0.1:8765/events` by default.
- Reject non-loopback gateway URLs.
- Return success/error response to the browser extension.
- Add native-host manifest/install script for local macOS.
- Add tests for frame parsing, event conversion, and loopback validation.

Done when:

- A framed `page_context` message produces an event accepted by the event gateway.
- Browser context is higher precedence than OCR through canonicalizer tests.
- No native messaging code is just a README placeholder.

## P0: Continuous macOS Sensor Runtime

Owner: local thread unless another worker slot opens.

Goal: The macOS app runs like a visible sensor, not only a manual snapshot tool.

Status: visible runtime and injected runtime tests are implemented. Live app
verification remains.

Tasks:

- Add heartbeat emission while active:
  - `event_type = system.sensor_heartbeat`
  - `sensor_id = argus-sensor-mac`
  - status, interval, current mode, sink status.
- Add an active polling/timer loop for structural signals:
  - frontmost window capture
  - focused field capture
  - no collection while paused.
- Add sink error reporting:
  - failed gateway/spool writes update dashboard status
  - emit `system.error` when possible.
- Keep permission gating strict:
  - no AX collection before Accessibility trust
  - no OCR fallback before consent and Screen Recording permission.
- Make dependencies injectable enough to test active/pause behavior.
- Add Swift tests or a small Core-level runtime model test where target visibility allows.

Done when:

- Running the app and pressing Resume starts heartbeats and periodic captures.
- Pressing Pause stops timers/sensors and emits a pause control event.
- Sink errors are visible, not swallowed with `try?`.

## P0: Real Screen OCR

Owner: local thread after runtime loop.

Goal: OCR fallback produces redacted `activity.screen_frame_ocr` events from real frames.

Status: implemented with a one-shot ScreenCaptureKit capture path, Vision text
recognition, confidence filtering, and Swift unit coverage for normalization and
redaction. Fresh-install permission behavior still needs manual macOS runtime
verification.

Tasks:

- Replace empty-observation skeleton with a real ScreenCaptureKit frame path.
- Keep `capturesAudio = false`.
- Feed sampled frames into `VNRecognizeTextRequest`.
- Build `ScreenOCRTextObservation` records with confidence.
- Redact before summary and before gateway emission.
- Rate-limit by `ScreenOCRPolicy.minimumFrameInterval`.
- Do not run OCR when AX/browser signals cover the same scope.
- Add a testable seam for Vision observations so policy/redaction can be verified
  without requiring live screen capture in unit tests.

Done when:

- With consent + Screen Recording and no structural signal, OCR can produce a
  redacted event.
- Sensitive OCR text is not stored or emitted unredacted.

## P1: Packaging And Install

Goal: A user can install and run the MVP repeatedly on macOS.

Status: local unsigned app and DMG packaging implemented. Developer ID signing
and notarization are ready through environment inputs but still require real
release credentials.

Tasks:

- Extend packaging to include:
  - Safari extension assets
  - native messaging host and manifest
  - LaunchAgent plist assets
  - app entitlements
  - versioned app metadata.
- Add local install/uninstall scripts.
- Add optional DMG packaging.
- Add code signing/notarization inputs, with unsigned local mode still supported.
- Add a packaging verification test that checks app bundle contents and plists.

Done when:

- `scripts/dev/package_macos_app.sh` produces a runnable app bundle with required
  local MVP assets.
- Install script can register background services and native messaging host.

## P1: Full Local E2E

Goal: Prove the whole MVP path works locally.

Status: `argus-mvp-smoke` now verifies the core local path without external
services. A Redis-backed live-stack variant remains.

Tasks:

- Start Redis, event gateway, storage worker.
- Send a Safari native-message page context.
- Verify event gateway stores raw event and dashboard shows raw/audit rows.
- Run perception/canonicalizer path and produce a sanitized note.
- Query through MCP stdio for recent notes and timeline search.
- Attempt raw expansion without approval and verify it is blocked/audited.
- Approve raw expansion for a known low-risk event and verify audit record.
- Run forget scope and verify SQLite/audit/LanceDB/graph counts.

Done when:

- One command or documented script runs the flow and fails on any broken step.

## P1: Hermes Live Verification

Goal: Actual Hermes sees Argus tools and uses sanitized context.

Status: implemented with `scripts/verify_hermes_runtime.py`; the verifier writes
a local MCP config snippet, validates Argus package metadata, runs the Argus
MCP stdio smoke, and exercises `hermes mcp add/test` in an isolated home.

Tasks:

- Install Argus package into the active Python environment.
- Write Hermes MCP config for `argus-sensor-mcp`.
- Register plugin entry point.
- Launch Hermes with Argus config.
- Verify tool discovery.
- Verify a simple Hermes prompt can call `sensor_get_recent_notes`.
- Verify `sensor_expand_event` full raw mode is blocked without approval.

Done when:

- A documented command sequence proves the live Hermes integration on this Mac.

## P2: Additional macOS Sensors

Tasks:

- MailKit extension implementation for Apple Mail metadata/compose/action.
- EventKit calendar/reminder collector.
- FSEvents watched-folder collector.
- File Provider extension MVP.
- Optional Endpoint Security collector behind entitlement/feature flag.
- Optional Speech/microphone voice note collector.

Done when:

- Each collector has permission gating, event schema tests, and redaction tests.

## P2: Operational Hardening

Tasks:

- Add retention controls for raw buffers.
- Add backup/export format for SQLite timeline and audit records.
- Add Grafana dashboard JSON.
- Add real p95 latency, stream lag, pending count, and MCP tool-call metrics.
- Add upgrade/migration smoke tests.
- Add crash recovery tests for worker restart and Redis pending reclaim.

Done when:

- A failed worker can restart and continue without losing or duplicating stored
  events beyond documented Redis delivery semantics.
