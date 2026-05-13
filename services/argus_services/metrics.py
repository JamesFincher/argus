"""Prometheus text-format metric names for Argus local services."""

from __future__ import annotations

from dataclasses import dataclass, field


METRIC_TYPES = {
    "events_ingested_total": "counter",
    "redactions_applied_total": "counter",
    "mcp_tool_calls_total": "counter",
    "policy_blocks_total": "counter",
    "sensor_bytes_written_total": "counter",
    "redis_stream_pending": "gauge",
    "redis_stream_lag": "gauge",
    "worker_latency_p95_ms": "gauge",
    "blocked_event_rate": "gauge",
    "redaction_hit_rate": "gauge",
}

METRIC_NAMES = set(METRIC_TYPES)


@dataclass
class MetricsRegistry:
    values: dict[str, float] = field(default_factory=lambda: {name: 0 for name in METRIC_NAMES})

    def increment(self, name: str, amount: int = 1) -> None:
        if name not in METRIC_NAMES:
            raise KeyError(f"unknown metric: {name}")
        self.values[name] += amount

    def set_gauge(self, name: str, value: float) -> None:
        if name not in METRIC_NAMES:
            raise KeyError(f"unknown metric: {name}")
        if METRIC_TYPES[name] != "gauge":
            raise ValueError(f"metric is not a gauge: {name}")
        self.values[name] = value

    def render_prometheus(self) -> str:
        lines: list[str] = []
        for name in sorted(self.values):
            lines.append(f"# TYPE argus_{name} {METRIC_TYPES[name]}")
            lines.append(f"argus_{name} {format_metric_value(self.values[name])}")
        return "\n".join(lines) + "\n"


def format_metric_value(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)
