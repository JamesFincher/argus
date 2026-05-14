# Best Setup for Injecting Real-World Sensor Context into Hermes Agent with Argus

## Executive summary

The best setup for your use case is a **hybrid local-first architecture**: send all sensor signals into **Argus as normalized local events**, store them in a **local timeline and optional retrieval index**, expose **detail-on-demand through an Argus MCP server**, and inject only a **short redacted ambient summary** into Hermes on each turn through the `pre_llm_call` plugin hook. That matches the strongest official Hermes extension surfaces today: plugin hooks for per-turn context injection, MCP for external tool discovery, and the API server only when you need a UI or an external controller. citeturn13view2turn13view3turn17view0turn13view5turn20view0

That approach is also the one Argus itself is already leaning toward. The Argus spec explicitly recommends **not** stuffing a continuous firehose of sensor notes into the prompt; instead it recommends injecting a short ambient note via `pre_llm_call`, letting Hermes call MCP tools for details, keeping raw evidence referenced by `event_id`, and expanding raw evidence only after a policy gate approves it. The current codebase contains the core pieces for exactly that pattern: a normalized event envelope, a loopback-only event gateway, a local MCP tool surface, a stdio MCP adapter, and a Hermes plugin skeleton. citeturn27view2turn27view3turn40view0turn32view0turn38view0turn28view1

The two most important implementation fixes before you rely on this in the latest Hermes line are compatibility fixes. First, **Argus currently uses the entry-point group `hermes.plugins`**, while the current official Hermes plugin docs use **`hermes_agent.plugins`** for pip-distributed plugins. Second, **Argus returns `{"block": true, "reason": ...}` from `pre_tool_call`**, while Hermes’ documented Python-plugin contract shows the veto shape as **`{"action": "block", "message": ...}`**. I would normalize Argus to the documented Hermes contract instead of assuming backward compatibility. citeturn29view0turn29view1turn15view0turn18view4turn16view2

For your concrete sensor examples, this means:

- **Light switch / home events** should become compact structured Argus events such as `activity.device_state` or `system.external_signal`, stored locally and summarized when relevant.
- **Computer activity** should flow in as `activity.app_focus`, `activity.window_focus`, `activity.focused_field`, and similar typed events.
- **Browser and website activity** should use the existing browser/native-messaging shape Argus already models, because that path is already wired from a page-context message into an `activity.browser_page` event sent to the local gateway.
- **Phone-derived events** should follow the same envelope and same local pipeline, but stay at a higher level unless you are on a platform that legitimately exposes the signal via public APIs. The Argus spec already defines event families for files, browser, health, device usage, reminders, and more, even where the current codebase is still a skeleton. citeturn27view5turn40view5turn40view0turn27view4

## Hermes Agent surfaces that matter for sensor injection

Hermes currently gives you **five distinct extension surfaces** that matter for this problem, and they are not interchangeable.

The most direct path for **ambient context injection** is the general plugin system. Official docs say plugins can be discovered from `~/.hermes/plugins/`, project-local `.hermes/plugins/`, and pip entry points; they can register tools, hooks, slash commands, CLI commands, skills, and context engines. General plugins are opt-in and must be enabled explicitly, which is exactly what you want for potentially privacy-sensitive local sensor integrations. citeturn18view4turn15view3turn15view0turn18view2

The critical hook is `pre_llm_call`. Hermes documents it as the **only** hook whose return value is used to inject context into the current turn’s user message. The docs also show that this hook is the intended mechanism for memory, RAG, guardrails, and any plugin that needs to provide extra context before the model loop begins. Multiple plugins can return context and Hermes joins them together, which means your Argus summary should stay short and deterministic. citeturn16view2turn22view4

For **detail-on-demand**, the cleanest Hermes-supported mechanism is MCP. Hermes supports both **local stdio MCP servers** and **remote HTTP MCP servers**, auto-discovers tools on startup or reload, and lets you include or exclude tools per server. Local stdio servers are the best fit when the integration is local, sensitive, and low latency; remote HTTP MCP is appropriate only if you intentionally want a network boundary. Hermes also supports `headers` for HTTP auth and OAuth 2.1 PKCE for HTTP/StreamableHTTP MCP servers via `auth: oauth`. citeturn13view3turn17view0turn17view1turn17view4turn17view6turn17view7

