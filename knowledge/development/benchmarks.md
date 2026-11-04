---
title: Benchmarks on real knowledge bases
summary: How bench/ measures AgentIndex on seven real projects' docs with questions from real tasks, and what it found. Covers the corpora, how questions were written, labeled and judged, the baselines, the cost model, the real-agent runs, choosing ranking changes without overfitting, and the limits.
tags: [development, testing, search]
keywords: [benchmark, evaluation, eval, performance, retrieval quality, accuracy, hit rate, mrr, tokens saved, context cost, latency, speed, real world, use cases, grep baseline, real agents, pooled judging, relevance judgments, labeling, dev test split, held out]
---

# Benchmarks on real knowledge bases

`bench/` measures AgentIndex on real projects' knowledge bases: whether search finds the
doc that answers questions agents really ask, how much text an agent reads to get the
answer, and how fast it is. There are two sets of results:

- [bench/results.md](../../bench/results.md): simulated agents, rerun with one command.
  Retrieval, context cost and speed for AgentIndex and three baselines.
- [bench/real-agents.md](../../bench/real-agents.md): real coding agents answering every
  question with and without AgentIndex, graded blind.

```bash
python3 -m bench fetch    # once: sparse checkouts of the pinned corpora into bench/.cache/
python3 -m bench check    # every labeled answer exists in its corpus
python3 -m bench run      # writes bench/results.md and bench/results.json (about a minute)
python3 -m bench pool     # top results no one has judged yet (see below)
```

All of them fetch whatever is missing and take corpus names to limit the run, such as
`python3 -m bench run node-contributing`. The harness needs git and network access only to
fetch; the unit tests in `tests/test_bench.py` run offline on a toy corpus.

## What it found

For 0.2.1, over 215 questions on seven knowledge bases:

- **Search finds the answer.** The answering doc was in AgentIndex's top 3 for 96% of
  natural questions and 93% of keyword queries, and ranked first for 78% of each. A grep
  agent that ranks files by how many of the query's words they contain had it in its top 3
  for 73% and 88%.
- **The scoring adds little over SQLite's own.** FTS5's `bm25()` on the same index and match
  expression ranked about as well: the same on natural questions, ahead on keyword queries
  over the big doc folders (95% against 90% in the top 3), where a narrow doc named after
  one query word can push the answer to fourth place, and behind on the small AGENTS.md
  knowledge bases (answer ranked first for 71% of questions and 77% of keyword queries,
  against 74% and 83%). What AgentIndex adds over plain FTS5 is mostly the rest: fields and
  sections, query parsing that never fails, and results that point at the section to read.
- **Real agents answered as well, with less context.** Searching doc folders with AgentIndex
  instead of grep, agents answered 99% correctly either way and added a median 7.4k tokens
  of context per lookup instead of 8.9k, in 3 tool calls instead of 4. Against reading a
  whole AGENTS.md, they added 6.8k instead of 15.0k, with 97% correct instead of 100%.
- **It matters most for big knowledge bases.** Three of the four doc folders (477k to 2.1M
  tokens) cannot be loaded into a 200k context at all; a lookup costs 2–4k tokens. An
  AGENTS.md of 7–12k tokens costs real agents only 1.6 to 3.1 times one lookup, so splitting
  one saves context only in sessions with few lookups.
- **It is fast.** A search takes a median of 4–5 ms on an AGENTS.md and 12–86 ms on the doc
  folders, and a whole CLI call, Python's start-up included, 80–220 ms. Indexing GitLab's
  668 docs (1.2M words) from scratch takes about 6 s, once.
