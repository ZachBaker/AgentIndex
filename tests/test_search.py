"""Ranking expectations. When a query ranks badly, add it here before tuning weights."""

from unittest import mock

from agentindex import store
from tests.helpers import ProjectTestCase

CORPUS = {
    "knowledge/ops/deploying.md": """
        ---
        title: Deploying to production
        summary: How releases reach production, and how to roll one back.
        tags: [deploy, ops]
        ---
        # Deploying to production

        Deploys go out through the deploy pipeline. Each deploy is tagged.

        ## Rollback

        If a release breaks, roll back the deploy with `deploy --rollback`.

        ## Feature flags

        Turn a feature flag off to disable a feature without a deploy.
    """,
    "knowledge/migrations.md": """
        ---
        title: Database migrations
        summary: Writing, reviewing and reverting schema migrations.
        tags: [database]
        keywords: [db, schema, alembic]
        ---
        # Database migrations

        Migrations are reviewed like code and run before the deploy.

        ## Rolling back

        Run `make migrate-down` to revert the last migration.
    """,
    "knowledge/auth.md": """
        ---
        title: Authentication
        summary: Login, sessions and token refresh.
        tags: [security]
        ---
        # Authentication

        Sessions are stored in redis. A deploy does not log users out.

        ## Token refresh

        Access tokens expire after 15 minutes and are refreshed with the refresh token.
    """,
    "knowledge/flags.md": """
        ---
        title: Experiments
        summary: Running experiments.
        tags: [product]
        ---
        # Experiments

        Every experiment needs a flag owner and a feature description. We deploy
        experiments behind a flag. The feature team reviews results weekly.
    """,
    "knowledge/testing.md": """
        ---
        title: Testing
        summary: How to run and write tests before a deploy.
        tags: [development]
        ---
        # Testing

        Run `make test`. Tests must pass before every deploy, and a deploy without
        tests is a deploy we roll back. Deploy, deploy, deploy: always test first.
    """,
}


class RankingTest(ProjectTestCase):
    files = CORPUS

    def ranking(self, query, **kwargs):
        return [r["id"] for r in self.open_index().search(query, **kwargs)["results"]]

    def assert_first(self, query, expected):
        ranking = self.ranking(query)
        self.assertTrue(ranking, f"no results for {query!r}")
        self.assertEqual(ranking[0], expected, f"{query!r} ranked {ranking}")

    def test_natural_language_question(self):
        self.assert_first("how do I roll back a deploy?", "ops/deploying")

    def test_topic_beats_repeated_mentions(self):
        # "deploy" appears in every doc, and testing.md repeats it; the doc about
        # deploying must still win (this failed with FTS5's clamped IDF).
        self.assert_first("deploy", "ops/deploying")

    def test_title_and_combination(self):
        self.assert_first("migrations rollback", "migrations")
        self.assert_first("token refresh", "auth")

    def test_keywords_cover_synonyms(self):
        self.assert_first("db", "migrations")
        self.assert_first("alembic", "migrations")

    def test_prefixes_and_stemming(self):
        self.assert_first("auth", "auth")
        self.assert_first("deploying", "ops/deploying")
        self.assert_first("refreshing tokens", "auth")

    def test_exact_phrase_outranks_scattered_words(self):
        # flags.md says "feature" and "flag" more often, but never "feature flag".
        self.assert_first("feature flag", "ops/deploying")

    def test_tags_and_summaries_count(self):
        self.assert_first("security", "auth")
        self.assert_first("reviewing migrations", "migrations")

    def test_best_section_is_reported(self):
        result = self.open_index().search("roll back a deploy")["results"][0]
        self.assertEqual(result["sections"][0]["anchor"], "rollback")
        self.assertIn("**roll back**", result["sections"][0]["snippet"])

    def test_scores_are_positive_and_sorted(self):
        scores = [r["score"] for r in self.open_index().search("deploy")["results"]]
        self.assertTrue(all(s > 0 for s in scores))
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_exclusion_and_tag_filter(self):
        self.assertNotIn("ops/deploying", self.ranking("rollback -pipeline"))
        self.assertEqual(self.ranking("deploy", tags=["database"]), ["migrations"])


# The field weights AgentIndex used until 0.2.1: titles 3x, keywords and ids 2x,
# tags, summaries and headings 1.5x. Real knowledge bases showed them to be too high.
WEIGHTED_FIELDS = (3.0, 2.0, 1.5, 1.5, 1.5, 1.0)


def plain_bm25_ranking(index, query, weights=None):
    """What FTS5's built-in bm25() would rank (the baseline these tests guard against)."""
    from agentindex.query import parse_query
    from agentindex.store import DOC_WEIGHTS

    weights = ", ".join(map(str, weights or DOC_WEIGHTS))
    rows = index.conn.execute(
        "SELECT d.id FROM docs_fts JOIN documents d ON d.rowid = docs_fts.rowid"
        f" WHERE docs_fts MATCH ? ORDER BY bm25(docs_fts, {weights})",
        (parse_query(query).to_fts(),),
    )
    return [r[0] for r in rows]