For **UI or app-driven control**, Hermes has an API server that exposes an OpenAI-compatible HTTP endpoint. `POST /v1/chat/completions` is stateless and expects the full conversation in the `messages` array. `POST /v1/responses` supports server-side conversation state using `previous_response_id`, and the Runs API exposes long-running sessions with SSE progress events and stop/status endpoints. Authentication is via Bearer token in the `Authorization` header, and the docs are explicit that this server exposes Hermes’ full toolset and should stay loopback-bound unless you intentionally open it up. citeturn13view5turn20view0turn20view1turn20view2turn20view3turn20view4

For **event-triggered workflows**, Hermes also ships a webhook adapter. By default, each webhook POST triggers an agent run; with `deliver_only: true`, the adapter skips the agent entirely and directly delivers a templated message. Every route must have a secret, and the adapter validates source-specific signatures or generic HMAC. This is useful when you want external systems to wake Hermes up, but it is a weaker fit than MCP plus a plugin when your core task is “give Hermes ambient private context every turn.” citeturn19view0turn19view1turn19view2turn19view3turn19view4

Finally, Hermes supports **single-select provider plugins** for memory and context engines. Memory providers are for persistent cross-session knowledge. Context engines replace Hermes’ built-in context compressor. These are powerful, but for your current “inject real-world data as context” goal, they are second-stage options, not where I would start. citeturn18view0turn25view0turn24view0

### What this means for real-time and batch ingestion

If you need **real-time ambient context**, use `pre_llm_call` and keep it cheap. If you need **real-time detailed lookup**, use MCP. If you need **scheduled summarization or periodic consolidation**, Hermes cron is the right batch surface. If you need **external systems to trigger agent runs**, use webhooks. If you need a **frontend or controller app**, use the API server. citeturn16view2turn13view3turn13view8turn19view0turn13view5

## What Argus already implements

Argus already has a surprisingly coherent local sensor plane.

At the data-model layer, Argus defines a canonical `EventEnvelope` with an `event_id`, `event_type`, `schema_version`, source metadata, timestamps, optional `session_id` and `dedupe_key`, `sensitivity`, `raw_scope`, `payload`, `redactions`, `relationships`, and `tags`. The spec’s example event families include app/window activity, browser activity, files, speech, calendar, device usage, perception notes, and system events, which is exactly the right shape for your “light switch + computer activity + phone activity + programs + websites” ambition. citeturn27view1turn27view5

At the ingest layer, Argus has a **loopback-only event gateway**. The gateway accepts normalized envelopes on `/events`, stores a local copy, publishes the event to Redis Streams, exposes `/health`, `/dashboard.json`, `/dashboard`, and `/metrics`, and supports operator control routes for pause, resume, forget, and export. It also rejects non-loopback host bindings. citeturn40view0

At the browser edge, Argus has a **native-messaging adapter** that converts a `page_context` message into an `activity.browser_page` event and posts it to the local gateway URL. That path validates that the gateway target is loopback HTTP with a fixed port and the `/events` path, which is an excellent local-security baseline for website/context sensors. citeturn40view5turn40view0

At the transport layer, Argus has **Redis stream routing** with separate raw streams per platform (`macos`, `ios`, `watchos`), plus streams for derived notes, policy-blocked events, system metrics, and a dead-letter queue. It also includes a Redis consumer-group worker that can read those streams and persist them to SQLite. citeturn41view1turn41view0

At the storage and retrieval layer, Argus uses a **SQLite timeline store with FTS5** plus an **audit log**, and it has a retrieval abstraction with an in-memory note index or a LanceDB-backed note index. In the MCP layer, timeline search first consults the note index when available and then searches or scans the timeline store, while workflow-pattern discovery can come either from Neo4j or from local timeline transitions. citeturn32view3turn32view4turn31view6turn38view0

