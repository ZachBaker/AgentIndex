"""Contradiction detection: statements, the rules for pairs, grouping and focus."""

import random
import unittest

from agentindex import NotFoundError
from agentindex.conflicts import CANDIDATE_SIMILARITY, _similar_pairs, extract_statements
from agentindex.markdown import parse_document
from tests.helpers import ProjectTestCase


def extract(text, doc="guide"):
    parsed = parse_document(text, fallback_title="Guide")
    sections = [(s.start, s.anchor, s.heading) for s in parsed.sections]
    return extract_statements(
        doc, f"knowledge/{doc}.md", parsed.title, parsed.body, parsed.body_line, sections
    )


class StatementTest(unittest.TestCase):
    def test_sentences_list_items_and_table_rows(self):
        text = (
            "---\ntitle: Guide\n---\n# Guide\n\n"
            "The API listens on port 8765. 3 restarts are needed after changing the port.\n\n"
            "- Run the tests with `make test` before pushing.\n"
            "- Lint the code with `ruff check`, which\n  reads `pyproject.toml`.\n\n"
            "> Use a linter, e.g. Ruff, before you commit; CI runs it as well.\n\n"
            "| Option | Default |\n|---|---|\n| `--port` | The port to listen on, `8765` |\n"
        )
        self.assertEqual(
            [(s.line, s.anchor, s.text) for s in extract(text)],
            [
                (6, "guide", "The API listens on port 8765."),
                (6, "guide", "3 restarts are needed after changing the port."),
                (8, "guide", "Run the tests with `make test` before pushing."),
                (9, "guide", "Lint the code with `ruff check`, which reads `pyproject.toml`."),
                (12, "guide", "Use a linter, e.g. Ruff, before you commit;"),
                (12, "guide", "CI runs it as well."),
                (16, "guide", "`--port` — The port to listen on, `8765`"),
            ],
        )

    def test_code_comments_headings_and_lead_ins_are_not_statements(self):
        text = (
            "# Guide\n\nTo install the tool, run these commands:\n\n"
            "```bash\nThe port is 8765 in a code block.\n```\n\n"
            "1. Start the server with the default settings.\n\n"
            "        ```\n        The port is 8080 in a fence nested in a list.\n        ```\n\n"
            "<!-- The port is 9000 in a comment. -->\n\n"
            "## The port is 1234 in a heading\n\n"
            "`npm install agentindex-cli`\n\nToo short.\n"
        )
        self.assertEqual(
            [s.text for s in extract(text)], ["Start the server with the default settings."]
        )


class ConflictsTestCase(ProjectTestCase):
    def conflicts(self, *refs):
        return self.open_index().conflicts(refs)["conflicts"]

    def differences(self, one, two):
        """The conflicts between a statement in one doc and a statement in another."""
        self.write("knowledge/one.md", f"# One\n\n{one}\n")
        self.write("knowledge/two.md", f"# Two\n\n{two}\n")
        return [(c["kind"], *c["difference"]) for c in self.conflicts()]


