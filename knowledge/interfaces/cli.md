---
title: CLI reference
summary: Every agentindex command and option, with exit codes and JSON output.
tags: [interfaces, reference]
keywords: [command line, commands, options, flags, exit codes, json output, search, read, list, check, sync, status, serve, mcp, init, import, usage]
---

# CLI reference

Run it as `python3 -m agentindex <command>` from this repository (or from a repo with a
vendored copy), or as `agentindex <command>` when it is installed. Two global options work
before or after the command: `--root <dir>` and `--db <path>`
([configuration](../configuration.md)). Code: [cli.py](../../agentindex/cli.py).

## Reading the knowledge base

| Command | What it does |
|---|---|
| `search <words...> [-n 8] [-t TAG]... [--json]` | Ranked docs with summaries and best sections. See [writing queries](../using-the-index.md#writing-queries). |
| `read <id>[#anchor] [-s SECTION] [--outline] [--json]` | A whole doc, one section, or the doc's outline. Accepts ids, file paths and unique id endings. |
| `list [-t TAG]... [--json]` | Every doc with its summary, plus tag counts. |

## Maintaining it

| Command | What it does |
|---|---|
| `check [--strict] [--json]` | Lint the docs: broken links (to docs and to code), links to missing sections, duplicate ids, missing titles and summaries, very long docs. |
| `sync [--force] [--json]` | Update the index now. Never required, since every command syncs first. |
| `status [--json]` | Root, config, sources, database location and counts. |
| `init [--dir DIR] [--no-mcp]` | Set up a repository. See [adopting AgentIndex](../guides/adopting-agentindex.md). |
| `import FILE [--level 2] [--into DIR] [--dry-run] [--force]` | Split a large markdown file, such as a CLAUDE.md, into one doc per section. |

## Servers

| Command | What it does |
|---|---|
| `mcp` | The MCP server on stdin and stdout. See [MCP server](mcp-server.md). |
| `serve [--host 127.0.0.1] [--port 8765] [--quiet]` | The HTTP JSON API. See [HTTP API](http-api.md). |

## Exit codes and JSON

- `0`: success, including a search with no results.
- `1`: a doc or section was not found (suggestions are printed to stderr), or `check`
  found errors (or warnings, with `--strict`).
- `2`: bad usage or configuration, such as a query with no search terms or an invalid
  `.agentindex.json`.

With `--json`, results are printed as JSON, and errors as
`{"error": "...", "suggestions": [...]}` on stdout. The shapes match the
[HTTP API](http-api.md) responses.
