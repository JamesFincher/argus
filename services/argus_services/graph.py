"""Optional graph integration boundaries for Argus Mesh."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


TRUE_VALUES = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class GraphConfig:
    enabled: bool = False
    uri: str = "bolt://127.0.0.1:7687"
    database: str = "neo4j"

    @classmethod
    def from_env(cls) -> "GraphConfig":
        return cls(
            enabled=os.environ.get("ARGUS_NEO4J_ENABLED", "").lower() in TRUE_VALUES,
            uri=os.environ.get("ARGUS_NEO4J_URI", "bolt://127.0.0.1:7687"),
            database=os.environ.get("ARGUS_NEO4J_DATABASE", "neo4j"),
        )


@dataclass
class DisabledGraphAdapter:
    reason: str = "neo4j feature flag disabled"
    enabled: bool = False

    def workflow_patterns(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"enabled": False, "reason": self.reason, "patterns": []}

    def forget_scope(self, _scope: str) -> int:
        return 0


def graph_from_config(config: GraphConfig) -> Any:
    if not config.enabled:
        return DisabledGraphAdapter()
    return Neo4jGraphAdapter(config)


@dataclass
class Neo4jGraphAdapter:
    config: GraphConfig
    enabled: bool = True
    driver: Any | None = None

    def __post_init__(self) -> None:
        if self.driver is None:
            from neo4j import GraphDatabase  # type: ignore[import-not-found]

            self.driver = GraphDatabase.driver(self.config.uri)

    def workflow_patterns(self, *, limit: int = 25) -> dict[str, Any]:
        query = """
        MATCH (e1:Event)-[r:FOLLOWED_BY]->(e2:Event)
        RETURN e1.event_type AS from_event_type,
               e2.event_type AS to_event_type,
               count(*) AS count
        ORDER BY count DESC
        LIMIT $limit
        """
        with self.driver.session(database=self.config.database) as session:
            rows = session.run(query, limit=limit)
            patterns = [dict(row) for row in rows]
        return {"enabled": True, "patterns": patterns}

    def forget_scope(self, _scope: str) -> int:
        # Graph mirroring is optional and not yet the source of truth. Until the
        # mirror worker lands, SQLite/LanceDB purge counts remain authoritative.
        return 0
