"""The benchmark harness in bench/: case files, baselines, metrics and the report.

These run offline on a throwaway corpus. The real corpora are fetched by
``python3 -m bench fetch`` and are not needed here.
"""

import json
import re
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from bench import corpora as bench_corpora
from bench import evaluate, report
from bench.corpora import CORPORA_FILE, Corpus, load_corpora
from bench.evaluate import CASES_DIR, Case, aggregate, load_cases, wilson
from tests.helpers import ProjectTestCase, make_project

CORPUS = {
    ".agentindex.json": '{"sources": ["docs"]}',
    "docs/testing.md": """
        ---
        title: Testing
        summary: How to run and write tests.
        ---
        # Testing

        Tests live in test/.

        ## Running one test

        Pass the file to the runner: `make test FILE=x`.

        ## Flaky tests

        Mark a flaky test in the status file.
    """,
    "docs/releases.md": """
        # Releases

        Releases are cut every Tuesday from main. A test run must pass first.
    """,
    "docs/style.md": """
        # Code style

        Use four spaces. Never commit a failing test or test test test.
    """,
}


def fake_corpus(name: str = "fake") -> Corpus:
    return Corpus(
        name=name,
        title="Fake docs",
        kind="docs",
        repo="https://github.com/example/fake",
        commit="0" * 40,
        paths=["docs"],
        license="MIT",
        about="A throwaway corpus.",
    )


class BenchTestCase(ProjectTestCase):
    """A fake corpus in a temporary cache, and a temporary cases directory."""

    files = {}

    def setUp(self):
        super().setUp()
        self.cache = Path(tempfile.mkdtemp(prefix="agentindex-bench-cache-"))
        self.cases = Path(tempfile.mkdtemp(prefix="agentindex-bench-cases-"))
        self.addCleanup(shutil.rmtree, self.cache, True)
        self.addCleanup(shutil.rmtree, self.cases, True)
        make_project(CORPUS, self.cache / "fake")
        for target, value in (
            ("bench.corpora.CACHE_DIR", self.cache),
            ("bench.evaluate.CASES_DIR", self.cases),
            ("bench.evaluate.CLI_RUNS", 1),
        ):
            patcher = mock.patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.corpus = fake_corpus()

    def write_cases(self, cases, dropped=()):
        data = {"corpus": "fake", "cases": cases, "dropped": list(dropped)}
        (self.cases / "fake.json").write_text(json.dumps(data), encoding="utf-8")


class CheckCasesTest(BenchTestCase):
    def test_valid_cases_pass(self):
        self.write_cases(
            [
                {
                    "id": "a",
                    "question": "how do I run one test?",
                    "keywords": "run single test",
                    "answers": ["testing#running-one-test", "releases"],
                }
            ]
        )
        self.assertEqual(evaluate.check_cases([self.corpus]), [])

    def test_unknown_docs_and_sections_are_reported(self):
        self.write_cases(
            [
                {"id": "a", "question": "q", "keywords": "k", "answers": ["nope"]},
                {"id": "a", "question": "q", "keywords": "", "answers": ["testing#nope"]},
            ]
        )
        problems = evaluate.check_cases([self.corpus])
        self.assertIn("fake: a: no doc 'nope'", problems)
        self.assertIn("fake: a: duplicate id", problems)
        self.assertIn("fake: a: needs both a question and keywords", problems)
        self.assertIn("fake: a: no section testing#nope", problems)

    def test_not_answers_are_checked(self):
        self.write_cases(
            [
                {
                    "id": "a",
                    "question": "q",
                    "keywords": "k",
                    "answers": ["testing"],
                    "not_answers": ["testing", "gone"],
                }
            ]
        )
        problems = evaluate.check_cases([self.corpus])
        self.assertIn("fake: a: 'testing' is in both answers and not_answers", problems)
        self.assertIn("fake: a: no doc 'gone' (in not_answers)", problems)


class PoolTest(BenchTestCase):
    def test_unjudged_top_results_are_pooled(self):
        self.write_cases(
            [
                {
                    "id": "a",
                    "question": "how do I run one test?",
                    "keywords": "run one test",
                    "answers": ["testing"],
                    "not_answers": ["style"],
                }
            ]
        )
        pool = evaluate.pool_candidates([self.corpus])["fake"]
        # testing is the answer and style was judged already: only releases is left.
        self.assertEqual([c["id"] for c in pool[0]["candidates"]], ["releases"])
        self.assertNotIn("rank", pool[0]["candidates"][0])  # judges cannot see who found it


