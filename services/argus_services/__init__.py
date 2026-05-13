"""Argus service primitives for local Hermes integration."""

from .audit import AuditRecord, InMemoryAuditLog
from .events import EventEnvelope, Redaction, Relationship, make_event
from .event_gateway import EventGateway
from .hermes_plugin import register
from .mcp import LocalMCPServer, ToolRegistry
from .metrics import METRIC_NAMES, MetricsRegistry
from .perception import PerceptionOutput, PerceptionWorker, TemplateSummarizer
from .policy import PolicyDecision, RedactionPolicy, RedactionResult
from .retrieval import InMemoryNoteIndex, RetrievalNote
from .sqlite_store import SQLiteAuditLog, SQLiteTimelineStore
from .store import InMemoryEventStore
from .streams import RedisStreamConsumer, RedisStreamPublisher, StreamMessage, stream_for_event

__all__ = [
    "AuditRecord",
    "EventEnvelope",
    "EventGateway",
    "InMemoryEventStore",
    "InMemoryAuditLog",
    "InMemoryNoteIndex",
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
    "RetrievalNote",
    "SQLiteAuditLog",
    "SQLiteTimelineStore",
    "StreamMessage",
    "TemplateSummarizer",
    "ToolRegistry",
    "make_event",
    "register",
    "stream_for_event",
]
