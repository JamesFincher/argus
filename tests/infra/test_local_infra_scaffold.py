import json
import re
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


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_compose_publishes_services_on_loopback_only():
    compose = read("infra/compose.yaml")
    ports = re.findall(r'"([^"]+:\d+:\d+)"', compose)

    assert "127.0.0.1:6379:6379" in ports
    assert "127.0.0.1:7474:7474" in ports
    assert "127.0.0.1:7687:7687" in ports
    assert "127.0.0.1:9090:9090" in ports
    assert "127.0.0.1:3000:3000" in ports
    assert all(port.startswith("127.0.0.1:") for port in ports)


def test_redis_accepts_host_gateway_connections_only_because_loopback_bound():
    compose = read("infra/compose.yaml")

    assert "--protected-mode\n      - \"no\"" in compose
    assert "127.0.0.1:6379:6379" in compose


def test_redis_stream_manifest_matches_spec_names():
    manifest = json.loads(read("infra/redis/streams.json"))
    streams = manifest["streams"]
    names = {stream["name"] for stream in streams}
    groups = {
        group
        for stream in streams
        for group in stream["consumer_groups"]
    }

    assert REQUIRED_STREAMS <= names
    assert REQUIRED_GROUPS <= groups


def test_storage_skeletons_include_timeline_search_and_graph_names():
    sqlite = read("storage/sqlite/migrations/001_timeline_fts5.sql")
    cypher = read("storage/neo4j/schema.cypher")

    assert "CREATE TABLE IF NOT EXISTS events" in sqlite
    assert "CREATE VIRTUAL TABLE IF NOT EXISTS event_fts USING fts5" in sqlite
    assert "dedupe_key" in sqlite
    assert "semantic_scope" in sqlite
    assert "CREATE CONSTRAINT event_id_unique" in cypher
    assert ":FOLLOWED_BY" in cypher


def test_prometheus_scrapes_local_stack_targets():
    prometheus = read("infra/prometheus/prometheus.yml")

    assert "redis-exporter:9121" in prometheus
    assert "prometheus:9090" in prometheus
