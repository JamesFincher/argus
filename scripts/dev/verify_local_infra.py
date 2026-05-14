#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

REQUIRED_STREAMS = {
    "stream:raw:macos",
    "stream:raw:ios",
    "stream:raw:watchos",
    "stream:derived:notes",
    "stream:policy:blocked",
    "stream:system:metrics",
    "stream:dlq",
}

REQUIRED_GROUPS = {
    "cg-perception",
    "cg-storage",
    "cg-hermes",
    "cg-audit",
    "cg-monitoring",
    "cg-ops",
}

REQUIRED_RETENTION = {
    "stream:raw:macos": "24h",
    "stream:raw:ios": "24h",
    "stream:raw:watchos": "24h",
    "stream:derived:notes": "30d",
    "stream:policy:blocked": "30d",
    "stream:system:metrics": "7d",
    "stream:dlq": "30d",
}

REQUIRED_STORAGE_MARKERS = {
    "events",
    "event_fts",
    "Event",
    "Concept",
}


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def check_loopback_ports(compose_text: str) -> list[str]:
    failures: list[str] = []
    for match in re.finditer(r'"([^"]+:\d+:\d+)"', compose_text):
        mapping = match.group(1)
        if not mapping.startswith("127.0.0.1:"):
            failures.append(f"port mapping is not loopback-only: {mapping}")
    return failures


def check_stream_manifest() -> list[str]:
    manifest = json.loads(read("infra/redis/streams.json"))
    streams = manifest.get("streams", [])
    names = {stream.get("name") for stream in streams}
    groups = {
        group
        for stream in streams
        for group in stream.get("consumer_groups", [])
    }

    failures = [
        f"missing Redis stream: {name}"
        for name in sorted(REQUIRED_STREAMS - names)
    ]
    failures.extend(
        f"missing Redis consumer group: {group}"
        for group in sorted(REQUIRED_GROUPS - groups)
    )
    retention = {
        stream.get("name"): stream.get("retention")
        for stream in streams
        if stream.get("name")
    }
    failures.extend(
        f"Redis stream {name} retention is {retention.get(name)!r}, expected {expected!r}"
        for name, expected in sorted(REQUIRED_RETENTION.items())
        if retention.get(name) != expected
    )
    return failures


def run_checks() -> list[str]:
    compose_text = read("infra/compose.yaml")
    sqlite_text = read("storage/sqlite/migrations/001_timeline_fts5.sql")
    neo4j_text = read("storage/neo4j/schema.cypher")

    failures = check_loopback_ports(compose_text)
    failures.extend(check_stream_manifest())

    storage_text = f"{sqlite_text}\n{neo4j_text}"
    for marker in sorted(REQUIRED_STORAGE_MARKERS):
        if marker not in storage_text:
            failures.append(f"missing storage marker: {marker}")

    if "redis-exporter:9121" not in read("infra/prometheus/prometheus.yml"):
        failures.append("Prometheus is not scraping redis-exporter")

    return failures


def main() -> int:
    failures = run_checks()
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1

    print("Argus local infra scaffold checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
