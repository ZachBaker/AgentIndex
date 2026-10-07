---
title: MCP server
summary: The stdio MCP server that gives Claude Code and other MCP clients native search_docs, read_doc and list_docs tools. Covers registration, the tools, and protocol details.
tags: [interfaces, reference, mcp]
keywords: [model context protocol, mcp, claude code, tools, stdio, json-rpc, mcp.json, search_docs, read_doc, list_docs, protocol version, permissions]
---

# MCP server

`python3 -m agentindex mcp` speaks the Model Context Protocol over stdin and stdout, so
agents get the index as native tools instead of shell commands. Code:
[mcp_server.py](../../agentindex/mcp_server.py).

## Registration

This repo registers the server for Claude Code in [.mcp.json](../../.mcp.json):

```json
{"mcpServers": {"agentindex": {"command": "python3", "args": ["-m", "agentindex", "mcp"]}}}
```

Claude Code starts project servers in the project directory and asks each user to approve
a project's servers once. Repos that install AgentIndex instead of vendoring it use
`{"command": "agentindex", "args": ["mcp"]}`, which is what `init` writes. To avoid
permission prompts for these read-only tools, a user can allow `mcp__agentindex__*` in their
own Claude Code settings.

## Tools

| Tool | Arguments | Returns |
|---|---|---|
| `search_docs` | `query` (required), `limit` (1 to 50, default 8), `tags` | Ranked docs, in the same text format as the CLI. |
| `read_doc` | `id` (required, may include `#anchor`), `section`, `outline` | The doc, one section, or its outline. |
| `list_docs` | `tags` | Every doc with its id, title and summary. |

All three tools are annotated read-only. Problems the agent can fix, like an unknown id or
an empty query, come back as an ordinary result with `isError: true` and suggestions, so the
model can try again. Unknown tools and malformed requests are JSON-RPC errors.

The server's `instructions` tell agents to search before exploring code. Claude Code cuts
server instructions off at 2,048 characters, so keep them short.

## Protocol details

- Newline-delimited JSON-RPC 2.0. The methods are `initialize`, `ping`, `tools/list` and
  `tools/call`. Notifications are ignored, and batches (from older protocol versions) are
  answered.
- Version negotiation: if the client asks for a version the server implements
  (`2025-11-25`, `2025-06-18`, `2025-03-26` or `2024-11-05`), it is echoed back. Otherwise
  the server answers with `2025-11-25`, the newest it implements, and the client decides
  whether to continue. Requests are served even before `initialize`.
- An accidental `print` would corrupt the protocol stream, so `run()` points `sys.stdout`
  at stderr and writes protocol messages to the original stdout.
- The index syncs at most once per second while the server runs.

## Debugging

Pipe JSON-RPC messages in by hand:

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"search_docs","arguments":{"query":"ranking"}}}' \
  | python3 -m agentindex mcp
```
