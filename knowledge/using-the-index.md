---
title: Using the index
summary: How agents should search and read the knowledge base. Covers query tips, reading single sections, and the CLI, MCP and HTTP interfaces.
tags: [usage, agents]
keywords: [search, query, read, how to search, tips, workflow, mcp tools, search_docs, read_doc, list_docs, find docs]
---

# Using the index

Search first, read narrowly, then go to the code. A typical loop:

1. `search` with a few keywords for what you are about to work on.
2. Scan the results. Each one shows the doc id, title, summary, and its best-matching
   sections with a snippet.
3. `read` the best doc, or just the section that matched (`<id>#<anchor>`).
4. Follow "Links to" at the end of the doc, or its links into the code, to go deeper.

## Writing queries

- Use the words the docs would use, such as `migration rollback`. Questions work too,
  because stop words like "how" and "the" are dropped.
- Docs matching more of your words rank higher, so add a word to narrow the results and
  remove one to broaden them.
- Words match as prefixes: `auth` finds "authentication" and `config` finds
  "configuration". Plurals and verb forms match each other (`deploys`, `deploying`, `deploy`).
- `"exact phrase"` requires the phrase, and `-word` excludes docs containing that word.
- `--tag <tag>` (CLI), `tags` (MCP) or `tag=` (HTTP) keeps only docs with that tag. `list`
  shows every tag.

Details of the ranking: [architecture/search-ranking](architecture/search-ranking.md).

## Reading only what you need

- `read <id>` prints the whole doc with its file path. At the end it lists the docs it
  links to and the docs that link to it.
- `read <id>#<anchor>` prints one section, including its subsections. Anchors are the
  GitHub-style heading slugs shown in search results; the heading text works too.
- `read <id> --outline` lists a doc's headings with anchors and word counts, so you can
  pick one section of a long doc.
- Doc ids are paths inside `knowledge/` without the `.md`. File paths and unique endings
  of an id (`overview` for `architecture/overview`) also work.

## Interfaces

All three run the same code against the same index:

| | Search | Read | Browse |
|---|---|---|---|
| CLI | `python3 -m agentindex search <words>` | `read <id>[#anchor]` | `list` |
| MCP | `search_docs(query)` | `read_doc(id, section, outline)` | `list_docs(tags)` |
| HTTP | `GET /search?q=<words>` | `GET /docs/<id>?section=<anchor>` | `GET /docs` |

References: [CLI](interfaces/cli.md), [MCP server](interfaces/mcp-server.md),
[HTTP API](interfaces/http-api.md).

The index updates itself before every query, so a doc you just edited is searchable right
away.