At the Hermes-facing layer, Argus includes both a **local MCP tool surface** and a **Hermes plugin skeleton**. The MCP surface registers tools for recent-note summaries, event expansion, timeline search, workflow-pattern search, scope pause, scope forget, and session-brief export. The stdio adapter implements a minimal MCP-compatible JSON-RPC dispatcher with `initialize`, `tools/list`, and `tools/call`. The Hermes plugin skeleton wires `pre_llm_call` to `sensor_get_recent_notes` and `pre_tool_call` to event-expansion policy checks. citeturn32view0turn32view1turn32view4turn32view5turn38view3turn38view4turn38view5turn28view1turn28view2

### Argus modules mapped to Hermes integration hooks

| Argus file or module | What it does | Hermes integration point | Recommendation |
|---|---|---|---|
| `events.py` | Canonical event envelope and metadata contract | Input schema for all sensors | Keep this as the single sensor contract; do not invent per-sensor one-off payloads. citeturn27view1turn27view5 |
| `event_gateway.py` | Loopback HTTP ingest, local persist, Redis publish, operator controls | Sensor ingress before Hermes sees anything | Make this the one local ingest endpoint for every sensor emitter. citeturn40view0 |
| `native_messaging.py` | Converts browser page context into Argus events and posts to gateway | Browser and website sensors | Reuse this pattern for browser/page sensors; add analogous local emitters for app focus and file events. citeturn40view5turn40view0 |
| `streams.py` | Redis stream routing, consumer-group helpers, DLQ | Optional async bus behind gateway | Keep optional for scale-out; skip initially if a single-machine install is enough. citeturn41view1 |
| `storage_worker.py` | Reads Redis Streams and writes to SQLite | Batch or fan-out persistence | Use only when you want asynchronous workers or multiple downstream processors. citeturn41view0 |
| `sqlite_store.py` | Timeline store, FTS5 search, ambient summaries, audit persistence | Backing store for plugin and MCP tools | Make SQLite the first source of truth for local deployment. citeturn40view4turn32view3 |
| `retrieval.py` | Note index and optional LanceDB-backed search | Rich retrieval behind MCP tools | Use when timeline search becomes too weak or you want semantic lookup. citeturn38view0turn32view3 |
| `graph.py` | Optional Neo4j pattern lookup | `sensor_find_workflow_patterns` backend | Leave optional until workflow-pattern mining matters. citeturn31view6turn38view1 |
| `mcp.py` | Local Argus tool registry and policy-gated lookup | Tool surface consumed by Hermes MCP client | This should remain the authoritative detail-on-demand layer. citeturn32view0turn32view1turn34view0 |
| `mcp_stdio.py` | Minimal stdio MCP adapter with tool schemas | Hermes `mcp_servers.<name>.command` | This is the correct way to expose Argus to Hermes as external tools. citeturn38view0turn38view3turn38view4turn39view0 |
| `hermes_plugin.py` | Ambient context injection and raw-access gating | `pre_llm_call`, `pre_tool_call` | Keep this, but fix compatibility with latest Hermes plugin packaging and veto shape. citeturn28view1turn28view2turn29view0turn15view0turn16view2 |

### Critical compatibility findings

The Argus direction is right, but the latest Hermes docs suggest two changes before you rely on the current plugin path in production.

Argus currently declares `ENTRY_POINT_GROUP = "hermes.plugins"` in `hermes_plugin.py`, while the current official Hermes plugin guide documents pip entry points under `[project.entry-points."hermes_agent.plugins"]`. If you plan to distribute Argus as a pip-installed Hermes plugin, I would change Argus to the documented group name or provide both groups during a transition. citeturn29view0turn15view0turn18view4

Argus also returns `{"block": True, "reason": ...}` from `pre_tool_call`, while the Hermes hook docs document the Python-plugin veto shape as `{"action": "block", "message": ...}`. The safest move is to update Argus to the documented shape rather than bet on undocumented normalization. citeturn28view2turn16view2

## Recommended integration architecture

The recommended design is **not** “inject everything into Hermes.” It is:

- **All sensors** emit typed Argus event envelopes to a **local loopback gateway**.
- Argus writes those events to a **local timeline store** and, only if needed, pushes them through **Redis Streams** for workers.
- Hermes loads an **Argus plugin** that injects only a **short recent ambient summary** via `pre_llm_call`.
- Hermes connects to an **Argus stdio MCP server** for on-demand lookup, redacted event expansion, timeline search, workflow patterns, pause, forget, and session-brief export.
- Raw expansion remains **policy gated**, audited, and keyed by `event_id`. citeturn27view2turn27view3turn40view0turn32view0turn32view1turn34view0turn38view3turn38view4

