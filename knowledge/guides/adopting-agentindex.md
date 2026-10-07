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

## 3. Migrate an existing CLAUDE.md

```bash
agentindex import CLAUDE.md --dry-run   # preview
agentindex import CLAUDE.md             # one doc per "##" section
```

`import` writes one doc per `##` section (`--level 3` splits more finely), each with title
and summary front matter and its headings shifted up a level. Text before the first section
becomes `overview.md`. Then:

1. **Curate.** Give every doc a summary that says what it answers, and add `tags` and
   `keywords`. Merge fragments, split mixed topics, and group docs into folders as the set
   grows (`architecture/`, `runbooks/`). The `writing-docs` doc has the details.
2. **Keep the always-on rules.** A few rules apply to every task, such as "never push to
   main" or "run the linter before committing". Leave those in CLAUDE.md, because agents do
   not search for rules they do not know exist.
3. **Replace the rest** with the pointer that `init` and `import` print. The template is
   [agentindex/templates/CLAUDE.md](../../agentindex/templates/CLAUDE.md).
4. **Fill in `start-here`** with a short map of the project and its docs.
5. Run `agentindex check` until it is clean.

## 4. Keep it healthy

Run the check in CI, so broken links and stale code references fail the build:

```yaml
- run: pip install git+https://github.com/ZachBaker/AgentIndex
- run: agentindex check --strict
```

Have agents update docs in the same change as the code they describe. The pointer in
CLAUDE.md already asks them to.
