# CLAUDE.md

Project knowledge (architecture, conventions, workflows, gotchas) lives in a
searchable index of `knowledge/`, not in this file. **Search it before you explore
code or make changes**, then read only what you need:

- `python3 -m agentindex search "<keywords>"` (MCP tool: `search_docs`)
- `python3 -m agentindex read <id>`, or `<id>#<section>` for one section (MCP: `read_doc`)
- `python3 -m agentindex list` to browse everything (MCP: `list_docs`)

New here? Start with `python3 -m agentindex read start-here`.

Learned something the next agent will need? Add or update a doc in `knowledge/`
(how: `python3 -m agentindex read writing-docs`), then run `python3 -m agentindex check`.
