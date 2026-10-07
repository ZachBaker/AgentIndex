"""Model Context Protocol server over stdio (``agentindex mcp``).

Exposes search_docs, read_doc and list_docs as tools so agents in Claude Code
(or any MCP client) query the knowledge base natively. A tools-only server
needs only a small slice of MCP (newline-delimited JSON-RPC 2.0: initialize,
ping, tools/list, tools/call), so it is implemented with the standard library.
"""

from __future__ import annotations

import json
import sys
import traceback
from typing import BinaryIO

from . import __version__, render
from .config import Config
from .errors import AgentIndexError, NotFoundError
from .store import KnowledgeIndex

# Newest first. A client asking for a version not listed here gets the newest
# one we implement, as the MCP version negotiation rules require.
PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = (
    -32700,
    -32600,
    -32601,
    -32602,
    -32603,
)

INSTRUCTIONS = (
    "This server indexes the project's knowledge base: architecture, conventions, workflows and "
    "gotchas, written for agents. Before exploring unfamiliar code or making changes, call "
    "search_docs with a few keywords for the topic, then read_doc the most relevant result "
    "(use id#section to read just one section). Use list_docs to browse everything."
)
READ_HINT = 'Read one with read_doc(id="<id>"), or id="<id>#<section>" for just that section.'
OUTLINE_HINT = 'Read one section with read_doc(id="<id>#<anchor>").'
LIST_HINT = "Search with search_docs(query=...), read with read_doc(id=...)."

_TAGS_SCHEMA = {
    "type": "array",
    "items": {"type": "string"},
    "description": "Only docs that have all of these tags.",
}
_READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}

TOOLS = [
    {
        "name": "search_docs",
        "title": "Search project knowledge",
        "description": (
            "Search the project's knowledge base (architecture, conventions, how-tos, runbooks) "
            "by keywords. Use it before exploring code to learn how things work and where they "
            "live. Returns ranked docs with ids, summaries and best-matching sections; follow up "
            'with read_doc. Supports "exact phrases" and -excluded words.'
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keywords or a short question, e.g. 'deploy rollback'.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "description": "Maximum number of docs to return (default 8).",
                },
                "tags": _TAGS_SCHEMA,
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "annotations": _READ_ONLY,
    },
    {
        "name": "read_doc",
        "title": "Read a knowledge doc",
        "description": (
            "Read a knowledge-base doc by id (from search_docs or list_docs). Pass 'id#anchor' or "
            "section to read just one section, or outline=true to see a long doc's sections "
            "and sizes first."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": "Doc id like 'architecture/overview', optionally '#anchor'.",
                },
                "section": {
                    "type": "string",
                    "description": "Section anchor or heading text; reads only that section.",
                },
                "outline": {
                    "type": "boolean",
                    "description": "Return the doc's headings and word counts, not its text.",
                },
            },
            "required": ["id"],
            "additionalProperties": False,
        },
        "annotations": _READ_ONLY,
    },
    {
        "name": "list_docs",
        "title": "List knowledge docs",
        "description": (
            "List every doc in the knowledge base with its id, title and summary. Use it to "
            "browse when you are not sure what to search for."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"tags": _TAGS_SCHEMA},
            "additionalProperties": False,
        },
        "annotations": _READ_ONLY,
    },
]


