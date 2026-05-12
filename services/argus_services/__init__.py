"""Argus service primitives for local Hermes integration."""

from .events import EventEnvelope, Redaction, Relationship, make_event
from .event_gateway import EventGateway
from .hermes_plugin import register
from .mcp import LocalMCPServer, ToolRegistry
from .perception import PerceptionOutput, PerceptionWorker, TemplateSummarizer
from .policy import PolicyDecision, RedactionPolicy, RedactionResult
from .store import InMemoryEventStore
from .streams import RedisStreamPublisher, stream_for_event

__all__ = [
    "EventEnvelope",
    "EventGateway",
    "InMemoryEventStore",
    "LocalMCPServer",
    "PerceptionOutput",
    "PerceptionWorker",
    "PolicyDecision",
    "Redaction",
    "RedactionPolicy",
    "RedactionResult",
    "Relationship",
    "RedisStreamPublisher",
    "TemplateSummarizer",
    "ToolRegistry",
    "make_event",
    "register",
    "stream_for_event",
]
