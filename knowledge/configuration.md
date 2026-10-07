---
title: Configuration
summary: The .agentindex.json file, how the project root is found, where the database lives, and the environment variables that override them.
tags: [configuration, reference]
keywords: [config, settings, sources, exclude, db, database path, AGENTINDEX_ROOT, AGENTINDEX_DB, root discovery, agentindex.json, ids]
---

# Configuration

AgentIndex works without configuration: it indexes `knowledge/` under the project root
into `.agentindex/index.db`. A `.agentindex.json` file at the root changes that, and also
marks where the root is. Code: [config.py](../agentindex/config.py).

## .agentindex.json

```json
{
  "//": "keys starting with // are comments",
  "sources": ["knowledge", "docs/adr", "agentindex/templates/writing-docs.md"],
  "exclude": ["**/drafts/**"],
  "db": ".agentindex/index.db"
}
```

| Key | Default | Meaning |
|---|---|---|
| `sources` | `["knowledge"]` | Directories, searched recursively for `.md`, `.markdown` and `.mdx` files, or single files. Relative to the root, and must stay inside it. |
| `exclude` | `[]` | Glob patterns matched against root-relative paths. `*` also matches `/`, and a leading `**/` also matches at the top level. |
| `db` | `.agentindex/index.db` | The database file, relative to the root (or absolute, or `:memory:`). |

Unknown keys are an error, which catches typos like `source`.

## Doc ids

A doc's id is its path relative to its source directory, without the extension:
`knowledge/architecture/overview.md` is `architecture/overview`. A file listed directly as a
source gets its file name as its id (`writing-docs`). If sources overlap, a file is indexed
once, under the first source listed that contains it. If two files would get the same id,
the second is skipped and `check` reports an error. Changing `sources` re-indexes files
whose ids change. Hidden files and directories, `node_modules`
and `__pycache__` are never indexed.

## Finding the project root

In order of precedence:

1. `--root <dir>` on the command line.
2. The `AGENTINDEX_ROOT` environment variable.
3. The nearest directory, from the current one upwards, that contains `.agentindex.json`.
4. The nearest directory that contains `.git`.
5. The current directory.

## The database

`--db <path>` or `AGENTINDEX_DB` override the configured path. The database is only a cache
of the markdown files: it is created on first use, updated before every query, rebuilt when
the schema changes, and always safe to delete. Keep `.agentindex/` in `.gitignore`. Details:
[architecture/database](architecture/database.md).