This is the best fit because it matches all four constraints that matter here.

It is **low-latency**. The pre-turn context injection happens from a local store, not a remote network service. Stdio MCP is also local and avoids an extra HTTP hop. Hermes explicitly recommends stdio MCP when the server is local and you want low-latency access to local resources. citeturn17view0

It is **token-efficient**. Hermes’ documented `pre_llm_call` injection should be used for compact context, while Argus’ own spec says the rolling firehose should stay out of the prompt and detail should come through tools. That combination is exactly how you avoid burying the model in stale or duplicative sensor text. citeturn16view2turn22view4turn27view2turn27view3

It is **privacy-preserving**. Argus already defaults toward local-only, loopback-only, policy-redacted handling, with explicit raw-access approval and auditable tool access. Hermes plugins are opt-in, and MCP filtering lets you expose only the tools you really want the model to see. citeturn40view0turn34view0turn18view4turn17view1turn17view3

It is **aligned with the code you already have**. You would be extending existing Argus structures, not fighting them. citeturn28view1turn32view0turn38view0

```mermaid
flowchart LR
  subgraph Sensors
    B[Browser extension or native host]
    D[Desktop focus and app sensors]
    P[Phone and external device sensors]
    H[Home automation signals]
  end

  subgraph Argus Local Plane
    G[Loopback Event Gateway]
    S[(SQLite timeline and audit)]
    R[(Optional Redis Streams)]
    N[(Optional LanceDB notes)]
    X[Argus MCP stdio server]
    K[Argus Hermes plugin]
  end

  subgraph Hermes
    A[Hermes Agent]
    U[Optional API server or UI]
  end

  B --> G
  D --> G
  P --> G
  H --> G

  G --> S
  G --> R
  S --> N
  S --> X
  N --> X
  S --> K

  K --> A
  X --> A
  A --> U
```

### Why not use only one integration surface

If you use **only `pre_llm_call`**, you will either over-inject context or end up rebuilding retrieval inside the plugin. If you use **only MCP**, Hermes has to remember to ask for ambient context every time and loses the “just know the recent environment” feel. If you use **only the API server**, you force the caller to manage context assembly, which duplicates Hermes’ own plugin and tool infrastructure. The hybrid plugin-plus-MCP approach avoids all three failure modes. citeturn16view2turn13view3turn13view5turn27view2

## Alternative designs and trade-offs

| Design | Latency | Reliability | Security and privacy | Complexity | Scalability | Verdict |
|---|---|---:|---:|---:|---:|---|
| Hermes webhook route only | Good for event-triggered runs | Good if sender retries | Strong route-secret model, but payload text becomes the prompt unless you stay in `deliver_only` mode | Low | Moderate | Good for “wake Hermes up on event”; not ideal for ambient computer context. citeturn19view0turn19view1turn19view2turn19view4 |
| Hermes API server only | Good | Good | Strong if loopback + bearer key; weak if you push too much private context from callers | Low to moderate | High | Good for a UI/controller, not the best core sensor-injection mechanism. citeturn13view5turn20view0turn20view3 |
| Plugin-only | Excellent | Good if local store is stable | Very private, but all logic lands on the hook hot path | Moderate | Low | Good for tiny setups; weak for detail retrieval and history exploration. citeturn16view2turn22view4 |
| MCP-only | Excellent | Good | Strong because the model only asks for details when needed | Moderate | High | Better than plugin-only, but misses passive “ambient summary” behavior. citeturn13view3turn17view0turn17view3 |
| Filesystem drop only | Moderate | High | Strong if files stay local | Low | Low | Fine for prototypes; poor real-time ergonomics and weaker policy enforcement. |
| Message broker centered | Moderate | High | Good if loopback-only or private network | High | Very high | Useful once you have many sensors or workers; overkill for first deployment. citeturn41view0turn41view1 |
| Hybrid local plugin + local MCP + local gateway | Excellent | High | Best overall local privacy posture | Moderate | High | **Recommended.** It matches Hermes’ documented surfaces and Argus’ current architecture. citeturn13view2turn13view3turn27view2turn40view0turn38view0 |

