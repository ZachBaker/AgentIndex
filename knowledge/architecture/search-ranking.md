---
title: Search ranking
summary: How a free-text query becomes an FTS5 match expression and how results are scored. Covers stop words, prefixes, phrase pairs, per-field BM25 with a smoothed IDF, and how sections are picked.
tags: [architecture, search]
keywords: [bm25, bm25f, fts5, relevance, scoring, idf, weights, stemming, porter, query parsing, snippets, tuning, ranking quality]
related: [architecture/database]
---

# Search ranking

Search is lexical. SQLite FTS5 with the porter stemmer finds the matching docs, and
AgentIndex scores them itself with per-field BM25. Code: [query.py](../../agentindex/query.py)
and `search()` in [store.py](../../agentindex/store.py).

## From query to match expression

`parse_query()` turns free text into phrases that FTS5 can always match:

1. `"quoted phrases"` become required phrases, and `-word` becomes an exclusion.
2. The rest is split the way FTS5's tokenizer splits text (runs of letters and digits, so
   `_` and punctuation separate words) and lowercased. Stop words such as "how", "the" and
   "do" are dropped, unless the query is nothing but stop words.
3. Each remaining term matches exactly and, for terms of three or more letters, as a
   prefix. So `auth` finds "authentication", and exact matches count twice.
4. Words that are adjacent in the query, with no stop word or punctuation between them,
   are added as two-word phrases, so `feature flag` ranks docs containing that exact
   phrase first.

The match expression is `(alternatives) AND required phrases NOT exclusions`. Every token
is quoted, so no input can cause an FTS5 syntax error. A doc matches if it contains any
alternative, which keeps recall high and leaves the rest to ranking.

For example, `how do I roll back a deploy?` gives the terms `roll`, `back` and `deploy`
and the pair `"roll back"`.

## Scoring documents

Every doc has six indexed fields:

| title | keywords and doc id | tags | summary | headings | body |
|---|---|---|---|---|---|
| 3.0 | 2.0 | 1.5 | 1.5 | 1.5 | 1.0 |

For each phrase, `bm25()` runs once per field, with every other field's weight set to
zero, so each field's term frequency saturates on its own. The per-field results are
combined with the weights above. FTS5's IDF is divided back out and replaced with a
smoothed IDF, `ln(1 + (N - n + 0.5) / (n + 0.5))`, where `N` is the number of docs and
`n` the number containing the phrase. A doc's score is the sum over all phrases.

Plain `bm25()` is not used directly, because it misranked small knowledge bases in two ways:

- **IDF clamping.** FTS5 computes `ln((N - n + 0.5) / (n + 0.5))` and clamps it to 1e-6
  for any phrase found in half the docs or more. In a small knowledge base many words are
  that common, and they then count for nothing next to rarer ones. Searching
  `redis session timeout` where most docs mention sessions and timeouts, a doc that
  mentioned redis once outranked the doc about session timeouts.
- **Single saturation.** `bm25()` adds the weighted counts of all fields into one term
  frequency, so a word appearing in a doc's tags, summary and one heading added up to
  nearly as much as a doc titled and written about it. `how do I roll back a deploy?`
  ranked a migrations doc (with a "Rolling back" heading and `deploy` in its tags) above the
  doc about deploying. Saturating each field separately rewards docs about the topic.

Both cases are tests in `tests/test_search.py`, which also check that plain `bm25()` still
gets them wrong, so the tests keep guarding something real.

This costs two small SQL queries per phrase (docs and sections), which takes milliseconds
on a corpus the size of a knowledge base.

## Picking sections and snippets

Sections are indexed separately, with fields for the heading (2.0), the parent headings
and doc title (0.5), and the body (1.0), and scored the same way. Each result shows its
two best sections with an FTS5 snippet of the section body, where `**` marks the matched
words. The indexed text is plain text: link targets, emphasis and HTML are dropped, and
code blocks are kept.

## Tuning

The weights are at the top of `store.py` (`DOC_WEIGHTS`, `SECTION_WEIGHTS`). Before
changing them, add the query that ranks badly to `tests/test_search.py` and make sure the
other cases still pass. Often the better fix is in the docs: a sharper title or summary,
or `keywords` with the words people actually search for.