class ClampedIdfTest(ProjectTestCase):
    """FTS5 gives phrases found in half the docs or more an IDF of ~0, while rarer
    phrases keep theirs. Here "session" and "timeout" are common, so plain bm25()
    let a doc that mentions redis once beat the doc about session timeouts."""

    files = {
        "knowledge/sessions.md": "# Session expiry and timeouts\n\nSessions expire after an idle"
        " timeout. Each session keeps its own timeout; renewing a session resets the timeout.\n",
        "knowledge/cache.md": "# Caching\n\nRendered pages are cached in redis for five minutes.\n",
        "knowledge/api.md": "# API gateway\n\nThe gateway checks the session and applies a"
        " request timeout.\n",
        "knowledge/jobs.md": "# Background jobs\n\nJobs run without a session and have a"
        " timeout.\n",
        "knowledge/deploy.md": "# Deploying\n\nDeploys go out through the pipeline.\n",
    }

    def test_common_words_still_count(self):
        index = self.open_index()
        query = "redis session timeout"
        self.assertEqual(index.search(query)["results"][0]["id"], "sessions")
        index.sync()
        self.assertEqual(plain_bm25_ranking(index, query)[0], "cache")  # the baseline's mistake


class FieldSaturationTest(ProjectTestCase):
    """bm25() sums weighted counts from all fields into one saturating term frequency,
    so with tags, summaries and headings weighted up, "deploy" in migrations' tags,
    summary and heading added up to nearly as much as a doc titled and written about
    deploying."""

    files = {
        "knowledge/auth.md": """
            # Authentication
            Login flow and token refresh. Sessions are stored in redis.

            ## Token refresh
            Access tokens expire after 15 minutes; the client refreshes with the refresh token.
        """,
        "knowledge/migrations.md": """
            ---
            title: Database migrations
            summary: How schema migrations are written, reviewed, and deployed.
            tags: [database, deploy]
            keywords: [db, schema, alembic]
            ---
            # Database migrations
            Migrations live in `db/migrations`.

            ## Writing a migration
            Use `make migration name=...`. Each migration must be reversible.

            ## Rolling back
            Run `make migrate-down` to revert the last migration.
            See [deploy](ops/deploying.md#rollback).
        """,
        "knowledge/ops/deploying.md": """
            ---
            title: Deploying to production
            tags: [deploy, ops]
            ---
            # Deploying to production
            Deploys go out via the `deploy` script in [src/deploy.py](../../src/deploy.py).
            A broken link: [nope](../nope.md).

            ## Rollback
            If a release breaks, roll back the deploy with `deploy --rollback`.
            Feature flags can also be turned off.

            ## Feature flags
            Feature flags live in LaunchDarkly. Turn a flag off to disable the feature.
        """,
        "knowledge/start-here.md": """
            ---
            title: Start here
            summary: Map of the knowledge base.
            tags: [meta]
            ---
            # Start here
            Read [deploying](ops/deploying.md) and [migrations](migrations.md#rolling-back).
        """,
    }

    def test_doc_about_the_topic_wins(self):
        index = self.open_index()
        query = "how do I roll back a deploy?"
        self.assertEqual(index.search(query)["results"][0]["id"], "ops/deploying")
        self.assertEqual(
            plain_bm25_ranking(index, query, WEIGHTED_FIELDS)[0], "migrations"
        )  # the baseline's mistake


def _ci_job_doc(name, extra):
    """A narrow doc about one CI job, named after it in every field."""
    return f"""
        ---
        title: The {name} CI job
        summary: What the {name} CI job runs and how to read its failures.
        ---
        # The {name} CI job

        The {name} job runs on every pull request. {extra}

        ## When the {name} CI job fails

        Check the job log first; most failures of this job are flaky.
    """


class FlatFieldWeightsTest(ProjectTestCase):
    """From the rustc-dev-guide benchmark: asked where CI jobs are defined, narrow docs
    named after one CI job outranked the CI overview that answers it. Each field already
    saturates separately, so a word in a doc's title, id, summary and headings counts
    once per field; weighting titles and ids up as well let the narrow doc win."""

    files = {
        "knowledge/tests/ci.md": """
            ---
            title: Testing with CI
            summary: How pull requests are tested before they merge.
            ---
            # Testing with CI

            Every pull request is tested on GitHub Actions before it can merge.

            ## Changing which jobs run

            The jobs are defined in `src/ci/jobs.yml`, including the runners each one uses.
            To stop running one temporarily, remove it from the list used for merge builds.
        """,
        "knowledge/tests/autodiff-ci-job.md": _ci_job_doc("autodiff", "It builds Enzyme first."),
        "knowledge/tests/linux-ci-job.md": _ci_job_doc("Rust for Linux", "It builds the kernel."),
        "knowledge/tests/gcc-ci-job.md": _ci_job_doc("GCC backend", "It uses the GCC backend."),
        "knowledge/tests/apple-ci-job.md": _ci_job_doc("Apple", "It runs on macOS."),
    }

    def test_doc_that_answers_beats_docs_named_after_the_words(self):
        query = (
            "Where are CI jobs like the aarch64-apple test runners defined, so I can remove"
            " them from merge builds?"
        )
        self.assertEqual(self.open_index().search(query)["results"][0]["id"], "tests/ci")
        with mock.patch.object(store, "DOC_WEIGHTS", WEIGHTED_FIELDS):
            ranked = self.open_index().search(query)["results"]
        self.assertEqual(ranked[0]["id"], "tests/apple-ci-job")  # the old weights' mistake
