---
title: Writing knowledge docs
summary: How to write docs for the knowledge index. Covers the file format, front matter fields, structure, linking, and what belongs in docs versus CLAUDE.md.
tags: [docs, conventions]
keywords: [front matter, frontmatter, metadata, summary, tags, keywords, style, contributing, documentation, add a doc, new doc]
---

# Writing knowledge docs

The knowledge base is a folder of markdown files that AgentIndex indexes for search.
Agents find docs through search results, which show each doc's title, summary and
best-matching sections, so those carry most of the weight. Commands below are
written `agentindex <command>`; use the exact invocation from CLAUDE.md (for
example `python3 -m agentindex`).

## File format

One topic per markdown file. A doc's id is its path inside the knowledge folder,
minus the extension: `deploy/rollback.md` is read with `agentindex read deploy/rollback`.

```markdown
---
title: Rolling back a deploy
summary: When and how to roll back production, and what must never be rolled back.
tags: [deploy, runbook]
keywords: [revert, undo release, rollback]
related: [deploy/overview]
---

# Rolling back a deploy

Lead with the answer...
```

## Front matter fields

| Field | What it is for |
|---|---|
| `title` | Shown in results and weighted highest in search. Defaults to the first `# Heading`. |
| `summary` | One or two sentences shown under every search result: say what the doc answers. Defaults to the first paragraph (`description` also works). |
| `tags` | A few broad categories, for filtering (`--tag`) and search. |
| `keywords` | Words people search for that are not in the text: synonyms, abbreviations, old names. |
| `related` | Ids of docs to read next, shown at the end of the doc. |

Any other field (say `owner` or `status`) is kept as metadata but not searched.
Front matter is simple YAML: `key: value`, `[inline, lists]`, `- block` lists,
and `>` folded text.

## Write for search and partial reads

- **One topic per doc**, roughly 200 to 1,500 words. Split anything longer: agents
  read whole docs or single sections, and focused docs waste less context.
- **Descriptive headings.** Every heading is a section that can be read on its own
  (`agentindex read <id>#<anchor>`) and shows up in results, so "Rolling back a
  migration" beats "Notes".
- **Lead with the answer.** The first paragraph becomes the summary if you do not set one.
- **Use the words people search for**, and put the rest in `keywords`.
- **Point at code** with relative links such as `[deploy.py](../../src/deploy.py)`;
  `agentindex check` flags them when the code moves.
- **Link related docs** with relative markdown links. Readers see them as
  "Links to" and "Linked from" at the end of a doc.

## What goes where

- **CLAUDE.md**: only the pointer to this index, plus rules that apply to every
  single task. Agents do not search for rules they do not know exist.
- **Knowledge docs**: everything else, including architecture, how-tos,
  conventions, runbooks, decisions and their reasons, and gotchas.
- **Code comments**: details that only matter while editing that exact code.

## Keeping docs healthy

Run `agentindex check` after editing docs, and in CI. It reports broken links (to
docs or code), links to missing sections, duplicate ids, and docs without a title
or summary; `--strict` also fails on warnings. When a change alters behavior that
a doc describes, update the doc in the same change.

After changing a fact, run `agentindex conflicts <id>` with the doc's id. It lists
statements in other docs that say nearly the same thing with a different value or
the opposite meaning: usually copies of the old fact. Without an id it checks every
doc. Better still, state each fact in one doc and link to it from the others.