class DetectionTest(ConflictsTestCase):
    def test_different_values(self):
        cases = [
            (
                "The HTTP API listens on port 8765 by default.",
                "The HTTP API listens on port 8080 by default.",
                ("value", "8765", "8080"),
            ),
            (
                "Requires Python 3.9 or newer.",
                "Requires Python 3.11 or newer.",
                ("value", "3.9", "3.11"),
            ),
            (
                "Run the tests with `pytest -x`.",
                "Run the tests with `make test`.",
                ("value", "pytest -x", "make test"),
            ),
            (
                "User sessions are stored in Redis.",
                "User sessions are stored in Memcached.",
                ("value", "Redis", "Memcached"),
            ),
            (
                "Docs longer than 2,500 words get a warning.",
                "Docs longer than 3,000 words get a warning.",
                ("value", "2,500", "3,000"),
            ),
            (  # the same words in another order
                "By default, the HTTP API listens on port 8765.",
                "The API listens on port 8080 by default.",
                ("value", "8765", "8080"),
            ),
            (
                "Production deploys go through GitHub Actions.",
                "Production deploys go through CircleCI.",
                ("value", "GitHub Actions", "CircleCI"),
            ),
            (
                "The default request timeout is 30 seconds.",
                "The default request timeout is 60 seconds.",
                ("value", "30", "60"),
            ),
            (
                "Use `uv` to install the dependencies.",
                "Use `pip` to install the dependencies.",
                ("value", "uv", "pip"),
            ),
            (  # a link on one side only
                "Keep sessions in [Postgres](pg.md) for now.",
                "Keep sessions in Redis for now.",
                ("value", "Postgres", "Redis"),
            ),
            (
                "Set `AGENTINDEX_DB` to change the database path.",
                "Set `AGENTINDEX_ROOT` to change the database path.",
                ("value", "AGENTINDEX_DB", "AGENTINDEX_ROOT"),
            ),
        ]
        for one, two, expected in cases:
            with self.subTest(one=one):
                self.assertEqual(self.differences(one, two), [expected])

    def test_opposite_meanings(self):
        cases = [
            ("Never commit the `.env` file.", "Always commit the `.env` file.", "Never", ""),
            ("Do not run migrations in production.", "Run migrations in production.", "not", ""),
            (
                "The importer doesn't overwrite existing docs.",
                "The importer overwrites existing docs.",
                "doesn't",
                "",
            ),
            (
                "Caching is enabled by default.",
                "Caching is disabled by default.",
                "enabled",
                "disabled",
            ),
            (
                "The `--force` flag is required.",
                "The `--force` flag is optional.",
                "required",
                "optional",
            ),
            (
                "Run database migrations before deploying.",
                "Run database migrations after deploying.",
                "before",
                "after",
            ),
            (
                "The tool is unsupported on Windows hosts.",
                "The tool is supported on Windows hosts.",
                "unsupported",
                "supported",
            ),
            (
                "`check --strict` fails on warnings.",
                "`check --strict` passes on warnings.",
                "fails",
                "passes",
            ),
            (
                "Keep `.agentindex/` in `.gitignore`.",
                "Remove `.agentindex/` from `.gitignore`.",
                "Keep",
                "Remove",
            ),
            (
                "You must not edit generated files by hand.",
                "You may edit generated files by hand.",
                "not",
                "",
            ),
            (
                "The summary is shown in every search result.",
                "The summary is hidden in search results.",
                "shown",
                "hidden",
            ),
        ]
        for one, two, *expected in cases:
            with self.subTest(one=one):
                self.assertEqual(self.differences(one, two), [("opposite", *expected)])

    def test_statements_that_do_not_contradict(self):
        cases = [
            ("The HTTP API listens on port 8765.", "The HTTP API listens on port 8765."),
            # The subjects differ, not the facts.
            ("The `search` command prints ranked docs.", "The `list` command prints ranked docs."),
            # Another word differs too, so the context does.
            (
                "In development, the API listens on port 8765.",
                "In production, the API listens on port 443.",
            ),
            ("Setup takes 5 minutes on Linux.", "Setup takes 20 minutes on Windows."),
            # More detail is not a contradiction.
            ("Run `agentindex check` in CI.", "Run `agentindex check --strict` in CI."),
            (
                "Not every doc needs tags, but every doc needs a summary.",
                "Every doc needs a summary.",
            ),
            # References point to different pages.
            ("See [Configuration](a.md) for the details.", "See [Testing](b.md) for the details."),
            ("See `parse()` for more information.", "See `render()` for more information."),
            (
                "Code: [conflicts.py](c.py) and `conflicts()` in [store.py](s.py).",
                "Code: [query.py](q.py) and `search()` in [store.py](s.py).",
            ),
            # "Not required" and "optional" agree.
            (
                "The cache is not required when the index is not shared.",
                "The cache is optional when the index is not shared.",
            ),
            (
                "In development, response caching is enabled for all endpoints.",
                "In production, response caching is disabled for all endpoints.",
            ),
            # Two things differ.
            ("Version 1.2 added the `--json` option.", "Version 1.3 added the `--outline` option."),
            ("Exit code 1 means not found.", "Exit code 2 means bad usage."),
            ("The CLI prints plain text.", "The HTTP API prints JSON."),
            # Different words are not values.
            ("Run the linter before committing.", "Run the tests before committing."),
            ("User sessions are stored in Redis.", "User sessions are stored in Redis Cluster."),
            (
                "The database is a cache that is always safe to delete.",
                "The database is a cache that is safe to delete.",
            ),
            # Sharing two words, they must match exactly.
            ("These run from the scripts of `<pkg>`.", "It will run the `test` script in `./a`."),
        ]
        for one, two in cases:
            with self.subTest(one=one):
                self.assertEqual(self.differences(one, two), [])

    def test_the_same_doc_is_not_compared_with_itself(self):
        self.write(
            "knowledge/one.md",
            "# One\n\nThe API listens on port 8765.\n\nThe API listens on port 8080.\n",
        )
        self.assertEqual(self.conflicts(), [])


