---
title: Contradiction detection
summary: How `agentindex conflicts` finds statements in different docs that disagree. Covers what counts as a statement and a contradiction, the rules that keep false positives down, how it was tuned, and what it cannot see.
tags: [architecture, maintenance]
keywords: [contradictions, conflicts, inconsistencies, inconsistent docs, disagree, drift, stale facts, duplicated facts, consistency, false positives]
related: [architecture/search-ranking, interfaces/cli]
---

# Contradiction detection

Knowledge bases drift: a fact gets written in two docs, then only one of them is updated,
and agents believe whichever copy they find first. `agentindex conflicts` finds such pairs.
Code: [conflicts.py](../../agentindex/conflicts.py) and `conflicts()` in
[store.py](../../agentindex/store.py).

Like search, it is lexical and never calls a model. It compares statements that nearly
repeat each other, so it catches copies that drifted apart, not claims worded differently.
Every result is a candidate for an agent or a person to check against the code, which is
why the command exits 0 when it finds some and is not meant as a CI gate.

## What it reports

Pairs of statements from different docs that differ in exactly one way:

| Kind | Example |
|---|---|
| Different values: numbers, versions, code spans, names | "The API listens on port **8765** by default." and "...port **8080** by default." |
| Opposite meanings: a negation, or opposite words | "Caching is **enabled** by default." and "Caching is **disabled** by default." |

Statements that make the same claim are grouped, so a result lists every place that says
8765 and every place that says 8080. The odd one out is usually the stale one.
`conflicts <id>...` reports only results involving those docs, which is the quick check
after editing one.

## Statements and terms

Each doc is split into sentences (and clauses at semicolons), list items and table rows.
Code blocks, including fences indented inside list items, comments, headings, HTML and link
definitions are not statements. Neither are lead-ins that end in a colon ("Run these
commands:"), statements that are only code, or ones with fewer than 3 or more than 60 terms.

A statement's terms are what gets compared:

- **Words**, lowercased and lightly stemmed ("defaults", "defaulted" and "default" match),
  without function words. "See" and "refer" count as function words, because they
  introduce references rather than claims.
- **Values**: numbers, versions and dates, URLs, flags, identifiers such as `file.py` or
  `snake_case`, everything in a code span, and capitalized names mid-sentence (Redis,
  GitHub).
- **Negations**: "not", "no", "never", "without", "n't" and the like, which all compare
  equal, so "never" and "do not" agree.

## Deciding that two statements disagree

1. **Candidates.** Statements whose terms overlap enough (Dice coefficient at least 0.5).
   Prefix filtering finds them without comparing every pair: statements that similar must
   share one of their rarest terms.
2. **Alignment.** `difflib` aligns the two term sequences. Words that only moved ("by
   default, X" and "X by default") do not count as differences; values that swapped
   places do.
3. **One difference.** Either the values differ in exactly one place, or the statements
   have an odd number of negations and opposite words between them (enabled and disabled,
   required and optional, before and after, supported and unsupported). So "not required"
   and "optional" agree.

Then the pair must pass guards, each added for false positives seen while tuning:

- **Something in common comes first.** Statements that start differently have different
  subjects: "`search` takes `--json`" and "`list` takes `--json`".
- **No word swapped elsewhere.** "In development, the API listens on port 8765" and "In
  production, ... port 443" disagree about the context, not the port.
- **Alike apart from the difference.** Leaving out the differing terms, the rest must be
  at least 75% alike and share at least 2 terms. The less they share, the fewer extra terms
  either may have: none at 2 shared terms, 1 at 3, and 2 from 4 up.
- **Not links to different pages.** When the differing words on both sides include a
  link's text, the statements point to different pages, as in
  `See [Configuration](config.md)` and `See [Testing](testing.md)`.
- **Not sections about different things.** Statements under headings that name different
  things (a code span, a flag or an identifier such as `--force`, `max_retries` or
  `v0.2.0`) are about those things.
- **Not each naming its own doc.** The npm-ci doc says "run `npm ci`", the npm-install doc
  "run `npm install`".
- **Not a template.** A sentence that its own doc repeats with other values, once per
  option or environment, depends on where it is. So does a sentence found in more than 3
  versions across the docs, such as a footer with each doc's review date: one fact that
  drifted rarely has more than two or three.
- **Different docs only.** A doc's own lists and tables repeat sentence patterns on
  purpose, so a doc is never compared with itself.

## How it was tuned

The thresholds are at the top of [conflicts.py](../../agentindex/conflicts.py), and the
pair behind each rule is in `tests/test_conflicts.py`, as a case it must reject next to one
it must still report. They were tuned on:

- This knowledge base: no results, and `tests/test_knowledge_base.py` keeps it that way.
- npm's 83 docs, which repeat option descriptions across commands: 2 results, one of them a
  real inconsistency ("use `offline`" next to "use `--offline`").
- npm 10.5's docs next to 10.9's: both value changes between the versions found.
- Hand-written pairs in `tests/test_conflicts.py`: contradictions it must find, and
  similar statements that do not contradict each other.

It takes about half a second for 3,500 statements and 5 seconds for 18,000.

## Limits

- Contradictions worded differently are not found, for example "Use Postgres" and "The
  database is MySQL". Reading the docs that search returns for a topic is the way to find
  those.
- Changelogs and option references whose headings are plain words can produce false
  positives: "Default: `true`" under one option and "Default: `false`" under another.
- The word lists (function words, negations, opposites) are English.

## Resolving a result

Check both statements against the code. Fix the doc that is wrong, or, if both are right,
reword them so the difference is explicit (name the environment, version or option). Then
keep the fact in one doc and link to it from the others, so it cannot drift again.
