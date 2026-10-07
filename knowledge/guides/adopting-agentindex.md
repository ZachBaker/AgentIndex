---
title: Adopting AgentIndex in a repository
summary: Step-by-step guide to adding AgentIndex to a project. Install or vendor it, run init, migrate an existing CLAUDE.md with import, and add check to CI.
tags: [guide, setup]
keywords: [install, setup, migrate, migration, shrink claude.md, vendor, pip, uv, init, import, ci, github actions, new repository]
---

# Adopting AgentIndex in a repository

The goal is a CLAUDE.md of about a dozen lines that points at a searchable knowledge base,
instead of hundreds of lines loaded into every session.

## 1. Make the tool available

Pick one:

- **Install it.** It needs Python 3.9+ and has no dependencies:
  `pip install git+https://github.com/ZachBaker/AgentIndex` or
  `uv tool install git+https://github.com/ZachBaker/AgentIndex`. The command is `agentindex`.
- **Vendor it.** Copy the `agentindex/` package folder into the repository root, and run it as
  `python3 -m agentindex` from the root. There is nothing to install, which suits cloud
  sandboxes.

## 2. Run init

```bash
agentindex init            # or: python3 -m agentindex init
```

It creates the following, and never overwrites anything:

- `.agentindex.json`, indexing `knowledge/` (`--dir` picks another folder)
- `knowledge/start-here.md` and `knowledge/writing-docs.md`
- a `.agentindex/` entry in `.gitignore`
- an `agentindex` server in `.mcp.json` (skip it with `--no-mcp`)
- a `CLAUDE.md` containing the pointer, if the repository has none
- if the repository already has a CLAUDE.md that does not mention AgentIndex, a
  `/migrate-claude-md` Claude Code skill in `.claude/skills/migrate-claude-md/` that walks an
  agent through step 3; delete it once the migration is done

## 3. Migrate an existing CLAUDE.md

```bash
agentindex import --guide               # the agent's checklist for the whole migration
agentindex import CLAUDE.md --dry-run   # preview
agentindex import CLAUDE.md             # one doc per "##" section
```

`import` writes one doc per `##` section (`--level 3` splits more finely), each with title
and summary front matter and its headings shifted up a level. Text before the first section
becomes `overview.md`. Before splitting, it converts headings the index would not see:
setext headings (underlined with `===` or `---`) and short lines that are only bold text
(`**Testing**`), which become a heading one level below their section. It lists each
conversion, and warns when there is nothing to split at or a section is too long for one doc.

Import only fixes formatting. Grouping scattered notes by topic and naming the topics
takes judgement, so the agent running the migration does it, following the checklist from
`agentindex import --guide` ([migrating-claude-md](../../agentindex/templates/migrating-claude-md.md)).
AgentIndex itself never calls a model. In Claude Code, the `/migrate-claude-md` skill
that `init` creates runs the same checklist. In outline:

1. **Restructure first.** Move each topic under its own `##` heading with a descriptive
   name, without rewriting or dropping text, and collect the rules that apply to every task
   under one heading.
2. **Import**, dry run first.
3. **Curate.** Give every doc a summary that says what it answers, and add `tags` and
   `keywords`. Merge fragments, split mixed topics, and group docs into folders as the set
   grows (`architecture/`, `runbooks/`). The `writing-docs` doc has the details.
4. **Keep the always-on rules.** A few rules apply to every task, such as "never push to
   main" or "run the linter before committing". Leave those in CLAUDE.md, because agents do
   not search for rules they do not know exist.
5. **Replace the rest** with the pointer that `init` and `import` print. The template is
   [agentindex/templates/CLAUDE.md](../../agentindex/templates/CLAUDE.md).
6. **Fill in `start-here`** with a short map of the project and its docs.
7. Run `agentindex check` until it is clean, and resolve what `agentindex conflicts`
   reports.

## 4. Keep it healthy

Run the check in CI, so broken links and stale code references fail the build:

```yaml
- run: pip install git+https://github.com/ZachBaker/AgentIndex
- run: agentindex check --strict
```

Have agents update docs in the same change as the code they describe. The pointer in
CLAUDE.md already asks them to.

From time to time, run `agentindex conflicts` to find docs that contradict each other. Its
results are candidates to check rather than errors, so it stays out of CI.