class SubjectTest(ConflictsTestCase):
    def test_sections_named_after_different_things(self):
        self.write(
            "knowledge/one.md", "# One\n\n## `--quiet`\n\nIt defaults to `false` in the CLI.\n"
        )
        self.write(
            "knowledge/two.md", "# Two\n\n## `--json`\n\nIt defaults to `true` in the CLI.\n"
        )
        self.assertEqual(self.conflicts(), [])
        self.write(
            "knowledge/two.md", "# Two\n\n## `--quiet`\n\nIt defaults to `true` in the CLI.\n"
        )
        self.assertEqual(len(self.conflicts()), 1)

    def test_values_that_name_their_own_doc(self):
        self.write("knowledge/npm-ci.md", "# npm ci\n\nRun `npm ci` to install the dependencies.\n")
        self.write(
            "knowledge/npm-install.md",
            "# npm install\n\nRun `npm install` to install the dependencies.\n",
        )
        self.assertEqual(self.conflicts(), [])
        self.write(
            "knowledge/ci-setup.md",
            "# CI setup\n\nRun `npm install` to install the dependencies.\n",
        )
        found = self.conflicts()
        self.assertEqual([c["difference"] for c in found], [["install", "ci"]])
        self.assertEqual(
            [loc["id"] for loc in found[0]["statements"][0]["locations"]], ["ci-setup"]
        )

    def test_sentences_found_in_many_versions_are_templates(self):
        footer = "# {0}\n\nThe docs team last reviewed this page on 2024-05-0{0}.\n"
        for n in (1, 2):
            self.write(f"knowledge/page{n}.md", footer.format(n))
        found = self.conflicts()
        self.assertEqual([c["difference"] for c in found], [["2024-05-01", "2024-05-02"]])
        for n in (3, 4):
            self.write(f"knowledge/page{n}.md", footer.format(n))
        self.assertEqual(len(self.conflicts()), 0)

    def test_sentences_a_doc_repeats_with_other_values_are_templates(self):
        self.write(
            "knowledge/environments.md",
            "# Environments\n\n## Staging\n\nDeploys use `deploy.sh` with `--env staging`.\n\n"
            "## Production\n\nDeploys use `deploy.sh` with `--env production`.\n",
        )
        self.write("knowledge/dev.md", "# Dev\n\nDeploys use `deploy.sh` with `--env dev`.\n")
        self.assertEqual(self.conflicts(), [])


PORT = "The HTTP API listens on port {} by default.\n"


class ResultTest(ConflictsTestCase):
    files = {
        "knowledge/api.md": "# API\n\n" + PORT.format(8765),
        "knowledge/ops/serving.md": "# Serving\n\n## Ports\n\n" + PORT.format(8765),
        "knowledge/setup.md": "---\nsummary: S.\n---\n# Setup\n\n" + PORT.format(8080),
    }

    def test_claims_are_grouped_with_every_place_that_makes_them(self):
        result = self.open_index().conflicts()
        self.assertEqual((result["docs"], result["documents"], result["total"]), ([], 3, 1))
        conflict = result["conflicts"][0]
        self.assertEqual(conflict["kind"], "value")
        self.assertEqual(conflict["difference"], ["8765", "8080"])
        self.assertEqual(conflict["similarity"], 1.0)
        majority, minority = conflict["statements"]
        self.assertEqual(majority["text"], "The HTTP API listens on port **8765** by default.")
        self.assertEqual(
            majority["locations"],
            [
                {"id": "api", "anchor": "api", "path": "knowledge/api.md", "line": 3},
                {
                    "id": "ops/serving",
                    "anchor": "ports",
                    "path": "knowledge/ops/serving.md",
                    "line": 5,
                },
            ],
        )
        self.assertEqual(minority["text"], "The HTTP API listens on port **8080** by default.")
        self.assertEqual([loc["line"] for loc in minority["locations"]], [6])

    def test_focus_on_some_docs(self):
        index = self.open_index()
        focused = index.conflicts(["serving"])
        self.assertEqual(focused["docs"], ["ops/serving"])
        statements = focused["conflicts"][0]["statements"]
        self.assertEqual([loc["id"] for loc in statements[0]["locations"]], ["ops/serving"])
        self.assertEqual(index.conflicts(["setup"])["total"], 1)
        with self.assertRaises(NotFoundError):
            index.conflicts(["nope-nope"])


class CandidatePairsTest(unittest.TestCase):
    def test_prefix_filtering_finds_every_similar_pair(self):
        rng = random.Random(7)
        words = [f"w{i}" for i in range(30)]
        for _ in range(100):
            sets = [
                frozenset(rng.sample(words[: rng.randint(9, 30)], rng.randint(1, 9)))
                for _ in range(40)
            ]
            expected = {
                (i, j)
                for i in range(len(sets))
                for j in range(i + 1, len(sets))
                if 2 * len(sets[i] & sets[j])
                >= CANDIDATE_SIMILARITY * (len(sets[i]) + len(sets[j]))
            }
            self.assertEqual({tuple(sorted(p)) for p in _similar_pairs(sets)}, expected)
