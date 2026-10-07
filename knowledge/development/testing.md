---
title: Testing
summary: How to run the test suite, how the tests are organized, and what each kind of change needs tested.
tags: [development, testing]
keywords: [tests, unittest, pytest, ci, github actions, run tests, test suite, fixtures, python 3.9]
---

# Testing

The suite uses only the standard library's `unittest`:

```bash
python3 -m unittest discover -s tests           # everything, a few seconds
python3 -m unittest tests.test_search -v        # one module
python3 -m agentindex check --strict            # this repo's knowledge base
```

pytest runs the same tests (`python3 -m pytest tests`) if you have it, but nothing requires
it. CI ([.github/workflows/ci.yml](../../.github/workflows/ci.yml)) runs both commands on
Python 3.9 and the newest Python on Linux, and on the newest Python on macOS and Windows.

## Layout

| Module | Covers |
|---|---|
| `test_frontmatter.py`, `test_markdown.py` | Parsing: the YAML subset, headings inside and outside code fences, anchors, sections, links, summaries. |
| `test_query.py` | Query parsing and the FTS5 expressions it produces. |
| `test_store.py` | Sync (adding, changing and deleting files, duplicate ids), read, outline, list, check, schema rebuilds. |
| `test_search.py` | Ranking expectations on a small, realistic corpus. Add a case here whenever a query ranks badly. |
| `test_cli.py`, `test_http_api.py`, `test_mcp_server.py` | The three interfaces, end to end. The HTTP and MCP tests talk to real servers. |
| `test_scaffold.py` | `init` and `import`. |
| `test_knowledge_base.py` | This repo's own docs pass `check --strict` and answer key questions. |

[tests/helpers.py](../../tests/helpers.py) builds throwaway projects in a temporary
directory: `make_project({"knowledge/a.md": "..."})` writes the files and returns the root.

## What to test

- A parsing change needs a unit test with the exact markdown that motivated it.
- A ranking change needs its motivating query in `test_search.py`, and the existing cases
  must still pass.
- A new CLI option, endpoint or tool argument needs a test through that interface.
- Run the suite on Python 3.9 when you can (`uv python install 3.9`), because CI does.
