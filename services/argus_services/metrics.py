"""Prometheus text-format metric names for Argus local services."""

from __future__ import annotations

from dataclasses import dataclass, field


METRIC_NAMES = {
    "events_ingested_total",
    "redactions_applied_total",
    "mcp_tool_calls_total",
    "policy_blocks_total",
    "redis_stream_pending",
    "redis_stream_lag",
    "perception_latency_ms",
}


@dataclass
class MetricsRegistry:
    counters: dict[str, int] = field(default_factory=lambda: {name: 0 for name in METRIC_NAMES})

    def increment(self, name: str, amount: int = 1) -> None:
        if name not in METRIC_NAMES:
            raise KeyError(f"unknown metric: {name}")
        self.counters[name] += amount

    def render_prometheus(self) -> str:
        lines: list[str] = []
        for name in sorted(self.counters):
            lines.append(f"# TYPE argus_{name} counter")
            lines.append(f"argus_{name} {self.counters[name]}")
        return "\n".join(lines) + "\n"
