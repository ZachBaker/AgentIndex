---
title: Architecture overview
summary: How AgentIndex is put together. Markdown files sync into SQLite FTS5, the KnowledgeIndex core ranks and reads them, and thin CLI, MCP and HTTP layers expose it.
tags: [architecture]
keywords: [design, modules, components, data flow, pipeline, how it works, internals, design decisions]
related: [architecture/search-ranking, architecture/database, architecture/markdown-parsing]
---

# Architecture overview

Markdown files are the source of truth, and SQLite is a cache that makes them searchable.
Every query first syncs the cache with the files, so there is no build step to forget.

```
knowledge/*.md ──sync──> SQLite: documents, sections, links + FTS5 tables
                                     │
                  KnowledgeIndex: search · read · outline · list · check
                                     │
               ┌─────────────────────┼─────────────────────┐
              CLI               MCP (stdio)             HTTP API
```

## Modules

| Module | Responsibility |
|---|---|
| [config.py](../../agentindex/config.py) | Find the project root, load `.agentindex.json`. |
| [frontmatter.py](../../agentindex/frontmatter.py) | Parse the YAML subset used in front matter. |
| [markdown.py](../../agentindex/markdown.py) | Headings, anchors, sections, links and summaries, all code-fence aware. |
| [query.py](../../agentindex/query.py) | Turn free text into FTS5 match expressions. |
| [store.py](../../agentindex/store.py) | `KnowledgeIndex`: schema, sync, ranking, read, list, check. |
| [render.py](../../agentindex/render.py) | Text output shared by the CLI and the MCP server. |
| [cli.py](../../agentindex/cli.py) | The `argparse` commands. |
| [mcp_server.py](../../agentindex/mcp_server.py) | MCP tools over stdio (JSON-RPC). |
| [http_api.py](../../agentindex/http_api.py) | The JSON API on `http.server`. |
| [scaffold.py](../../agentindex/scaffold.py) | `init` and `import`. |
| [errors.py](../../agentindex/errors.py) | User-facing exception types. |

## Life of a query

1. An interface loads the config and creates a `KnowledgeIndex`.
2. `ensure_synced()` stats every source file and re-parses only those whose size,
   modification time and content hash changed ([database](database.md#sync)).
3. `search()` parses the query, scores the matching docs phrase by phrase, and picks each
   result's best sections and snippets ([search ranking](search-ranking.md)).
4. The interface renders the result as text (CLI, MCP) or JSON (HTTP, `--json`).

## Design decisions

- **Markdown in git, not rows in a database.** Docs get code review, history and merges
  like code, and the database can always be rebuilt from them.
- **Standard library only, Python 3.9+.** There is nothing to install, so it runs in any
  agent sandbox, and another repo can vendor it by copying one folder.
- **Lexical search, not embeddings.** BM25 over a curated knowledge base is fast,
  deterministic and explainable. `keywords` front matter covers synonyms.
- **Sections are first-class.** Results point at sections and `read` can return just one,
  so agents spend context only on what is relevant.
- **One core, thin interfaces.** Behavior lives in `KnowledgeIndex`; the interfaces only
  parse input and format output, so they cannot drift apart.
