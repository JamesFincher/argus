# Argus Implementation Plan

This plan translates `argus_spec.md` into the Argus product naming used for implementation. The spec currently uses "Hermes Sensor System" language; in this repository, Argus owns the sensor system and Hermes is treated as one possible downstream agent integration target.

## Naming Map

| Argus name | Spec language | Implementation responsibility |
| --- | --- | --- |
| Argus Core | event gateway, canonicalizer, perception worker, policy gate, MCP server, plugin hooks | Local data plane that accepts events, deduplicates them, redacts sensitive data, writes durable stores, and exposes retrieval tools. |
| Argus Sensor | macOS app and helpers, iOS app and extensions, watchOS app | User-approved platform collectors that produce normalized event envelopes. |
| Argus Mesh | Redis Streams, SQLite + FTS5, LanceDB, optional Neo4j, monitoring | Local-first transport, storage, retrieval, graph, and observability fabric. |
| ArgusOS | login/background registration, permission controls, pause/forget controls, packaging, localhost service policy | Host-level runtime and operator surface that keeps sensing visible, auditable, permissioned, and locally bound. |
| Hermes integration | Hermes MCP client, Hermes plugin, Hermes API | External agent adapter. Argus should expose policy-checked summaries and tools without making Hermes the owner of the data plane. |

## Architecture Boundaries

Argus Sensor is the only layer allowed to interact directly with Apple platform APIs such as ScreenCaptureKit, Accessibility, NSWorkspace, Vision, Speech, EventKit, MailKit, Safari Web Extensions, File Provider, FSEvents, HealthKit, DeviceActivity, BackgroundTasks, App Intents, and WatchConnectivity.

Argus Core owns the base event envelope, schema validation, canonicalization precedence, redaction, policy decisions, derived notes, MCP tools, and adapter hooks. Raw observations enter Core through the local event gateway and should not bypass the policy gate.

Argus Mesh owns the local persistence split from the spec: Redis Streams for short-lived fan-in, SQLite + FTS5 for the timeline and audit trail, LanceDB for embeddings, and Neo4j only when graph-native traversal is needed. Mesh services must bind to loopback by default.

ArgusOS owns startup, permission sequencing, sensor toggles, pause/resume, forget/purge, local notifications, signing/notarization readiness, service health, and operator-visible status. ArgusOS must not add hidden capture modes or bypass platform prompts.

## Phased Build Plan

### Phase 0: Spec Harness

Deliver the bounded verification scaffold in this repository:

- `docs/implementation-plan.md`
- `docs/spec-checklist.md`
- `scripts/verify_spec.py`
- `tests/spec/`

Gate: `python3 scripts/verify_spec.py` reports all required scaffold files present.

### Phase 1: Core Contracts

Define the base event envelope and first event-family schemas from the spec:

- activity events: app/window focus, focused field, browser page/selection/download, screen OCR
- communication events: mail metadata/compose/action, voice note, speech transcript
- personal context events: calendar/reminder, file change/open/sync, health summary, device activity, watch annotation
- derived events: perception note, entity link, workflow edge, policy block
- system events: permission state, heartbeat, error, dead letter

Gates:

- schema migration test
- event envelope contract tests
- canonicalizer precedence tests for browser-over-OCR, AX-over-OCR, MailKit-over-screen, EventKit-over-OCR, and HealthKit-over-watch-UI

### Phase 2: Sensor MVP

Implement macOS-first collection using public APIs and explicit permissions:

- NSWorkspace frontmost app and window events
- Accessibility focused window and focused field snapshots
- Safari Web Extension page context
- ScreenCaptureKit plus Vision OCR as fallback, not primary signal
- staged permission status events and user-visible pause control

Gates:

- no sensor starts before the corresponding permission state is known
- sensitive app/domain denylist suppresses raw propagation
- extension packaging test
- one end-to-end "sensitive surface suppressed" test

### Phase 3: Mesh MVP

Stand up local-only transport and storage:

- Redis Streams keys from the spec: `stream:raw:*`, `stream:derived:notes`, `stream:policy:blocked`, `stream:system:metrics`, `stream:dlq`
- SQLite + FTS5 timeline and audit tables
- LanceDB note embedding store
- optional Neo4j graph path behind a feature flag

Gates:

- Redis replay test
- stream dead-letter test
- storage purge test for forget actions
- localhost bind test for every local service

### Phase 4: Core Perception and Policy

Implement rules-first processing:

- deterministic secret and PII scanners before any model step
- sensitivity scoring and escalation
- constrained paraphrase templates
- derived note emission
- policy audit for every downstream egress

Gates:

- redaction regression suite
- blocked-output tests for passwords, tokens, OTP codes, cookies, private keys, bank/payroll/password-manager surfaces, and raw health text
- allowed-output tests for sanitized summaries, app/window names, safe domains, calendar semantics, mail metadata summaries, DeviceActivity aggregates, HealthKit aggregates, and retrieval snippets

### Phase 5: Agent Integration

Expose Argus Core through a local MCP server first, then optional adapter hooks:

- `sensor_timeline_search`
- `sensor_get_recent_notes`
- `sensor_expand_event`
- `sensor_find_workflow_patterns`
- `sensor_pause_scope`
- `sensor_forget_scope`
- `sensor_export_session_brief`

Gates:

- MCP discovery test
- policy gate test for raw event expansion
- concise ambient-summary injection test
- audit log test for every agent-facing call

## Non-Goals

Argus must not implement hidden keylogging, silent permission bypass, raw third-party message database scraping, or always-running invisible iOS/watchOS daemons. The product should remain local-first, consent-first, visible, pausable, auditable, and policy-gated.
