# Argus Spec Checklist

Use this as the delivery checklist for turning `argus_spec.md` into verifiable work. A task is not complete until its artifact exists and its listed test gate passes.

## Spec Harness

| Deliverable | Required artifact | Test gate |
| --- | --- | --- |
| Argus naming plan | `docs/implementation-plan.md` | Argus Core, Argus Sensor, Argus Mesh, and ArgusOS are mapped to spec responsibilities. |
| Checklist | `docs/spec-checklist.md` | Checklist includes concrete deliverables and test gates. |
| Verifier | `scripts/verify_spec.py` | `python3 scripts/verify_spec.py` exits 0 when required scaffold exists. |
| Verifier tests | `tests/spec/test_verify_spec.py` | `python3 -m pytest tests/spec` passes. |

## Argus Sensor

| Deliverable | Required artifact | Test gate |
| --- | --- | --- |
| macOS sensor module | app target or module for NSWorkspace, Accessibility, Safari Web Extension, ScreenCaptureKit, Vision | Permission-state test proves no collection starts before explicit authorization. |
| iOS sensor module | app plus Share Extension, Safari Web Extension, App Intents, BackgroundTasks, optional DeviceActivity | Test proves iOS collection is user-invoked or system-scheduled, not a universal observer. |
| watchOS sensor module | watch app for HealthKit summaries, controls, annotations, WatchConnectivity | Test proves only aggregate/consented data syncs to the phone/Core. |
| Permission events | `system.permission_state` schema and emitter | Permission sequencing test covers notifications, Accessibility, Screen Recording, Speech, EventKit, HealthKit, Safari/Mail extensions, and optional entitlements. |
| Sensor heartbeat | `system.sensor_heartbeat` schema and emitter | Health test fails when a sensor stops reporting within its configured interval. |

## Argus Core

| Deliverable | Required artifact | Test gate |
| --- | --- | --- |
| Base event envelope | schema containing `event_id`, `event_type`, `schema_version`, `source_device_id`, `source_platform`, `sensor_id`, `observed_at`, `ingested_at`, `dedupe_key`, `sensitivity`, `raw_scope`, `payload`, `redactions`, `relationships`, and `tags` | Contract tests reject missing fields, invalid sensitivity values, invalid raw scopes, and non-sortable IDs. |
| Event families | schemas for activity, browser, screen/OCR, speech/audio, email, calendar/reminders, files, health/device usage, derived/perception, and system events | Schema tests validate every event type listed in the spec. |
| Canonicalizer | precedence rules for overlapping signals | Tests prove browser extension beats OCR, AX focused field beats OCR, MailKit beats screen email guesses, EventKit beats calendar OCR, and HealthKit aggregate beats watch UI text. |
| Perception worker | normalize, dedupe, secret scan, PII scan, classify, paraphrase, embed, policy gate | Pipeline order test proves rules run before model-generated summaries. |
| Policy gate | block/redact/allow decision engine | Regression tests block passwords, OTP codes, bearer tokens, API keys, private keys, cookies, banking/password-manager/payroll surfaces, and raw health free text by default. |
| Derived notes | constrained paraphrase templates and evidence links | Tests prove summaries include evidence event IDs and never include blocked raw fields. |
| Audit log | egress records for agent/tool access | Tests prove every MCP or plugin-facing raw expansion records actor, scope, count, and redactions. |

## Argus Mesh

| Deliverable | Required artifact | Test gate |
| --- | --- | --- |
| Redis Streams bus | streams for raw macOS/iOS/watchOS events, derived notes, policy blocks, metrics, and DLQ | Redis replay test covers XADD, XREADGROUP, ack, reclaim, max attempts, and DLQ routing. |
| Timeline store | SQLite + FTS5 migrations for events and audit records | Migration test creates, upgrades, rolls back if supported, and runs a timeline query. |
| Embedding store | LanceDB schema for notes/chunks with metadata | Retrieval test returns top notes without exposing blocked raw payloads. |
| Optional graph | Neo4j schema for User, Event, App, Window, Page, File, Concept, Note and relationships | Feature-flag test proves graph can be disabled without breaking Core. |
| Purge path | forget action across SQLite, LanceDB, Neo4j, retained blobs, and tombstone index | Purge test proves matching app/domain/project data is removed or tombstoned consistently. |
| Observability | metrics for lag, pending count, reclaim count, p95 latency, blocked rate, redaction hit rate, bytes per sensor | Monitoring test proves metrics endpoint is localhost-only. |

## ArgusOS

| Deliverable | Required artifact | Test gate |
| --- | --- | --- |
| Local service control | login item, LaunchAgent, or platform-appropriate background registration | Startup test proves services bind only to loopback and expose health. |
| Operator controls | pause, resume, forget, export, permission status | UI/API test proves pause stops raw collection and forget triggers purge. |
| Secrets handling | Keychain-backed storage for tokens, API keys, encryption keys | Test proves secrets are not persisted in config files, logs, or container layers. |
| Packaging | signed/notarized macOS distribution path plus extension packaging | Packaging test verifies entitlements and bundled extensions. |
| Safety posture | visible, pausable, auditable operation | E2E test proves sensitive surfaces emit only a policy heartbeat or sanitized note. |

## Agent Integration

| Deliverable | Required artifact | Test gate |
| --- | --- | --- |
| MCP server | local tools for timeline search, recent notes, event expansion, workflow patterns, pause scope, forget scope, export brief | MCP discovery test proves tools are visible to the downstream agent. |
| Policy-checked expansion | raw fetch tool guarded by policy and audit | Test proves blocked scopes cannot be expanded even through tools. |
| Optional adapter hooks | concise ambient context and pre-tool policy enforcement for downstream agents | Test proves the injected context is short, sanitized, and retrievable rather than a raw firehose. |

## Release Gates

Every release should pass:

- schema migration test
- redaction regression suite
- extension packaging test
- MCP discovery test
- Redis replay test
- localhost bind test
- storage purge test
- one end-to-end sensitive-surface suppression test