The only design I would seriously consider instead is **a memory-provider plugin** if your long-term goal becomes “persistent cross-session ambient memory managed entirely inside Hermes.” But that is a bigger commitment, memory plugins are single-select, and they are a poor first step when you already have an external local event plane in Argus. citeturn25view0turn18view0

## Implementation blueprint

### Fix the Hermes compatibility edges in Argus first

Before anything else, make two changes in the Argus Hermes plugin package:

```python
# package metadata
[project.entry-points."hermes_agent.plugins"]
argus = "argus_services.hermes_plugin:register"
```

```python
# hook veto return shape
return {"action": "block", "message": decision.reason}
```

That aligns the package with the current official plugin discovery and hook contract. citeturn15view0turn16view2turn29view0

### Normalize all sensors onto the single Argus envelope

Every sensor should emit the Argus envelope and go through the loopback gateway. Do not build separate direct-to-Hermes sensor adapters for browser activity, app focus, light-switch events, and phone summaries. The event gateway already gives you one ingest path, one store, one metrics surface, and one policy boundary. citeturn27view1turn40view0

A good event shape for computer and phone activity looks like this:

```json
{
  "event_type": "activity.app_focus",
  "source_device_id": "macbook-pro",
  "source_platform": "macos",
  "sensor_id": "frontmost_app_sensor",
  "payload": {
    "app": {
      "bundle_id": "com.apple.Safari",
      "name": "Safari"
    },
    "window": {
      "title": "Vendor pricing - Safari"
    },
    "reason": "frontmost_changed"
  },
  "observed_at": "2026-05-13T20:47:18Z",
  "raw_scope": "ephemeral",
  "sensitivity": "low",
  "tags": ["macos", "focus"]
}
```

That style is consistent with the Argus event families and payload examples for app focus, focused field, and browser page activity. citeturn27view5

A simple local emitter looks like this:

```python
import requests

def emit_argus_event(event: dict) -> None:
    r = requests.post("http://127.0.0.1:8765/events", json=event, timeout=2)
    r.raise_for_status()
```

That endpoint and local-gateway flow are already what Argus implements. citeturn40view0

### Keep Redis optional on day one

For a first deployment on one person’s machine, you do not need Redis Streams unless you really want asynchronous workers or fan-out. The gateway already stores locally and already exposes what Hermes needs. Redis and the storage worker become useful when you add perception workers, enrichment, multi-process indexing, or a dead-letter workflow. citeturn40view0turn41view0turn41view1

My recommendation is:

- **Day one**: sensors → gateway → SQLite → plugin/MCP.
- **Later**: turn on Redis Streams and storage/perception workers for fan-out, analytics, or heavier processing. citeturn40view0turn41view0

### Expose Argus to Hermes over stdio MCP

Configure Hermes to treat Argus as a local stdio MCP server. This keeps the detailed retrieval surface outside the prompt and inside a narrow, filterable tool namespace. Hermes supports local stdio MCP servers with `command`, `args`, and `env`, and it lets you filter the tool surface per server. citeturn17view0turn17view1turn17view7

```yaml
# ~/.hermes/config.yaml
mcp_servers:
  argus:
    command: "python"
    args: ["-m", "argus_services.mcp_stdio"]
    env:
      ARGUS_TIMELINE_DB_PATH: "/Users/you/Library/Application Support/Argus/timeline.db"
      ARGUS_LANCEDB_PATH: "/Users/you/Library/Application Support/Argus/lancedb"
      ARGUS_APPROVAL_TOKEN: "replace-with-local-approval-token"
    tools:
      include:
        - sensor_get_recent_notes
        - sensor_expand_event
        - sensor_timeline_search
        - sensor_find_workflow_patterns
        - sensor_pause_scope
        - sensor_forget_scope
        - sensor_export_session_brief
      resources: false
      prompts: false
```

Once configured, Hermes will discover the tools at startup or after `/reload-mcp`. Remember that Hermes prefixes MCP tools with `mcp_<server>_<tool>` when registering them to the model, but include/exclude filters use the original MCP tool names. citeturn17view2turn17view7turn23view0turn38view3turn38view4

