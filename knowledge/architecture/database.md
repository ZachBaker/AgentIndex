---
title: Database and sync
summary: The SQLite schema, how sync keeps it in step with the markdown files, schema versioning, and concurrency between processes.
tags: [architecture, database]
keywords: [sqlite, schema, tables, sync, incremental, cache, wal, migrations, rebuild, locking, concurrency, fts5, index.db]
related: [architecture/overview]
---

# Database and sync

The database is a cache of the markdown sources, kept in `.agentindex/index.db` by
default. Code: [store.py](../../agentindex/store.py).

## Tables

| Table | Contents |
|---|---|
| `documents` | One row per doc: id, path, title, summary, tags, keywords, other front matter (`meta`), the body, word count, parse warnings, and the file's hash, mtime and size. |
| `sections` | One row per heading, plus any text before the first heading: level, heading, anchor, line range and word count. |
| `tags` | `(doc, tag)` pairs, for filtering. |
| `links` | Links found in docs. `doc` links point at markdown files, `file` links at any other path, `anchor` links at a `#section` in the same doc, and `related` entries come from front matter. Targets are stored as root-relative paths, so they resolve whenever the target exists. |
| `docs_fts` | FTS5 table with title, keywords, tags, summary, headings and body. |
| `sections_fts` | FTS5 table with heading, context (parent headings and doc title) and body. |
| `meta` | `schema_version` and `last_sync`. |

Both FTS5 tables use the `porter unicode61` tokenizer, which every SQLite with FTS5
supports, and share rowids with `documents` and `sections`.

## Sync

`sync()` runs before every query in a single `BEGIN IMMEDIATE` transaction. The MCP and
HTTP servers run it at most once per second.

1. Discover the source files. Delete the rows of files that no longer exist, and of
   files whose id changed because `sources` did, so they are re-added under the new id.
2. Skip each file whose size and mtime are unchanged. Otherwise hash it; if only its
   timestamp changed, record the new mtime and move on.
3. Re-parse the changed files and replace all of their rows.
4. Skip and report a file whose id is already taken by another file. `check` reports this
   as an error.

`sync --force` re-parses everything. It is only needed if a file changed without its size
or mtime changing.

## Schema versions

`SCHEMA_VERSION` in `store.py` is stored in `meta`. When it differs from the code's
version, every table is dropped and recreated, and the next sync re-indexes everything.
**Bump it whenever the schema or the parsing output changes.** No migrations are needed,
because the markdown files hold all the data. A corrupt database file is deleted and rebuilt.

## Concurrency

The database runs in WAL mode, so readers never block. Writers (syncs) use
`BEGIN IMMEDIATE` and wait up to 30 seconds for each other, so a CLI command, the MCP
server and the HTTP server can share one database. Each HTTP request opens its own
connection, because a SQLite connection belongs to one thread.
