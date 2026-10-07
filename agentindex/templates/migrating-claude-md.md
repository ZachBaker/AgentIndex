---
title: Migrating a CLAUDE.md into the knowledge base
summary: Checklist for an agent moving a large CLAUDE.md into knowledge docs. Restructure the file so import splits it well, import it, curate the docs, and slim CLAUDE.md down to the pointer.
tags: [guide, setup, migration]
keywords: [import, claude.md, restructure, preprocess, split, headings, slim down, migrate, setext, bold headings]
---

# Migrating a CLAUDE.md into the knowledge base

This checklist is for the agent doing the migration. `agentindex import` splits a file
into one doc per `##` section, so the result is only as good as the file's structure.
The work has three parts: restructure the file so each topic sits under its own heading,
import it, then curate the docs it creates. Print this guide at any time with
`agentindex import --guide`. Commands are written `agentindex <command>`; use the exact
invocation from CLAUDE.md (for example `python3 -m agentindex`).

## What import fixes on its own

Import converts headings that the index would not recognize, and lists each conversion:

- **Setext headings**, text underlined with `===` or `---`, become `#` and `##` headings.
- **Bold lines used as headings**, such as `**Testing**` or `**Testing:**` on a line of
  their own, become a heading one level below the section they are in. Bold sentences
  such as `**Never push to main.**` are left alone, because they are rules, not headings.

It also warns when there is nothing to split at (everything would land in `overview.md`)
and when a section is too long to be one doc. Start every import with `--dry-run` and
read the conversions and warnings before writing anything.

## 1. Restructure the file

Edit CLAUDE.md in place. It is in git, so the change can be reviewed as a diff. The goal
is one topic per `##` section, with a heading that names the topic.

- **Move text, do not rewrite it.** Keep every rule, command, path and caveat word for
  word. Rewording comes later, in the docs, where it can be reviewed one doc at a time.
  Never drop something because it looks out of date; flag it to the user instead.
- **Group by topic.** Gather notes about one subject that are scattered through the file
  (testing advice in three places, say) under one `## Testing` heading.
- **Split mixed sections.** "Setup and deployment" becomes `## Setup` and `## Deployment`.
  Use `###` for subtopics that belong together.
- **Name topics the way people search.** Headings become doc titles and file names:
  "Running the tests" beats "Notes", "Misc" or "Important".
- **Collect the always-on rules.** Rules that apply to every task ("never push to main",
  "run the linter before committing") go under one `## Rules for every task` heading.
  They stay in CLAUDE.md, because agents do not search for rules they do not know exist.
- **Keep sections under about 1,500 words.** Split longer ones into separate topics.
- **Leave code blocks alone.** Headings inside fences are never treated as headings.

Check nothing was lost: the word count (`wc -w CLAUDE.md`) should be about the same
before and after, and `git diff` should show moved lines, not changed ones.

## 2. Import

```bash
agentindex import CLAUDE.md --dry-run   # read the conversions, docs and warnings
agentindex import CLAUDE.md             # write one doc per section
```

- If a warning says everything went into one doc, add headings or use the `--level` it
  suggests. `--level 3` splits at `###` as well.
- Use `--into knowledge/<folder>` to put the docs in a subfolder.
- Existing docs are skipped unless you pass `--force`.

## 3. Curate the docs

Import gives every doc a title and a summary taken from its first paragraph. Then:

- **Delete the always-on rules doc** (`rules-for-every-task.md`); those rules go back
  into CLAUDE.md in the next step.
- **Rewrite each summary** to say what the doc answers. Search results show it under
  every hit, so it decides whether an agent opens the doc.
- **Add `tags` and `keywords`**: keywords are the words people search for that are not in
  the text, such as synonyms, abbreviations and old names.
- **Merge fragments** of a few sentences into the doc they belong with, and group docs
  into folders as the set grows (`architecture/`, `runbooks/`).
- **Link to code** with relative links, so `agentindex check` notices when it moves.

`agentindex read writing-docs` covers the doc format in detail.

## 4. Replace CLAUDE.md

Replace the file with the pointer that `import` printed, then add the always-on rules
under it. The result should be a few dozen lines at most. Anything longer belongs in a
doc.

## 5. Verify

- Run `agentindex check` and fix everything it reports.
- Run `agentindex conflicts`. A CLAUDE.md that grew over time often says one thing in two
  places, differently, and the import has now put them in different docs. Check each
  result against the code, and ask the user when the code does not settle it.
- For each section of the old CLAUDE.md, search with the words someone would use when
  they need it (`agentindex search "<question>"`), and confirm the right doc is in the
  top three. If it is not, improve that doc's title, summary or keywords.
- If `init` created `.claude/skills/migrate-claude-md/`, delete it; the migration is done.