### Inject only a compact ambient summary with a Hermes plugin

Your plugin should do one thing on the hot path: ask Argus for the recent redacted summary and return it as a short `context` string. Anything heavier belongs in MCP tools, not the injected prompt. Hermes documents `pre_llm_call` as the context injection hook, and Argus’ own spec recommends precisely this split. citeturn22view4turn27view2turn27view3

```python
# ~/.hermes/plugins/argus/__init__.py
import os
from argus_services.mcp_stdio import local_mcp_server_from_env
from argus_services.policy import RedactionPolicy

def register(ctx):
    server = local_mcp_server_from_env()
    policy = RedactionPolicy(approval_token=os.getenv("ARGUS_APPROVAL_TOKEN"))

    def inject_argus_context(session_id=None, **_):
        result = server.call_tool(
            "sensor_get_recent_notes",
            limit=5,
            actor=session_id or "hermes",
        )
        context = result.get("context")
        if not context:
            return None
        return {"context": context}

    def gate_raw_sensor_access(tool_name=None, args=None, arguments=None, **_):
        params = arguments or args or {}

        # Hermes MCP tool names are prefixed with mcp_<server>_
        if tool_name not in {"sensor_expand_event", "mcp_argus_sensor_expand_event"}:
            return None

        if params.get("raw_mode") != "full":
            return None

        event_id = params.get("event_id")
        if not event_id:
            return {"action": "block", "message": "event_id is required for full raw access"}

        event = server.store.get(event_id)
        if event is None:
            return {"action": "block", "message": "unknown event_id"}

        decision = policy.evaluate_raw_access(
            event,
            approval_token=params.get("approval_token"),
            raw_mode="full",
        )
        if not decision.allowed:
            return {"action": "block", "message": decision.reason}

        return None

    ctx.register_hook("pre_llm_call", inject_argus_context)
    ctx.register_hook("pre_tool_call", gate_raw_sensor_access)
```

That pattern keeps the injection cheap while still preventing accidental raw expansion. It also aligns the veto return value with the documented Hermes hook shape. citeturn16view2turn28view1turn28view2turn34view0

### Use the existing browser path as the template for websites and programs

Argus’ existing browser path is the best concrete template in the repo for your website/program context injectors. A native message carrying `page_context` becomes an `activity.browser_page` event and is posted to the local gateway. Build your app-focus and focused-field sensors exactly the same way: local source → normalized envelope → local gateway. citeturn40view5turn40view0turn27view5

### Sequence of data flow

```mermaid
sequenceDiagram
  participant Sensor as Local sensor
  participant Gateway as Argus event gateway
  participant Store as SQLite timeline
  participant MCP as Argus MCP stdio server
  participant Plugin as Hermes Argus plugin
  participant Hermes as Hermes Agent

  Sensor->>Gateway: POST /events with EventEnvelope
  Gateway->>Store: persist event
  Gateway-->>Sensor: 202 accepted with event_id

  Hermes->>Plugin: pre_llm_call
  Plugin->>Store: get recent redacted summary
  Plugin-->>Hermes: {"context": "...ambient summary..."}

  Hermes->>MCP: tools/call sensor_timeline_search or sensor_expand_event
  MCP->>Store: search or fetch event
  Store-->>MCP: redacted result or raw-gated event
  MCP-->>Hermes: tool result

  Hermes->>Plugin: pre_tool_call before raw expansion
  Plugin-->>Hermes: allow or block
```

## Security, privacy, testing, and deployment

### Security and privacy considerations

The strongest part of the current design is that both Hermes and Argus already support a local-only security posture. Hermes’ API server defaults to `127.0.0.1`, and the docs warn that exposing it gives access to Hermes’ full toolset. Argus’ event gateway rejects non-loopback bindings, and the browser/native-messaging path validates a loopback-only gateway URL. Keep that default. citeturn13view5turn40view0turn40view5