class RunTest(BenchTestCase):
    def setUp(self):
        super().setUp()
        self.write_cases(
            [
                {
                    "id": "one-test",
                    "question": "how do I run just one test file?",
                    "keywords": "run one test",
                    "answers": ["testing#running-one-test"],
                },
                {
                    "id": "release-day",
                    "question": "which day are releases cut?",
                    "keywords": "release schedule",
                    "answers": ["releases"],
                },
            ],
            dropped=[{"id": "dropped", "question": "not answered", "reason": "not covered"}],
        )
        self.results = evaluate.run_benchmark([self.corpus], log=lambda message: None)

    def test_ranks_costs_and_sections(self):
        corpus = self.results["corpora"][0]
        self.assertEqual((corpus["docs"], corpus["n"], corpus["written"]), (3, 2, 3))
        one = corpus["cases"][0]["keywords"]
        self.assertEqual(one["agentindex"]["rank"], 1)
        self.assertTrue(one["agentindex"]["section"])  # it pointed at #running-one-test
        self.assertGreater(one["agentindex"]["tokens"], 0)
        self.assertIsNotNone(one["bm25"]["rank"])
        self.assertEqual(one["grep"]["top"][0], "testing")  # has all three words
        release = corpus["cases"][1]["question"]
        self.assertIsNone(release["agentindex"]["section"])  # answered by the whole doc

    def test_speed_is_measured(self):
        speed = self.results["corpora"][0]["speed"]
        self.assertGreater(speed["cold_index_s"], 0)
        self.assertGreater(speed["cli_ms"], 0)

    def test_report_renders(self):
        text = report.render_report(self.results)
        self.assertIn("| Fake docs | 2 |", text)
        self.assertIn("## Misses", text)
        self.assertIn("| other | 2 |", text)  # cases without a kind, in the by-kind table
        out = Path(tempfile.mkdtemp(prefix="agentindex-bench-out-"))
        self.addCleanup(shutil.rmtree, out, True)
        paths = report.write_results(self.results, out)
        self.assertEqual(json.loads(paths[1].read_text(encoding="utf-8"))["overall"]["n"], 2)


class MetricsTest(ProjectTestCase):
    def run_with(self, ranks):
        return {
            p: {
                "ms": 1.0,
                "agentindex": {"rank": r, "tokens": 10, "section": None},
                "bm25": {"rank": r},
                "grep": {"rank": None, "tokens": 20},
            }
            for p, r in zip(evaluate.PHRASINGS, ranks)
        }

    def test_hit_rates_and_mrr(self):
        cases = [self.run_with((1, 2)), self.run_with((3, None)), self.run_with((None, 1))]
        stats = aggregate(cases)["retrieval"]
        question = stats["question"]["agentindex"]
        self.assertEqual((question["hit1"], question["hit3"]), (0.333, 0.667))
        self.assertEqual(question["mrr"], round((1 + 1 / 3) / 3, 3))
        self.assertEqual(stats["keywords"]["grep"]["found"], 0.0)

    def test_wilson_interval(self):
        self.assertEqual(wilson(0, 0), [0.0, 0.0])
        low, high = wilson(45, 50)
        self.assertTrue(low < 0.9 < high)
        self.assertEqual(wilson(10, 10)[1], 1.0)

    def test_section_coverage(self):
        spans = {"a": (0, 10), "a-b": (3, 6), "c": (10, 12)}
        self.assertTrue(evaluate._covers(spans, "a", {"a-b"}))
        self.assertFalse(evaluate._covers(spans, "a-b", {"c"}))
        self.assertFalse(evaluate._covers(spans, "missing", {"a"}))

    def test_case_answers(self):
        case = Case("x", "q", "k", ["a#one", "a#two", "b"])
        self.assertEqual(case.wanted(), {"a": {"one", "two"}, "b": set()})

    def test_grep_ranks_by_words_then_lines(self):
        files = {
            "a": "deploy here\ndeploy there\ndeploy everywhere",
            "b": "deploy the cache\nroll back",
            "c": "nothing relevant",
        }
        paths = {"a": "docs/alpha.md", "b": "docs/beta.md", "c": "docs/gamma.md"}
        grep = evaluate._Grep(paths, files)
        self.assertEqual(grep.rank("deploy"), [("a", 3), ("b", 1)])  # more matching lines
        self.assertEqual(grep.rank("how do I roll back a deploy?")[0], ("b", 3))  # more words
        self.assertEqual(grep.rank("gamma"), [("c", 1)])  # file names are searched too


class CommittedFilesTest(ProjectTestCase):
    """corpora.json and bench/cases/*.json are well formed (no network needed)."""

    def test_corpora_are_pinned(self):
        names = set()
        for corpus in load_corpora():
            self.assertRegex(corpus.commit, r"^[0-9a-f]{40}$", corpus.name)
            self.assertIn(corpus.kind, ("docs", "import"))
            self.assertTrue(corpus.paths, corpus.name)
            names.add(corpus.name)
        listed = {c["name"] for c in json.loads(CORPORA_FILE.read_text("utf-8"))["corpora"]}
        self.assertEqual(names, listed)

    def test_case_files_are_well_formed(self):
        corpora = {c.name for c in load_corpora()}
        for path in sorted(CASES_DIR.glob("*.json")):
            with self.subTest(file=path.name):
                self.assertIn(path.stem, corpora)
                case_file = load_cases(path.stem)
                ids = [c.id for c in case_file.cases] + [d["id"] for d in case_file.dropped]
                self.assertEqual(len(ids), len(set(ids)), "duplicate ids")
                for case in case_file.cases:
                    self.assertTrue(case.question.strip() and case.keywords.strip(), case.id)
                    self.assertTrue(case.answers, case.id)
                    for answer in case.answers:
                        self.assertRegex(answer, r"^[^#\s]+(#[^#\s]+)?$", case.id)
                for dropped in case_file.dropped:
                    self.assertTrue(dropped.get("reason"), dropped["id"])

    def test_cache_is_ignored_by_git(self):
        root = Path(bench_corpora.__file__).resolve().parent.parent
        ignored = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("bench/.cache/", ignored)
        self.assertTrue(re.match(r"^\.cache$", bench_corpora.CACHE_DIR.name))