- **It changed the ranking.** 0.2.0 weighted titles 3x and other fields up to 2x, which
  ranked narrow docs named after a query word above the answer. Equal weights did better
  on held-out questions; see
  [search ranking](../architecture/search-ranking.md#why-the-fields-are-weighted-equally).

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

Each corpus has cases in `bench/cases/<corpus>.json`, made in three separate steps, so that
questions do not copy the docs' wording, which would flatter any keyword search, and labels
do not favor any system:

1. **Written blind.** An agent wrote 40 questions per doc folder, and 36 per AGENTS.md,
   from the project's recently merged PRs (the `pr` and `task` fields) or, for Electron's
   app developers, common app tasks. It saw only the PR titles and a paragraph on what the
   docs cover, never the docs. Each question is phrased twice: as a natural question
   (`question`) and as the few words an agent types into a search box (`keywords`).
2. **Labeled twice.** Two labelers independently recorded every doc, and the most specific
   section, that answers each question, without using AgentIndex search: one started from
   the list of docs, the other from grep. A third agent reconciled every disagreement.
   Questions the docs do not answer were moved to `dropped`, with the reason. How often the
   labelers agreed is in the results.
3. **Pooled judging.** Labelers miss answers, and their misses favor whichever system
   searches the way they did. So every doc that any system ranked in its top 3, for either
   phrasing, and that no one had judged was judged by two judges, with a third where they
   disagreed, who were not told which system found it. Docs that answer were added to
   `answers` (and listed in `pooled`); the rest are kept in `not_answers`.
   `python3 -m bench pool` lists what is still unjudged.

Every step was done by agents in the Claude Code harness, each starting fresh.
[bench/prompts.md](../../bench/prompts.md) has their prompts word for word.

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

[bench/real-agents.md](../../bench/real-agents.md) checks the simulated agents against real
behavior. Every question, including the ones dropped as unanswered, went to two fresh
agents in the Claude Code harness, with the same model and one run each:

- one could read the docs only through `python3 -m agentindex search` and `read`;
- the other could use only grep, find and file reads on the docs folder, or, for the
  AGENTS.md corpora, had to read the whole AGENTS.md first.

Two judges, not told which agent was which, graded each answer against the labeled docs
as correct, partly correct, wrong or "the docs don't answer it", with a third judge where
they disagreed. Context added, the text the tools returned, tool calls and time come from
the agents' transcripts, and every run is in `bench/real-agents.json`. These runs used
0.2.0's ranking, and they need an agent harness, so `python3 -m bench run` does not repeat
them.

## Changing ranking or output

Run the benchmark before and after any change to [query.py](../../agentindex/query.py),
the weights in [store.py](../../agentindex/store.py) or search output, and say what changed
in the PR. The cases are a test set, not a tuning set:

- Fix a ranking problem found here by adding its query to `tests/test_search.py` first, as
  [search ranking](../architecture/search-ranking.md#tuning) describes. Do not edit cases
  to match results.
- To choose between variants, compare them with `python3 -m bench run --split dev`, then
  check the winner once with `--split test`. Each case's half is fixed by a hash of its id.
  0.2.1's field weights were chosen this way, before Electron's cases existed, so the test
  half has been used once.
- A change can put docs no one has judged into the top 3, and an unjudged doc counts as a
  miss. Run `python3 -m bench pool` and judge what it lists, blind, as above, before
  comparing.
- Re-label only when an answer is wrong, judging it without looking at which system
  returned it.

## Adding a corpus or cases

Add the corpus to `corpora.json` with its commit, then write questions blind, label them
twice and judge the pooled results, as above, with the prompts in `bench/prompts.md`. Keep
`pr` and `task` so every case traces to a real task, and keep dropped questions with their
reasons. `python3 -m bench check` catches answers that name a missing doc or section.

## Limits

- The question writers, labelers and judges are agents, not the projects' maintainers.
  They were kept apart (writers never saw the docs, labelers never ran AgentIndex search,
  judges were not told which system found a doc), but they are the same model, and it may
  know these public docs from training.
- 20 to 40 questions per corpus, so per-corpus numbers have 95% intervals of about ±15
  points. Compare totals, or the same corpus before and after a change.
- Lexical search cannot match a question to a doc that shares none of its words. The
  misses listed in the results are mostly that.
- Tokens are estimated, not counted with a tokenizer, and the simulated agents are simple:
  real agents also skim, reformulate queries and stop early. The real-agent runs cover
  that, with one model and one run per question.
- Speed depends on the machine; compare runs from the same one.
