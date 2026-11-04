"""Run every case against AgentIndex and the baselines, and measure them.

Each case is a question from a real task with the doc (or section) that answers
it. It is asked two ways: as a natural question and as the few keywords an agent
would type. Systems compared:

- ``agentindex``: ``KnowledgeIndex.search``, exactly as the CLI and MCP server run it.
- ``bm25``: the same index and match expression ranked by SQLite FTS5's built-in
  ``bm25()``, to measure AgentIndex's own scoring.
- ``grep``: what an agent without an index does. Files are ranked by how many of
  the query's words they contain (case-insensitive substrings, like ``grep -i``),
  then by how many lines match, and read whole.
- loading everything: the whole knowledge base, or the whole agent instructions
  file, in context in every session.

Costs are approximate tokens (characters / 4) of the text an agent reads to reach
the answer. AgentIndex: the search output, then ``read`` of the section each result
points at (the whole doc when the answer is elsewhere in it) in rank order until the
answering doc, at most ``READS`` reads. grep: the top of the match listing, then
whole files in rank order, at most ``READS``. A miss costs all of its reads.
"""

from __future__ import annotations

import hashlib
import json
import math
import platform
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from agentindex import KnowledgeIndex, QueryError, __version__, load_config, render
from agentindex.query import parse_query, tokenize
from agentindex.scaffold import render_template
from agentindex.store import DOC_WEIGHTS

from .corpora import BENCH_DIR, Corpus

CASES_DIR = BENCH_DIR / "cases"
REPO_ROOT = BENCH_DIR.parent
PHRASINGS = ("question", "keywords")
SPLITS = ("dev", "test")
SYSTEMS = ("agentindex", "bm25", "grep")
SEARCH_LIMIT = 8  # what search_docs and the CLI return by default
READS = 3  # docs an agent reads, in rank order, before giving up
GREP_LISTING = 20  # lines of grep output an agent looks at
CHARS_PER_TOKEN = 4
CLI_RUNS = 5
COMMAND = "python3 -m agentindex"
SEARCH_HINT = f"Read one: {COMMAND} read <id>  (or <id>#<section> for just that section)"


def split_of(case_id: str) -> str:
    """The fixed half of the cases this one is in: "dev" to choose a ranking change on,
    "test" to confirm the choice on once. Chosen by a hash of the id, so it never moves."""
    return SPLITS[int(hashlib.sha256(case_id.encode()).hexdigest(), 16) % 2]


