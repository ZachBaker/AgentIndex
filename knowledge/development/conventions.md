---
title: Code conventions
summary: Rules for changing AgentIndex. Standard library only, Python 3.9 compatible, one core with thin interfaces, user-facing errors, stable output, and docs updated with the code.
tags: [development, conventions]
keywords: [style, coding standards, guidelines, contributing, dependencies, python version, compatibility, errors, versioning, release, schema version]
---

# Code conventions

## Hard rules

- **Standard library only.** No runtime dependencies, ever. The tool must run in any
  sandbox and be vendorable by copying one folder.
- **Python 3.9 compatible.** Use `from __future__ import annotations` for modern type
  hints, but nothing that needs 3.10+ at runtime: no `match`, no `X | Y` outside
  annotations, no `zip(strict=...)`, no `tomllib`.
- **Behavior lives in `KnowledgeIndex`.** The CLI, MCP and HTTP layers only validate input
  and format output. Logic that two interfaces need belongs in `store.py` (data) or
  `render.py` (text).
- **Bump `SCHEMA_VERSION`** in `store.py` when the schema or the parsing output changes, so
  existing databases are rebuilt.

## Errors

Expected problems raise subclasses of `AgentIndexError` from
[errors.py](../../agentindex/errors.py), with a message written for whoever will read it:
`ConfigError`, `QueryError`, and `NotFoundError`, which carries `suggestions`. The
interfaces turn these into exit codes, HTTP statuses or MCP `isError` results. Any other
exception is a bug and should surface as one.

## Output is an interface

Agents parse what the CLI and the MCP tools print. Keep the output of
[render.py](../../agentindex/render.py) compact and stable, and end it with the next step
to take. Change the JSON shapes, which `--json` and the HTTP API share, only on purpose,
and update the [HTTP API](../interfaces/http-api.md) doc when you do.

## Style

Keep lines under 100 characters, type-hint function signatures, give every module a
docstring that says what it is for, and comment on why rather than what. If you have
ruff (it is not required), `ruff check` and `ruff format` use the settings in
`pyproject.toml`.

## Docs

This knowledge base documents the code. A change that alters behavior also updates the doc
that describes it, in the same commit, and `python3 -m agentindex check --strict` must pass.

## Versioning

`__version__` in [agentindex/__init__.py](../../agentindex/__init__.py) is the single
source of truth; `pyproject.toml` reads it. Bump the minor version for new commands or
options, and the patch version for fixes.
