---
name: migrate-claude-md
description: Move the knowledge in CLAUDE.md into the AgentIndex knowledge base in {docs}/. Use when asked to migrate, split or slim down CLAUDE.md, or to set up AgentIndex docs from it.
---

# Migrate CLAUDE.md into {docs}/

Print the migration guide and follow it step by step:

```bash
{cmd} import --guide
```

In short: restructure CLAUDE.md so each topic has its own `##` heading (move text, never
rewrite or drop it), run `{cmd} import CLAUDE.md --dry-run` and then without
`--dry-run`, curate the new docs, replace CLAUDE.md with the pointer that import prints
plus the rules every task must follow, and run `{cmd} check` until it is clean.

Show the user the restructured CLAUDE.md diff before importing, and ask before deleting
anything that looks out of date.

When the migration is done, delete this skill (`.claude/skills/migrate-claude-md/`).
