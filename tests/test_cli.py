import contextlib
import io
import json

from agentindex.cli import main
from tests.helpers import ProjectTestCase


class CliTestCase(ProjectTestCase):
    files = {
        "knowledge/ops/deploying.md": """
            ---
            title: Deploying
            summary: How we deploy.
            tags: [ops]
            ---
            # Deploying

            Run the deploy script.

            ## Rollback

            Use `deploy --rollback`.
        """,
        "knowledge/auth.md": "# Auth\n\nSessions live in redis.\n",
    }

    def run_cli(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(["--root", str(self.root), *args], prog="agentindex")
        return code, stdout.getvalue(), stderr.getvalue()


class ReadingCommandsTest(CliTestCase):
    def test_search(self):
        code, out, _ = self.run_cli("search", "roll", "back")
        self.assertEqual(code, 0)
        self.assertIn("1. ops/deploying — Deploying  [ops]", out)
        self.assertIn("§ Rollback (ops/deploying#rollback)", out)
        self.assertIn("Read one: agentindex read <id>", out)

    def test_search_json_and_options(self):
        code, out, _ = self.run_cli("search", "deploy", "--json", "-n", "1", "--tag", "ops")
        result = json.loads(out)
        self.assertEqual((code, result["results"][0]["id"]), (0, "ops/deploying"))

    def test_exclusions_are_query_words_not_options(self):
        # -tests would otherwise parse as "-t ests" and -heroku as "-h"
        code, out, _ = self.run_cli(
            "search", "redis", "deploy", "-auth", "-tests", "-heroku", "-n", "5"
        )
        self.assertEqual(code, 0)
        self.assertIn('match "redis deploy -auth -tests -heroku"', out)
        self.assertNotIn("auth — Auth", out)
        code, out, _ = self.run_cli("search", "--", "-n")
        self.assertEqual(code, 2)

    def test_no_results_is_not_an_error(self):
        code, out, _ = self.run_cli("search", "zebra")
        self.assertEqual(code, 0)
        self.assertIn('No docs match "zebra"', out)

    def test_read_section_and_outline(self):
        code, out, _ = self.run_cli("read", "ops/deploying#rollback")
        self.assertEqual(code, 0)
        self.assertTrue(
            out.startswith("id: ops/deploying#rollback | file: knowledge/ops/deploying.md:10")
        )
        self.assertIn("Use `deploy --rollback`.", out)
        self.assertNotIn("Run the deploy script", out)
        _, out, _ = self.run_cli("read", "ops/deploying", "--outline")
        self.assertIn("## Rollback  #rollback", out)

    def test_read_adds_a_title_when_the_doc_has_no_h1(self):
        self.write("knowledge/plain.md", "---\ntitle: Plain doc\n---\nJust text.\n")
        _, out, _ = self.run_cli("read", "plain")
        self.assertIn("# Plain doc\n\nJust text.", out)

    def test_not_found(self):
        code, out, err = self.run_cli("read", "ops/deployin")
        self.assertEqual((code, out), (1, ""))
        self.assertIn("error: no doc with id 'ops/deployin'", err)
        self.assertIn("did you mean: ops/deploying", err)
        code, out, _ = self.run_cli("read", "nope-nope", "--json")
        self.assertEqual((code, json.loads(out)["error"]), (1, "no doc with id 'nope-nope'"))

    def test_list(self):
        code, out, _ = self.run_cli("list")
        self.assertEqual(code, 0)
        self.assertIn("auth           Auth — Sessions live in redis.", out)
        self.assertIn("Tags: ops (1)", out)


class MaintenanceCommandsTest(CliTestCase):
    def test_check_exit_codes(self):
        code, out, _ = self.run_cli("check")
        self.assertEqual(code, 0)  # warnings only (auth.md has no summary)
        self.assertIn("2 docs checked: 0 errors, 1 warning.", out)
        self.assertEqual(self.run_cli("check", "--strict")[0], 1)
        self.write("knowledge/broken.md", "---\nsummary: S.\n---\n# B\n\n[x](missing.md)\n")
        code, out, _ = self.run_cli("check")
        self.assertEqual(code, 1)
        self.assertIn("knowledge/broken.md:6: error: broken link", out)

    def test_conflicts(self):
        code, out, _ = self.run_cli("conflicts")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("No contradictions found"), out)
        self.write("knowledge/api.md", "# API\n\nThe HTTP API listens on port 8765 by default.\n")
        self.write(
            "knowledge/setup.md", "# Setup\n\nThe HTTP API listens on port 8080 by default.\n"
        )
        code, out, _ = self.run_cli("conflicts")
        self.assertEqual(code, 0)
        self.assertIn('1. Different values: "8765" vs "8080"\n   api#api (knowledge/api.md:3)', out)
        self.assertIn("     The HTTP API listens on port **8080** by default.", out)
        self.assertIn("agentindex read <id>#<anchor>", out)
        code, out, _ = self.run_cli("conflicts", "setup", "--json")
        result = json.loads(out)
        self.assertEqual((code, result["docs"], result["total"]), (0, ["setup"], 1))
        self.assertEqual(result["conflicts"][0]["difference"], ["8080", "8765"])
        code, out, err = self.run_cli("conflicts", "ops/deploying")
        self.assertIn("No contradictions found involving ops/deploying", out)
        self.assertEqual(self.run_cli("conflicts", "nope-nope")[0], 1)

    def test_conflicts_list_a_few_places_per_side(self):
        for n in range(10):
            self.write(f"knowledge/copy{n}.md", f"# Copy {n}\n\nThe API listens on port 8765.\n")
        self.write("knowledge/odd.md", "# Odd\n\nThe API listens on port 8080.\n")
        _, out, _ = self.run_cli("conflicts")
        self.assertIn(
            "copy7#copy-7 (knowledge/copy7.md:3)\n   … and 2 more (--json lists all)", out
        )
        _, out, _ = self.run_cli("conflicts", "--json")
        self.assertEqual(len(json.loads(out)["conflicts"][0]["statements"][0]["locations"]), 10)

    def test_sync_and_status(self):
        code, out, _ = self.run_cli("sync")
        self.assertEqual(code, 0)
        self.assertIn("Indexed 2 docs", out)
        code, out, _ = self.run_cli("status", "--json")
        self.assertEqual(json.loads(out)["documents"], 2)

    def test_usage_errors(self):
        code, _, err = self.run_cli("search", "-x")
        self.assertEqual(code, 2)
        self.assertIn("no search terms", err)
        self.write(".agentindex.json", "{bad json")
        code, _, err = self.run_cli("list")
        self.assertEqual(code, 2)
        self.assertIn(".agentindex.json", err)

    def test_environment_errors_are_reported_not_raised(self):
        self.write("blocker", "a file where a directory should be")
        db = str(self.root / "blocker" / "index.db")
        code, out, err = self.run_cli("--db", db, "list")
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.startswith("error: "), err)
        code, out, _ = self.run_cli("--db", db, "list", "--json")
        self.assertEqual(code, 2)
        self.assertIn("error", json.loads(out))

    def test_global_options_work_after_the_command(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main(["list", "--root", str(self.root)], prog="agentindex")
        self.assertEqual(code, 0)
        self.assertIn("2 docs", stdout.getvalue())

    def test_no_command_prints_help(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(main([], prog="agentindex"), 2)
        self.assertIn("examples:", stdout.getvalue())


class ImportCommandTest(CliTestCase):
    def test_guide(self):
        code, out, _ = self.run_cli("import", "--guide")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("# Migrating a CLAUDE.md into the knowledge base"))
        self.assertIn("## 1. Restructure the file", out)
        self.assertNotIn("summary:", out)  # front matter is for the index, not the reader

    def test_needs_a_file(self):
        code, _, err = self.run_cli("import")
        self.assertEqual(code, 2)
        self.assertIn("--guide", err)

    def test_reports_fixes_and_warnings(self):
        source = str(self.write("CLAUDE.md", "Setup\n=====\n\n**Install**\n\nRun make.\n"))
        code, out, _ = self.run_cli("import", source, "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("Converted 2 headings the index would not recognize:", out)
        self.assertIn("line 4: **Install**  ->  ## Install", out)
        self.assertIn("knowledge/install.md", out)
        self.assertNotIn("Warning:", out)
        self.write("CLAUDE.md", "Just some notes.\n")
        code, out, _ = self.run_cli("import", source, "--dry-run")
        self.assertIn("Warning: no headings to split at", out)
        self.assertIn("`agentindex import --guide` explains how", out)
