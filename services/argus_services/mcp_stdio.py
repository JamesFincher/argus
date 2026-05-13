"""JSON-RPC stdio transport for the local Argus MCP tool surface."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any, TextIO

from .event_gateway import audit_log_from_env, store_from_env
from .graph import GraphConfig, graph_from_config
from .mcp import LocalMCPServer
from .retrieval import InMemoryNoteIndex, LanceDBNoteIndex

JSONRPC_VERSION = "2.0"
MCP_PROTOCOL_VERSION = "2024-11-05"


TOOL_INPUT_SCHEMAS: dict[str, dict[str, Any]] = {
    "sensor_get_recent_notes": {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "minimum": 1,
                "description": "Maximum recent events to summarize.",
            },
            "actor": {
                "type": "string",
                "description": "Agent or session requesting the tool.",
            },
        },
        "additionalProperties": False,
    },
    "sensor_expand_event": {
        "type": "object",
        "properties": {
            "event_id": {
                "type": "string",
                "description": "Argus event identifier to expand.",
            },
            "raw_mode": {
                "type": "string",
                "enum": ["redacted", "full"],
                "description": (
                    "Return redacted event data by default; full raw data requires approval."
                ),
            },
            "approval_token": {
                "type": "string",
                "description": "Optional approval token for full raw access.",
            },
            "actor": {
                "type": "string",
                "description": "Agent or session requesting the tool.",
            },
        },
        "required": ["event_id"],
        "additionalProperties": False,
    },
    "sensor_timeline_search": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search text for redacted local timeline summaries.",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "description": "Maximum matches to return.",
            },
            "actor": {
                "type": "string",
                "description": "Agent or session requesting the tool.",
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    "sensor_find_workflow_patterns": {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "minimum": 1,
                "description": "Maximum workflow transitions to return.",
            },
            "actor": {
                "type": "string",
                "description": "Agent or session requesting the tool.",
            },
        },
        "additionalProperties": False,
    },
    "sensor_pause_scope": {
        "type": "object",
        "properties": {
            "scope": {"type": "string", "description": "Local sensing scope to pause."},
            "actor": {
                "type": "string",
                "description": "Agent or session requesting the tool.",
            },
        },
        "required": ["scope"],
        "additionalProperties": False,
    },
    "sensor_forget_scope": {
        "type": "object",
        "properties": {
            "scope": {"type": "string", "description": "Local data scope to purge."},
            "actor": {
                "type": "string",
                "description": "Agent or session requesting the tool.",
            },
        },
        "required": ["scope"],
        "additionalProperties": False,
    },
    "sensor_export_session_brief": {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "minimum": 1,
                "description": "Maximum recent events to include in the brief.",
            },
            "actor": {
                "type": "string",
                "description": "Agent or session requesting the tool.",
            },
        },
        "additionalProperties": False,
    },
}


class JsonRpcError(Exception):
    """Exception carrying a JSON-RPC error code and message."""

    def __init__(self, code: int, message: str, data: Any | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


@dataclass
class MCPStdioServer:
    """Minimal MCP-compatible JSON-RPC dispatcher backed by LocalMCPServer."""

    server: LocalMCPServer = field(default_factory=lambda: local_mcp_server_from_env())
    protocol_version: str = MCP_PROTOCOL_VERSION

    def handle_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        request_id = request.get("id")
        try:
            method = self._method_from_request(request)
            if request_id is None and method.startswith("notifications/"):
                self._handle_notification(method)
                return None
            result = self._dispatch(method, request.get("params", {}))
            return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result}
        except JsonRpcError as error:
            return self._error_response(request_id, error.code, error.message, error.data)
        except TypeError as error:
            return self._error_response(request_id, -32602, "invalid params", str(error))
        except KeyError as error:
            return self._error_response(request_id, -32602, "invalid params", str(error))
        except Exception as error:
            return self._error_response(request_id, -32603, "internal error", str(error))

    def handle_line(self, line: str) -> dict[str, Any] | None:
        try:
            request = json.loads(line)
        except json.JSONDecodeError as error:
            return self._error_response(None, -32700, "parse error", str(error))
        if not isinstance(request, dict):
            return self._error_response(
                None,
                -32600,
                "invalid request",
                "request must be a JSON object",
            )
        return self.handle_request(request)

    def serve(self, stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> None:
        for line in stdin:
            if not line.strip():
                continue
            response = self.handle_line(line)
            if response is not None:
                stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
                stdout.flush()

    def _method_from_request(self, request: dict[str, Any]) -> str:
        if request.get("jsonrpc") != JSONRPC_VERSION:
            raise JsonRpcError(-32600, "invalid request", "jsonrpc must be 2.0")
        method = request.get("method")
        if not isinstance(method, str) or not method:
            raise JsonRpcError(-32600, "invalid request", "method must be a non-empty string")
        return method

    def _dispatch(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(params, dict):
            raise JsonRpcError(-32602, "invalid params", "params must be an object")
        if method == "initialize":
            return self._initialize(params)
        if method == "tools/list":
            return {"tools": self._tools()}
        if method == "tools/call":
            return self._call_tool(params)
        raise JsonRpcError(-32601, "method not found", method)

    def _handle_notification(self, method: str) -> None:
        if method == "notifications/initialized":
            return
        raise JsonRpcError(-32601, "method not found", method)

    def _initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "protocolVersion": params.get("protocolVersion", self.protocol_version),
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "argus", "version": "0.1.0"},
        }

    def _tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": tool["name"],
                "description": tool["description"],
                "inputSchema": TOOL_INPUT_SCHEMAS[tool["name"]],
            }
            for tool in self.server.list_tools()
        ]

    def _call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or not name:
            raise JsonRpcError(-32602, "invalid params", "tools/call requires a tool name")
        if not isinstance(arguments, dict):
            raise JsonRpcError(-32602, "invalid params", "arguments must be an object")

        result = self.server.call_tool(name, **arguments)
        is_error = result.get("ok") is False
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result, sort_keys=True),
                }
            ],
            "isError": is_error,
            "structuredContent": result,
        }

    def _error_response(
        self,
        request_id: Any,
        code: int,
        message: str,
        data: Any | None = None,
    ) -> dict[str, Any]:
        error: dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "error": error}


def main() -> None:
    MCPStdioServer().serve()


def local_mcp_server_from_env() -> LocalMCPServer:
    lancedb_path = os.environ.get("ARGUS_LANCEDB_PATH")
    note_index = LanceDBNoteIndex(lancedb_path) if lancedb_path else InMemoryNoteIndex()
    return LocalMCPServer(
        store=store_from_env(),
        audit_log=audit_log_from_env(),
        note_index=note_index,
        graph=graph_from_config(GraphConfig.from_env()),
    )


if __name__ == "__main__":  # pragma: no cover
    main()
