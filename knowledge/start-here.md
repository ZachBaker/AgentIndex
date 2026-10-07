---
title: "Start here: what AgentIndex is"
summary: What AgentIndex is, how this repository is laid out, and which docs to read first.
tags: [overview]
keywords: [onboarding, getting started, introduction, map, repository layout, project structure, what is agentindex]
---

# Start here

AgentIndex turns a folder of markdown docs into a searchable knowledge base for
coding agents. Instead of loading one huge CLAUDE.md into every session, agents
search the index, read the one doc or section they need, and get back to work.

This repository is the tool itself, and it uses its own index: the docs you are
reading are served by it.

## Repository layout

| Path | What lives there |
|---|---|
| `agentindex/` | The Python package, standard library only. See [architecture/overview](architecture/overview.md). |
| `agentindex/templates/` | Files that `init` writes into other repos: the CLAUDE.md pointer and starter docs. |
| `knowledge/` | This knowledge base. |
| `tests/` | The `unittest` suite. See [development/testing](development/testing.md). |
| `.agentindex.json` | Which paths are indexed. See [configuration](configuration.md). |
| `.mcp.json` | Registers the MCP server, giving Claude Code `search_docs`, `read_doc` and `list_docs` tools. |

## Read these first

- [Using the index](using-the-index.md): how to search and read effectively.
- [Architecture overview](architecture/overview.md): how sync, search and the three interfaces fit together.
- [Code conventions](development/conventions.md): the rules for changing the code.
- [Writing knowledge docs](../agentindex/templates/writing-docs.md) (id `writing-docs`): how to write docs for the index.
- [Adopting AgentIndex](guides/adopting-agentindex.md): putting it in another repository.
