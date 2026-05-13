"""Argus service primitives for local Hermes integration."""

from .audit import AuditRecord, InMemoryAuditLog
from .events import EventEnvelope, Redaction, Relationship, make_event
from .event_gateway import EventGateway
from .graph import DisabledGraphAdapter, GraphConfig
from .hermes_plugin import register
from .mcp import LocalMCPServer, ToolRegistry
from .metrics import METRIC_NAMES, MetricsRegistry
from .perception import PerceptionOutput, PerceptionWorker, TemplateSummarizer
from .policy import PolicyDecision, RedactionPolicy, RedactionResult
from .purge import ScopePurgeResult
from .retrieval import HashEmbeddingModel, InMemoryNoteIndex, LanceDBNoteIndex, RetrievalNote
from .sqlite_store import SQLiteAuditLog, SQLiteTimelineStore
from .store import InMemoryEventStore
from .storage_worker import RedisToSQLiteWorker
from .streams import RedisStreamConsumer, RedisStreamPublisher, StreamMessage, stream_for_event

__all__ = [
    "AuditRecord",
    "DisabledGraphAdapter",
    "EventEnvelope",
    "EventGateway",
    "GraphConfig",
    "HashEmbeddingModel",
    "InMemoryEventStore",
    "InMemoryAuditLog",
    "InMemoryNoteIndex",
    "LanceDBNoteIndex",
    "LocalMCPServer",
    "METRIC_NAMES",
    "MetricsRegistry",
    "PerceptionOutput",
    "PerceptionWorker",
    "PolicyDecision",
    "Redaction",
    "RedactionPolicy",
    "RedactionResult",
    "Relationship",
    "RedisStreamConsumer",
    "RedisStreamPublisher",
    "RedisToSQLiteWorker",
    "RetrievalNote",
    "SQLiteAuditLog",
    "SQLiteTimelineStore",
    "ScopePurgeResult",
    "StreamMessage",
    "TemplateSummarizer",
    "ToolRegistry",
    "make_event",
    "register",
    "stream_for_event",
]