class _RpcError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class McpServer:
    def __init__(self, index: KnowledgeIndex):
        self.index = index
        self._tools = {"search_docs": self._search, "read_doc": self._read, "list_docs": self._list}

    def handle(self, message: object) -> dict | None:
        """The response to one JSON-RPC message, or None for notifications."""
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return _error(None, INVALID_REQUEST, "expected a JSON-RPC 2.0 message")
        if "method" not in message:
            return None  # a response; this server never sends requests
        request_id = message.get("id")
        notification = "id" not in message
        method = message["method"]
        params = message.get("params") or {}
        try:
            if not isinstance(params, dict):
                raise _RpcError(INVALID_PARAMS, "params must be an object")
            if method == "initialize":
                result = self._initialize(params)
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                result = self._call_tool(params)
            elif notification:
                return None  # notifications/initialized, notifications/cancelled, ...
            else:
                raise _RpcError(METHOD_NOT_FOUND, f"method not found: {method}")
        except _RpcError as exc:
            return None if notification else _error(request_id, exc.code, exc.message)
        except Exception as exc:  # one bad request must not take the server down
            traceback.print_exc(file=sys.stderr)
            return None if notification else _error(request_id, INTERNAL_ERROR, str(exc))
        return None if notification else {"jsonrpc": "2.0", "id": request_id, "result": result}

    def _initialize(self, params: dict) -> dict:
        requested = params.get("protocolVersion")
        return {
            "protocolVersion": requested
            if requested in PROTOCOL_VERSIONS
            else PROTOCOL_VERSIONS[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "agentindex", "title": "AgentIndex", "version": __version__},
            "instructions": INSTRUCTIONS,
        }

    def _call_tool(self, params: dict) -> dict:
        name = params.get("name")
        handler = self._tools.get(name)
        if handler is None:
            raise _RpcError(INVALID_PARAMS, f"unknown tool: {name!r}")
        arguments = params.get("arguments") or {}
        try:
            if not isinstance(arguments, dict):
                raise ValueError("arguments must be an object")
            return _tool_result(handler(arguments))
        except NotFoundError as exc:
            text = f"Error: {exc}"
            if exc.suggestions:
                text += "\nDid you mean: " + ", ".join(exc.suggestions)
            return _tool_result(text, error=True)
        except (AgentIndexError, ValueError) as exc:
            return _tool_result(f"Error: {exc}", error=True)

    def _search(self, args: dict) -> str:
        result = self.index.search(
            _string(args, "query"), limit=_integer(args, "limit", 8), tags=_strings(args, "tags")
        )
        return render.render_search(result, READ_HINT)

    def _read(self, args: dict) -> str:
        ref = _string(args, "id")
        if args.get("outline"):
            return render.render_outline(self.index.outline(ref), OUTLINE_HINT)
        section = args.get("section")
        if section is not None and not isinstance(section, str):
            raise ValueError("'section' must be a string")
        return render.render_doc(self.index.read(ref, section=section or None))

    def _list(self, args: dict) -> str:
        return render.render_list(self.index.list_docs(tags=_strings(args, "tags")), LIST_HINT)


def _string(args: dict, name: str) -> str:
    value = args.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"'{name}' is required and must be a non-empty string")
    return value


def _integer(args: dict, name: str, default: int) -> int:
    value = args.get(name, default)
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError(f"'{name}' must be an integer")
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"'{name}' must be an integer") from None


def _strings(args: dict, name: str) -> list[str]:
    value = args.get(name) or []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError(f"'{name}' must be a list of strings")
    return value


def _tool_result(text: str, error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": error}


def _error(request_id: object, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def serve_stdio(server: McpServer, stdin: BinaryIO, stdout: BinaryIO) -> None:
    for raw in stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            reply: object = _error(None, PARSE_ERROR, "parse error: invalid JSON")
        else:
            if isinstance(message, list):  # JSON-RPC batch (older protocol versions)
                replies = [r for r in map(server.handle, message) if r is not None]
                reply = replies or (
                    None if message else _error(None, INVALID_REQUEST, "empty batch")
                )
            else:
                reply = server.handle(message)
        if reply is not None:
            stdout.write(json.dumps(reply, ensure_ascii=False).encode("utf-8") + b"\n")
            stdout.flush()


def run(config: Config) -> int:
    stdin, stdout = sys.stdin.buffer, sys.stdout.buffer
    sys.stdout = sys.stderr  # stray prints must never corrupt the protocol stream
    with KnowledgeIndex(config, min_sync_interval=1.0) as index:
        serve_stdio(McpServer(index), stdin, stdout)
    return 0
