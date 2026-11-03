---
title: Benchmarks on real knowledge bases
summary: How bench/ measures AgentIndex on real projects' docs with questions from real tasks. Covers the corpora, how questions were written and labeled, the baselines, the token cost model, running it, and its limits.
tags: [development, testing, search]
keywords: [benchmark, evaluation, eval, performance, retrieval quality, accuracy, hit rate, mrr, tokens saved, context cost, latency, speed, real world, use cases, grep baseline]
---

# Benchmarks on real knowledge bases

`bench/` measures whether AgentIndex finds the right doc for questions agents really
ask, how much text the agent reads to get the answer, and how fast it is, on real
projects' knowledge bases. `python3 -m bench run` writes the numbers to `bench/results.md`.

```bash
python3 -m bench fetch    # once: sparse checkouts of the pinned corpora into bench/.cache/
python3 -m bench check    # every labeled answer exists in its corpus
python3 -m bench run      # writes bench/results.md and bench/results.json (about a minute)
```

`run` and `check` fetch whatever is missing, and all three take corpus names to limit the
run, such as `python3 -m bench run node-contributing`. The harness needs git and network
access only to fetch; the unit tests in `tests/test_bench.py` run offline on a toy corpus.

## The corpora

[bench/corpora.json](../../bench/corpora.json) pins each corpus to a commit:

- Four documentation folders, indexed as they are: the Rust compiler's rustc-dev-guide,
  Node.js's `doc/contributing`, Electron's `docs`, and GitLab's `doc/development` (668 docs,
  about a million words).
- Three large AGENTS.md files (PostHog, Next.js, Cloudflare workerd), split with
  `agentindex import` and its defaults, as an adopter would.

Nothing is tuned per corpus: no excludes, no keywords added, no edits after import. The
numbers are what a team gets on day one.

## The questions

Each corpus has cases in `bench/cases/<corpus>.json`. They were made in two separate
passes, so that questions do not copy the docs' wording, which would flatter any
keyword search:

1. **Written blind.** Questions came from real merged PRs in the project (the `pr` and
   `task` fields) or, for Electron app developers, common app-building tasks. The writer
   saw only the PR titles and a one-paragraph description of what the docs cover, never the
   docs. Each question is phrased twice: as a natural question (`question`) and as the
   few words an agent types into a search box (`keywords`).
2. **Labeled separately.** Another pass read the docs and recorded every doc, and the
   most specific section, that answers each question, without using AgentIndex search.
   Questions the docs do not answer were moved to `dropped`, with the reason.

## Systems compared

| System | What it is |
|---|---|
| AgentIndex | `KnowledgeIndex.search`, as the CLI and MCP server run it. |
| FTS5 `bm25()` | The same index and match expression ranked by SQLite's built-in function: measures what AgentIndex's own scoring adds. |
| grep | An agent without an index: files ranked by how many of the query's words they contain (case-insensitive substrings), then by matching lines, and read whole. |
| Load everything | The whole knowledge base, or the whole AGENTS.md, in context in every session. |

Retrieval is scored as the share of cases whose answering doc is ranked first, and is in
the top 3, with a 95% Wilson interval. "Points at the section" counts results whose first
section contains the answer.

## Cost model

Tokens are estimated as characters / 4. Per lookup, the AgentIndex agent reads the search
output (8 results, as the CLI and MCP tool return), then reads the section each result
points at, in rank order, until it reaches an answering doc. If that section does not
contain the answer it also reads the whole doc; a doc that answers as a whole is read
whole. The grep agent reads 20 lines of match counts, then whole files in rank order.
Both stop after 3 reads, and a miss costs all of them. AgentIndex also costs its CLAUDE.md
pointer once per session. "Lookups before AgentIndex costs more" divides what loading
everything costs per session by the median lookup.

Reading whole files makes the simulated grep agent an upper bound: real agents grep, then
read only the matching part of a file. Compare costs against grep with the
[real agents](#real-agents) instead.

## Speed

Measured on whatever machine runs it: building the index from scratch (the first query
does this once), searching in-process including the per-query file check, and a whole
`python3 -m agentindex search` process from start to output.

## Real agents

The simulated agents above are deterministic and cheap to rerun. To check them against
real behavior, every question was also given to real coding agents, with results in
`bench/pilot.md`. For each question, two fresh agents in the Claude
Code harness, with the same model and one run each, looked up the answer:

- one could read the docs only through `python3 -m agentindex search` and `read`;
- the other could use only grep, find and file reads on the docs folder, or, for the
  AGENTS.md corpora, had to read the whole AGENTS.md first.

Two judges, blind to which agent was which, graded each answer against the labeled docs as
correct, partly correct, wrong or "the docs don't answer it", with a third judge where they
disagreed. Context added, doc text read, tool calls and time come from the agents'
transcripts. This needs an agent harness, so `python3 -m bench run` does not repeat it.

## Changing ranking or output

Run the benchmark before and after any change to [query.py](../../agentindex/query.py),
the weights in [store.py](../../agentindex/store.py) or search output, and say what changed
in the PR. The cases are a test set, not a tuning set: fix a ranking problem found here by
adding its query to `tests/test_search.py` first, as
[search ranking](../architecture/search-ranking.md#tuning) describes, and do not edit
cases to match results. Re-label only when an answer is wrong, judging it without looking
at which system returned it.

## Adding a corpus or cases

Add the corpus to `corpora.json` with its commit, then write questions blind and label
them in a separate pass, as above. Keep `pr` and `task` so every case traces to a real
task, and keep dropped questions with their reasons. `python3 -m bench check` catches
answers that name a missing doc or section.

## Limits

- One writer and one labeler per corpus; labels are judgement calls, and some questions
  have answers the labeler missed. Re-label in the open when you find one.
- Lexical search cannot match a question to a doc that shares none of its words. The
  misses listed in the results are mostly that.
- Tokens are estimated, not counted with a tokenizer, and the agents are simulated: real
  agents also skim, reformulate queries and stop early.
- Speed depends on the machine; compare runs from the same one.
