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