def tokens(text: str) -> int:
    """Approximate tokens: characters / 4, the usual rule of thumb for English text."""
    return -(-len(text) // CHARS_PER_TOKEN)


@dataclass
class Case:
    id: str
    question: str
    keywords: str
    answers: list[str]  # "doc-id" or "doc-id#anchor"
    kind: str = ""
    task: str = ""
    pr: str | None = None
    note: str = ""
    not_answers: list[str] = field(default_factory=list)  # docs judged not to answer it

    def query(self, phrasing: str) -> str:
        return self.question if phrasing == "question" else self.keywords

    def wanted(self) -> dict[str, set[str]]:
        """Answering doc ids, each with the anchors that answer (empty: the whole doc)."""
        out: dict[str, set[str]] = {}
        for answer in self.answers:
            doc, _, anchor = answer.partition("#")
            out.setdefault(doc, set())
            if anchor:
                out[doc].add(anchor)
        return out


@dataclass
class CaseFile:
    corpus: str
    cases: list[Case] = field(default_factory=list)
    dropped: list[dict] = field(default_factory=list)  # blind questions the docs do not answer
    about: str = ""
    labeling: dict = field(default_factory=dict)  # how answers were labeled, and agreement


def load_cases(name: str) -> CaseFile:
    path = CASES_DIR / f"{name}.json"
    if not path.is_file():
        return CaseFile(name)
    data = json.loads(path.read_text(encoding="utf-8"))
    fields = set(Case.__dataclass_fields__)
    cases = [Case(**{k: v for k, v in c.items() if k in fields}) for c in data.get("cases", [])]
    return CaseFile(
        name, cases, data.get("dropped", []), data.get("about", ""), data.get("labeling", {})
    )


def check_cases(corpora: list[Corpus]) -> list[str]:
    """Problems with the case files: unknown docs or anchors, missing fields, duplicate ids."""
    problems = []
    for corpus in corpora:
        case_file = load_cases(corpus.name)
        with _open_index(corpus) as (index, _):
            index.sync()
            tree = _section_tree(index)
        seen: set[str] = set()
        for case in case_file.cases:
            where = f"{corpus.name}: {case.id}"
            if case.id in seen:
                problems.append(f"{where}: duplicate id")
            seen.add(case.id)
            if not case.question.strip() or not case.keywords.strip():
                problems.append(f"{where}: needs both a question and keywords")
            if not case.answers:
                problems.append(f"{where}: no answers")
            for doc, anchors in case.wanted().items():
                if doc not in tree:
                    problems.append(f"{where}: no doc {doc!r}")
                    continue
                problems += [
                    f"{where}: no section {doc}#{a}" for a in sorted(anchors) if a not in tree[doc]
                ]
            for doc in case.not_answers:
                if doc not in tree:
                    problems.append(f"{where}: no doc {doc!r} (in not_answers)")
                elif doc in case.wanted():
                    problems.append(f"{where}: {doc!r} is in both answers and not_answers")
    return problems


def pool_candidates(corpora: list[Corpus], depth: int = READS) -> dict[str, list[dict]]:
    """Docs any system ranks in its top ``depth`` that no one has judged yet, per case.

    The standard fix for answers the labeler missed: judge the pooled results of
    every system. Candidates are listed by id, not by rank or system, so whoever
    judges them cannot tell which system returned what.
    """
    pools: dict[str, list[dict]] = {}
    for corpus in corpora:
        case_file = load_cases(corpus.name)
        entries = []
        with _open_index(corpus) as (index, _):
            index.sync()
            docs = index.conn.execute("SELECT id, path FROM documents").fetchall()
            paths = {row["id"]: row["path"] for row in docs}
            files = {doc: _read(corpus.root / path) for doc, path in paths.items()}
            grep = _Grep(paths, files)
            titles = dict(index.conn.execute("SELECT id, title FROM documents").fetchall())
            for case in case_file.cases:
                judged = set(case.wanted()) | set(case.not_answers)
                found: set[str] = set()
                for phrasing in PHRASINGS:
                    query = case.query(phrasing)
                    found.update(r["id"] for r in _search(index, query)["results"][:depth])
                    found.update(_bm25_ranking(index, query)[:depth])
                    found.update(doc for doc, _ in grep.rank(query)[:depth])
                fresh = sorted(found - judged)
                if fresh:
                    entries.append(
                        {
                            "case": case.id,
                            "question": case.question,
                            "keywords": case.keywords,
                            "answers": case.answers,
                            "candidates": [
                                {"id": doc, "title": titles[doc], "path": paths[doc]}
                                for doc in fresh
                            ],
                        }
                    )
        pools[corpus.name] = entries
    return pools


def run_benchmark(corpora: list[Corpus], log=print, split: str | None = None) -> dict:
    """Run every system on every case, or only on the cases in one ``split``."""
    results = [_run_corpus(corpus, log, split) for corpus in corpora]
    return {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "environment": {
            "agentindex": __version__,
            "python": platform.python_version(),
            "sqlite": sqlite3.sqlite_version,
            "platform": f"{platform.system()} {platform.machine()}",
        },
        "settings": {
            "search_limit": SEARCH_LIMIT,
            "reads": READS,
            "grep_listing": GREP_LISTING,
            "chars_per_token": CHARS_PER_TOKEN,
            "pointer_tokens": tokens(render_template("CLAUDE.md", COMMAND, "knowledge")),
            "split": split,
        },
        "corpora": results,
        "overall": aggregate([c for r in results for c in r["cases"]]),
        "by_kind": by_kind([c for r in results for c in r["cases"]]),
    }


# -- one corpus ---------------------------------------------------------------------


class _open_index:
    """A KnowledgeIndex for the corpus on a fresh database in a temporary directory."""

    def __init__(self, corpus: Corpus, **kwargs) -> None:
        self.corpus, self.kwargs = corpus, kwargs

    def __enter__(self) -> tuple[KnowledgeIndex, str]:
        self.tmp = tempfile.TemporaryDirectory(prefix="agentindex-bench-")
        db = str(Path(self.tmp.name) / "index.db")
        self.index = KnowledgeIndex(load_config(self.corpus.root, db=db), **self.kwargs)
        return self.index, db

    def __exit__(self, *exc: object) -> None:
        self.index.close()
        self.tmp.cleanup()


def _run_corpus(corpus: Corpus, log, split: str | None = None) -> dict:
    case_file = load_cases(corpus.name)
    written = len(case_file.cases) + len(case_file.dropped)
    if split:
        case_file.cases = [c for c in case_file.cases if split_of(c.id) == split]
    log(f"{corpus.name}: indexing")
    with _open_index(corpus) as (index, db):
        started = time.perf_counter()
        report = index.sync()
        cold = time.perf_counter() - started
        if report.errors or report.duplicates or report.missing_sources:
            log(f"{corpus.name}: sync problems: {report.to_dict()}")
        started = time.perf_counter()
        index.sync()
        resync = time.perf_counter() - started

        docs = index.conn.execute("SELECT id, path, words FROM documents ORDER BY id").fetchall()
        files = {row["id"]: _read(corpus.root / row["path"]) for row in docs}
        original = _read(corpus.original) if corpus.original else None
        everything = original if original is not None else "\n".join(files.values())
        tree = _section_tree(index)
        grep = _Grep({row["id"]: row["path"] for row in docs}, files)
        reader = KnowledgeIndex(index.config, auto_sync=False)
        reads: dict[str, int] = {}

        def read_tokens(ref: str) -> int:
            if ref not in reads:
                reads[ref] = tokens(render.render_doc(reader.read(ref)))
            return reads[ref]

        log(f"{corpus.name}: {len(docs)} docs, {len(case_file.cases)} cases")
        cases = []
        for case in case_file.cases:
            wanted = case.wanted()
            entry = {"id": case.id, "kind": case.kind, "answers": case.answers}
            for phrasing in PHRASINGS:
                query = case.query(phrasing)
                started = time.perf_counter()
                result = _search(index, query)
                elapsed = time.perf_counter() - started
                ranking = [r["id"] for r in result["results"]]
                cost, section = _agentindex_cost(result, wanted, tree, read_tokens)
                grep_ranking = grep.rank(query)
                entry[phrasing] = {
                    "query": query,
                    "ms": round(elapsed * 1000, 2),
                    "agentindex": {
                        "rank": _rank(ranking, wanted),
                        "top": ranking[:READS],
                        "tokens": cost,
                        "section": section,
                    },
                    "bm25": {"rank": _rank(_bm25_ranking(index, query), wanted)},
                    "grep": {
                        "rank": _rank([doc for doc, _ in grep_ranking], wanted),
                        "top": [doc for doc, _ in grep_ranking[:READS]],
                        "tokens": _grep_cost(grep_ranking, wanted, grep, files),
                    },
                }
            cases.append(entry)
        reader.close()
        cli_ms = _time_cli(corpus, db, [c.keywords for c in case_file.cases[:CLI_RUNS]])

    stats = aggregate(cases)
    return {
        "name": corpus.name,
        "title": corpus.title,
        "kind": corpus.kind,
        "url": corpus.web_url,
        "commit": corpus.commit,
        "license": corpus.license,
        "about": corpus.about,
        "docs": len(docs),
        "sections": sum(len(anchors) for anchors in tree.values()),
        "words": sum(row["words"] for row in docs),
        "tokens_total": tokens(everything),
        "original": corpus.paths[0] if corpus.original else None,
        "written": written,
        "dropped": case_file.dropped,
        "labeling": case_file.labeling,
        "speed": {
            "cold_index_s": round(cold, 3),
            "resync_ms": round(resync * 1000, 2),
            "cli_ms": cli_ms,
        },
        "cases": cases,
        **stats,
    }


def _search(index: KnowledgeIndex, query: str) -> dict:
    try:
        return index.search(query, limit=SEARCH_LIMIT)
    except QueryError:
        return {"query": query, "total": 0, "indexed": 0, "results": []}


def _rank(ranking: list[str], wanted: dict[str, set[str]]) -> int | None:
    """1-based rank of the first answering doc in the top ``SEARCH_LIMIT``, else None."""
    for n, doc in enumerate(ranking[:SEARCH_LIMIT], 1):
        if doc in wanted:
            return n
    return None


def _agentindex_cost(
    result: dict, wanted: dict, tree: dict, read_tokens
) -> tuple[int, bool | None]:
    """Tokens to reach the answer, and whether the result pointed at the answering section.

    The agent reads the section each result points at, in rank order. For the
    answering doc, if that section does not contain the answer, it reads the
    whole doc as well. A doc answered as a whole is read whole.
    """
    cost = tokens(render.render_search(result, SEARCH_HINT))
    for hit in result["results"][:READS]:
        doc = hit["id"]
        shown = hit["sections"][0]["anchor"] if hit["sections"] else ""
        if doc not in wanted:
            cost += read_tokens(f"{doc}#{shown}" if shown else doc)
            continue
        anchors = wanted[doc]
        if not anchors:
            return cost + read_tokens(doc), None
        if shown and _covers(tree[doc], shown, anchors):
            return cost + read_tokens(f"{doc}#{shown}"), True
        if shown:
            cost += read_tokens(f"{doc}#{shown}")  # read, but the answer is elsewhere
        return cost + read_tokens(doc), False
    return cost, None


def _covers(spans: dict[str, tuple[int, int]], shown: str, anchors: set[str]) -> bool:
    """Whether reading section ``shown`` (with its subsections) includes one of ``anchors``."""
    if shown not in spans:
        return False
    start, end = spans[shown]
    return any(a in spans and start <= spans[a][0] < end for a in anchors)


def _section_tree(index: KnowledgeIndex) -> dict[str, dict[str, tuple[int, int]]]:
    """Doc id -> {anchor: (start line, end of subtree)} for every named section."""
    tree: dict[str, dict[str, tuple[int, int]]] = {}
    for row in index.conn.execute("SELECT id FROM documents"):
        tree[row["id"]] = {}
    for row in index.conn.execute(
        "SELECT d.id, s.anchor, s.start_line, s.subtree_end"
        " FROM sections s JOIN documents d ON d.rowid = s.doc WHERE s.anchor != ''"
    ):
        tree[row["id"]].setdefault(row["anchor"], (row["start_line"], row["subtree_end"]))
    return tree


def _bm25_ranking(index: KnowledgeIndex, query: str) -> list[str]:
    """FTS5's built-in ranking over the same match expression and field weights."""
    try:
        expression = parse_query(query).to_fts()
    except QueryError:
        return []
    weights = ", ".join(map(str, DOC_WEIGHTS))
    rows = index.conn.execute(
        "SELECT d.id FROM docs_fts JOIN documents d ON d.rowid = docs_fts.rowid"
        f" WHERE docs_fts MATCH ? ORDER BY bm25(docs_fts, {weights}), d.rowid LIMIT ?",
        (expression, SEARCH_LIMIT),
    )
    return [row[0] for row in rows]


class _Grep:
    """Rank files the way an agent picks them from grep output."""

    def __init__(self, paths: dict[str, str], files: dict[str, str]) -> None:
        self.paths = paths
        # The path is searched too: agents look at file names as well as contents.
        self.lines = {
            doc: [line for line in (paths[doc] + "\n" + text).lower().split("\n") if line]
            for doc, text in files.items()
        }

    def rank(self, query: str) -> list[tuple[str, int]]:
        """``(doc id, matching lines)``, most query words first, then most matching lines."""
        try:
            terms = parse_query(query).terms
        except QueryError:
            terms = []
        terms = terms or tokenize(query)
        scored = []
        for doc, lines in self.lines.items():
            counts = [sum(1 for line in lines if term in line) for term in terms]
            matched = sum(1 for count in counts if count)
            if matched:
                scored.append((-matched, -sum(counts), self.paths[doc], doc, sum(counts)))
        scored.sort()
        return [(doc, count) for *_, doc, count in scored]


def _grep_cost(
    ranking: list[tuple[str, int]], wanted: dict, grep: _Grep, files: dict[str, str]
) -> int:
    listing = "\n".join(f"{grep.paths[doc]}:{count}" for doc, count in ranking[:GREP_LISTING])
    cost = tokens(listing)
    for doc, _ in ranking[:READS]:
        cost += tokens(files[doc])
        if doc in wanted:
            break
    return cost


def _time_cli(corpus: Corpus, db: str, queries: list[str]) -> float | None:
    """Median wall time of ``python3 -m agentindex search``: process start to output."""
    if not queries:
        return None
    command = [sys.executable, "-m", "agentindex", "--root", str(corpus.root), "--db", db]
    subprocess.run([*command, "search", "warm up"], cwd=REPO_ROOT, capture_output=True)
    times = []
    for query in queries:
        started = time.perf_counter()
        subprocess.run([*command, "search", query], cwd=REPO_ROOT, capture_output=True)
        times.append(time.perf_counter() - started)
    return round(statistics.median(times) * 1000, 1)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


# -- aggregation --------------------------------------------------------------------


def aggregate(cases: list[dict]) -> dict:
    """Hit rates, MRR, section accuracy, costs and search times over ``cases``."""
    out: dict = {"n": len(cases), "retrieval": {}, "tokens": {}, "section": {}}
    times = [case[p]["ms"] for case in cases for p in PHRASINGS]
    for phrasing in PHRASINGS:
        runs = [case[phrasing] for case in cases]
        out["retrieval"][phrasing] = {
            system: _retrieval([run[system]["rank"] for run in runs]) for system in SYSTEMS
        }
        out["tokens"][phrasing] = {
            system: _distribution([run[system]["tokens"] for run in runs])
            for system in ("agentindex", "grep")
        }
        pointed = [run["agentindex"]["section"] for run in runs]
        judged = [p for p in pointed if p is not None]
        out["section"][phrasing] = {
            "n": len(judged),
            "rate": round(sum(judged) / len(judged), 3) if judged else None,
        }
    out["search_ms"] = _percentiles(times)
    return out


def by_kind(cases: list[dict]) -> dict:
    """Retrieval per kind of question (how-to, troubleshooting, ...), for each phrasing."""
    kinds: dict[str, list[dict]] = {}
    for case in cases:
        kinds.setdefault(case.get("kind") or "other", []).append(case)
    return {
        kind: {
            phrasing: {
                system: _retrieval([case[phrasing][system]["rank"] for case in group])
                for system in SYSTEMS
            }
            for phrasing in PHRASINGS
        }
        for kind, group in sorted(kinds.items())
    }


def _retrieval(ranks: list[int | None]) -> dict:
    n = len(ranks)
    if not n:
        return {"n": 0}
    hit1 = sum(1 for r in ranks if r == 1)
    hit3 = sum(1 for r in ranks if r is not None and r <= 3)
    return {
        "n": n,
        "hit1": round(hit1 / n, 3),
        "hit1_ci": wilson(hit1, n),
        "hit3": round(hit3 / n, 3),
        "hit3_ci": wilson(hit3, n),
        "found": round(sum(1 for r in ranks if r is not None) / n, 3),
        "mrr": round(sum(1 / r for r in ranks if r) / n, 3),
    }


def _distribution(values: list[int]) -> dict:
    if not values:
        return {}
    return {
        "median": int(statistics.median(values)),
        "mean": int(statistics.mean(values)),
        "p90": int(_quantile(values, 0.9)),
    }


def _percentiles(values: list[float]) -> dict:
    if not values:
        return {}
    return {
        "p50": round(_quantile(values, 0.5), 2),
        "p95": round(_quantile(values, 0.95), 2),
        "max": round(max(values), 2),
    }


def _quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def wilson(successes: int, n: int, z: float = 1.96) -> list[float]:
    """95% Wilson score interval for a proportion."""
    if not n:
        return [0.0, 0.0]
    p = successes / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(max(0.0, centre - margin), 3), round(min(1.0, centre + margin), 3)]
