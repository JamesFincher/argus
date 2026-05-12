"""Argus service primitives for local Hermes integration."""

from .events import EventEnvelope, Redaction, Relationship, make_event
from .hermes_plugin import register
from .mcp import LocalMCPServer, ToolRegistry
from .policy import PolicyDecision, RedactionPolicy, RedactionResult
from .store import InMemoryEventStore

__all__ = [
    "EventEnvelope",
    "InMemoryEventStore",
    "LocalMCPServer",
    "PolicyDecision",
    "Redaction",
    "RedactionPolicy",
    "RedactionResult",
    "Relationship",
    "ToolRegistry",
    "make_event",
    "register",
]