Argus already gives you the right privacy primitives for sensor data: event-level `sensitivity`, `raw_scope`, deterministic redaction, blocked surfaces, approval-token-gated raw access, and audit logging around tool access and purges. Use them aggressively. In practice that means: store enough structure to retrieve by `event_id`, but only inject summaries into Hermes; keep raw payloads either ephemeral or explicitly durable-by-policy; and make full expansion rare, audited, and user-approvable. citeturn27view1turn34view0turn32view1turn32view2turn33view3

One subtle but important security point is tool exposure. Hermes’ MCP docs strongly emphasize per-server filtering and “the smallest useful surface.” Do that here. Give Hermes the search, summary, expand, pause, forget, and brief-export tools, but do not expose anything broader than necessary. citeturn17view1turn17view3

### Error-handling patterns

Use a small number of predictable failure modes.

At ingest time, if the gateway returns a pause-related error or policy-rejection behavior, the sensor should **drop or buffer locally** and record the reason instead of retrying blindly. The gateway already supports pause and forget controls and returns structured JSON. citeturn40view0

At plugin time, `pre_llm_call` should **fail open** and return `None` if Argus is unavailable, so Hermes can still answer normally. That follows Hermes’ hook model and avoids bricking the whole turn because the ambient-context helper failed. citeturn16view2turn22view4

At MCP-tool time, error results should remain structured and narrow. Argus already returns explicit results for missing events, denied raw access, and redacted versus full modes in `sensor_expand_event`. Keep that pattern. citeturn34view0

### Testing and validation plan

Use three layers of validation.

First, test the **sensor contract**: every sensor should produce valid `EventEnvelope` objects with stable `dedupe_key`, correct `source_platform`, and the right `event_type` family. Second, test the **privacy contract**: blocked surfaces stay blocked, raw expansions require approval, and redacted summaries never leak tokens or secrets. Third, test the **Hermes contract**: the plugin injects context in the documented shape, the MCP server enumerates tools correctly, and a Hermes session can use those tools after discovery or `/reload-mcp`. citeturn27view1turn34view0turn38view3turn17view2

A practical validation sequence is:

- emit a known browser page event;
- verify it appears in SQLite;
- call the Argus MCP `sensor_get_recent_notes`;
- start Hermes and confirm `pre_llm_call` adds a short ambient summary;
- ask Hermes something like “what have I been working on recently?” and confirm it answers from injected summary;
- then ask Hermes to show details and confirm it reaches for the MCP search/expand tools rather than inventing them. citeturn32view1turn32view3turn13view4

### Deployment checklist

Use this as the minimum deployment baseline:

- Bind **Argus gateway**, **Redis** if enabled, and **Hermes API server** to loopback only. citeturn40view0turn13view5
- Put sensor data into **one normalized envelope** and **one local ingress endpoint**. citeturn27view1turn40view0
- Expose Argus to Hermes as a **local stdio MCP server** with a filtered tool list. citeturn17view0turn17view1turn38view3
- Inject only a **short redacted summary** through `pre_llm_call`. citeturn16view2turn27view2
- Make **raw expansion** explicitly gated and audited. citeturn34view0turn32view2
- Fix the **plugin entry-point group** and **pre_tool_call veto shape** to match current Hermes docs. citeturn29view0turn15view0turn16view2
- Keep Redis, LanceDB, and Neo4j **optional** until you actually need fan-out, semantic retrieval, or graph mining. citeturn41view0turn38view0turn31view6

## Open questions and limitations

There are two limitations worth calling out clearly.

The first is **Hermes version labeling**. In the official repo surfaces I reviewed, the repository page and the releases page appear to show inconsistent version labels around the March 28, 2026 stable line, while the docs site itself has pages updated through late April and early May 2026. Because of that, I treated the **current official docs site and current official repo docs** as the operative contract for extension surfaces, rather than trusting a single version label at face value. citeturn0search0turn21search0turn14search6turn14search10

The second is **Argus completeness**. The repo already has the right architectural spine for Hermes integration, but some parts are more mature than others. The browser/native-messaging path, event gateway, SQLite store, MCP surface, and Hermes plugin skeleton are concrete; the broader cross-device perception pipeline described in the spec is still more aspirational than fully surfaced in the code paths I inspected. That does not weaken the recommended architecture; it just means you should treat “sensor collectors” as the area that still needs the most build-out. citeturn27view4turn8view0turn40view0turn38view0turn28view1