# AgentIndex

A searchable knowledge base for coding agents.

A CLAUDE.md tends to grow into hundreds of lines of architecture notes, conventions
and gotchas, and every session loads all of it. AgentIndex moves that knowledge into
small markdown docs that agents **search** and **read on demand**, so CLAUDE.md
shrinks to a short pointer:

```console
$ agentindex search "roll back a deploy" -n 2
5 docs match "roll back a deploy", showing the top 2:

1. ops/deploying — Deploying to production  [deploy, ops]
   How releases reach production, and how to roll one back.
   § Rollback (ops/deploying#rollback)
     If a release breaks, **roll back** the **deploy** with **deploy** --**rollback**.
   § Deploying to production (ops/deploying#deploying-to-production)
     **Deploys** go out through the **deploy** pipeline. Each **deploy** is tagged.

2. migrations — Database migrations  [database]
   Writing, reviewing and reverting schema migrations.
   § Rolling back (migrations#rolling-back)
     Run make migrate-down to revert the last migration.

Read one: agentindex read <id>  (or <id>#<section> for just that section)

$ agentindex read ops/deploying#rollback
id: ops/deploying#rollback | file: knowledge/ops/deploying.md:10 | tags: deploy, ops

## Rollback

If a release breaks, roll back the deploy with `deploy --rollback`.
```

## Features

- **Markdown in git is the source of truth.** A SQLite FTS5 index is built from it and
  synced automatically before every query, so there is no build step and no stale index.
- **Ranking that works on small knowledge bases.** Per-field BM25 with a smoothed IDF,
  prefix and stem matching, and phrase boosts. Plain questions like "how do I roll back a
  deploy?" work.
- **Section-level results.** Results point at the matching section, and agents can read
  just that section instead of the whole doc.
- **Three interfaces, one core.** A CLI, an MCP server (native `search_docs`, `read_doc`
  and `list_docs` tools in Claude Code), and an HTTP JSON API.
- **Migration in one command.** `agentindex import CLAUDE.md` splits an existing CLAUDE.md
  into one doc per section, fixing heading styles the index would not see. For the parts that
  need judgement, `agentindex import --guide` prints a checklist for the agent doing the
  migration (or run the `/migrate-claude-md` skill that `init` adds).
- **A linter for CI.** `agentindex check` catches broken links to docs and code, duplicate
  ids, and docs missing a title or summary.
- **A contradiction finder.** `agentindex conflicts` finds statements in different docs that
  nearly repeat each other but disagree, such as port 8765 in one doc and 8080 in another,
  or "enabled" in one and "disabled" in another, so stale copies of a fact get fixed.
- **No dependencies.** Python 3.9+ standard library only. Install it, or vendor the
  `agentindex/` folder into your repo.

## Quick start

```bash
pip install git+https://github.com/ZachBaker/AgentIndex   # or copy agentindex/ into your repo
cd your-repo
agentindex init                    # config, starter docs, .mcp.json entry, CLAUDE.md pointer
agentindex import CLAUDE.md        # optional: split an existing CLAUDE.md into docs
agentindex search "how do we deploy"
```

`init` never overwrites existing files. The full walkthrough, including what to keep in
CLAUDE.md, is in [Adopting AgentIndex](knowledge/guides/adopting-agentindex.md).

## Commands

| Command | What it does |
|---|---|
| `search <words>` | Ranked docs with summaries and best-matching sections |
| `read <id>[#section]` | A whole doc or one section (`--outline` lists its headings) |
| `list` | Every doc with its summary |
| `check` | Lint the docs (use `--strict` in CI) |
| `conflicts [id...]` | Statements in different docs that contradict each other |
| `init`, `import` | Set up a repository; split a large markdown file into docs |
| `mcp`, `serve` | The MCP server on stdio; the HTTP JSON API |

`search`, `read`, `list`, `check`, `conflicts`, `sync` and `status` also take `--json`. See the
[CLI reference](knowledge/interfaces/cli.md),
[MCP server](knowledge/interfaces/mcp-server.md) and [HTTP API](knowledge/interfaces/http-api.md).

## Writing docs

One topic per file. The path is the id, and front matter is optional but makes results
much better:

```markdown
---
title: Rolling back a deploy
summary: When and how to roll back production, and what must never be rolled back.
tags: [deploy, runbook]
keywords: [revert, undo release]
---

# Rolling back a deploy
...
```

See [Writing knowledge docs](agentindex/templates/writing-docs.md).

## This repository

AgentIndex documents itself with its own index. [CLAUDE.md](CLAUDE.md) is 14 lines, and
[knowledge/](knowledge/) holds the design docs. Start with
[Start here](knowledge/start-here.md), then read about the
[architecture](knowledge/architecture/overview.md) and
[search ranking](knowledge/architecture/search-ranking.md).

```bash
python3 -m unittest                      # run the tests
python3 -m agentindex check --strict     # lint the knowledge base
```
