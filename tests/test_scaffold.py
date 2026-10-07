import json

from agentindex import AgentIndexError, KnowledgeIndex, load_config
from agentindex.frontmatter import parse_frontmatter, split_frontmatter
from agentindex.scaffold import SKILL_PATH, import_markdown, init, normalize_headings
from tests.helpers import ProjectTestCase

BIG_CLAUDE_MD = """
# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

Acme is a billing service: a Go API with a React dashboard.

## Commands

```bash
# install
make deps
## not a heading
```

Run `make test` before committing.

## Architecture: overview & data flow

Requests go through the gateway.

### Payments

Stripe webhooks land in `api/payments`.

## Empty section

## Commands

Second commands section.
"""


class InitTest(ProjectTestCase):
    def test_fresh_repository(self):
        result = init(self.root)
        self.assertEqual(result["command"], "agentindex")
        config = json.loads((self.root / ".agentindex.json").read_text())
        self.assertEqual(config, {"sources": ["knowledge"]})
        self.assertTrue((self.root / "knowledge/start-here.md").is_file())
        self.assertTrue((self.root / "knowledge/writing-docs.md").is_file())
        self.assertIn(".agentindex/", (self.root / ".gitignore").read_text().splitlines())
        mcp = json.loads((self.root / ".mcp.json").read_text())
        self.assertEqual(
            mcp["mcpServers"]["agentindex"], {"command": "agentindex", "args": ["mcp"]}
        )
        claude_md = (self.root / "CLAUDE.md").read_text()
        self.assertIn('agentindex search "<keywords>"', claude_md)
        self.assertIn("`knowledge/`", claude_md)
        self.assertLess(len(claude_md.splitlines()), 20)
        self.assertEqual(result["notes"], [])
        self.assertFalse((self.root / SKILL_PATH).exists())  # nothing to migrate

    def test_starter_docs_pass_check(self):
        init(self.root)
        with KnowledgeIndex(load_config(self.root)) as index:
            result = index.check()
            self.assertEqual((result["errors"], result["warnings"]), (0, 0), result["issues"])
            self.assertEqual(
                index.search("how do I write a new doc")["results"][0]["id"], "writing-docs"
            )

    def test_is_idempotent_and_preserves_existing_files(self):
        self.write(".gitignore", "node_modules/")
        self.write(".mcp.json", '{"mcpServers": {"other": {"command": "x"}}}')
        self.write("CLAUDE.md", "# Big file\n\nLots of knowledge.\n")
        first = init(self.root, docs="docs/kb")
        second = init(self.root)
        self.assertEqual(second["docs"], "docs/kb")  # taken from the existing config
        self.assertTrue(all(a.startswith("kept") for a in second["actions"]), second["actions"])
        self.assertEqual((self.root / ".gitignore").read_text().count(".agentindex/"), 1)
        self.assertTrue((self.root / ".gitignore").read_text().startswith("node_modules/\n"))
        mcp = json.loads((self.root / ".mcp.json").read_text())
        self.assertEqual(sorted(mcp["mcpServers"]), ["agentindex", "other"])
        self.assertEqual(
            (self.root / "CLAUDE.md").read_text(), "# Big file\n\nLots of knowledge.\n"
        )
        self.assertIn("import --guide", first["notes"][0])
        skill = (self.root / SKILL_PATH).read_text()
        self.assertIn("name: migrate-claude-md", skill)
        self.assertIn("agentindex import --guide", skill)
        self.assertIn("docs/kb/", skill)

    def test_vendored_copy_uses_python_module(self):
        self.write("agentindex/__init__.py", "")
        result = init(self.root, mcp=True)
        self.assertEqual(result["command"], "python3 -m agentindex")
        mcp = json.loads((self.root / ".mcp.json").read_text())
        self.assertEqual(mcp["mcpServers"]["agentindex"]["args"], ["-m", "agentindex", "mcp"])

    def test_invalid_mcp_json_is_not_clobbered(self):
        self.write(".mcp.json", "{oops")
        with self.assertRaises(AgentIndexError):
            init(self.root)
        self.assertEqual((self.root / ".mcp.json").read_text(), "{oops")

    def test_mcp_json_with_a_byte_order_mark(self):
        self.write(".mcp.json", '\ufeff{"mcpServers": {}}')
        init(self.root)
        self.assertIn("agentindex", json.loads((self.root / ".mcp.json").read_text())["mcpServers"])

    def test_no_mcp(self):
        init(self.root, mcp=False)
        self.assertFalse((self.root / ".mcp.json").exists())


class ImportTest(ProjectTestCase):
    files = {"CLAUDE.md": BIG_CLAUDE_MD}

    def run_import(self, **kwargs):
        return import_markdown(self.root / "CLAUDE.md", self.root / "knowledge", **kwargs)["docs"]

    def test_splits_sections_into_docs(self):
        planned = self.run_import()
        names = [p["path"].name for p in planned]
        self.assertEqual(
            names,
            ["overview.md", "commands.md", "architecture-overview-data-flow.md", "commands-2.md"],
        )
        self.assertTrue(all(p["status"] == "created" for p in planned))

        overview = (self.root / "knowledge/overview.md").read_text()
        self.assertNotIn("provides guidance to Claude Code", overview)
        self.assertIn("Acme is a billing service", overview)

        commands = (self.root / "knowledge/commands.md").read_text()
        front, body, _, _ = split_frontmatter(commands)
        data, warnings = parse_frontmatter(front)
        self.assertEqual(data, {"title": "Commands", "summary": "Run make test before committing."})
        self.assertIn("# install\nmake deps\n## not a heading", body)  # code untouched
        self.assertTrue(body.startswith("\n# Commands"))

        architecture = (self.root / "knowledge/architecture-overview-data-flow.md").read_text()
        data, warnings = parse_frontmatter(split_frontmatter(architecture)[0])
        self.assertEqual((data["title"], warnings), ("Architecture: overview & data flow", []))
        self.assertIn("\n## Payments\n", architecture)  # ### shifted up a level

    def test_imported_docs_are_searchable(self):
        self.run_import()
        with KnowledgeIndex(load_config(self.root)) as index:
            self.assertEqual(
                index.search("stripe webhooks")["results"][0]["id"],
                "architecture-overview-data-flow",
            )
            self.assertEqual(index.check()["errors"], 0)

    def test_dry_run_and_existing_files(self):
        planned = self.run_import(dry_run=True)
        self.assertTrue(all(p["status"] == "would create" for p in planned))
        self.assertFalse((self.root / "knowledge").exists())
        self.write("knowledge/commands.md", "mine")
        statuses = {p["path"].name: p["status"] for p in self.run_import()}
        self.assertEqual(statuses["commands.md"], "exists, skipped")
        self.assertEqual((self.root / "knowledge/commands.md").read_text(), "mine")
        statuses = {p["path"].name: p["status"] for p in self.run_import(force=True)}
        self.assertEqual(statuses["commands.md"], "overwrote")

    def test_split_level(self):
        names = [p["path"].name for p in self.run_import(level=3, dry_run=True)]
        self.assertIn("payments.md", names)

    def test_nothing_to_split_at_warns(self):
        self.write("CLAUDE.md", "# Notes\n\nSome text.\n\n### Deep\n\nMore text.\n")
        result = import_markdown(self.root / "CLAUDE.md", self.root / "knowledge", dry_run=True)
        self.assertEqual([p["path"].name for p in result["docs"]], ["overview.md"])
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn("try --level 3", result["warnings"][0])
        self.write("CLAUDE.md", "Just a paragraph of notes.\n")
        result = import_markdown(self.root / "CLAUDE.md", self.root / "knowledge", dry_run=True)
        self.assertIn("add a '## Topic' heading", result["warnings"][0])

    def test_long_section_warns(self):
        self.write("CLAUDE.md", "## Short\n\nFine.\n\n## Huge\n\n" + "word " * 2600 + "\n")
        result = import_markdown(self.root / "CLAUDE.md", self.root / "knowledge", dry_run=True)
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn("huge.md has 2601 words", result["warnings"][0])

    def test_bad_input(self):
        with self.assertRaises(AgentIndexError):
            import_markdown(self.root / "missing.md", self.root / "knowledge")
        with self.assertRaises(AgentIndexError):
            self.run_import(level=7)


MESSY_CLAUDE_MD = """---
owner: platform
---
Acme Guide
==========

Acme is a billing service.

Commands
--------

Run `make test`.

**Testing:**
- unit tests live in `tests/`

**Never push to main.**

**Deploys**

Use the deploy script.

```markdown
Not a heading
-------------
**Not a heading either**
```
"""


class NormalizeHeadingsTest(ProjectTestCase):
    files = {"CLAUDE.md": MESSY_CLAUDE_MD}

    def test_setext_and_bold_lines_become_headings(self):
        result = import_markdown(self.root / "CLAUDE.md", self.root / "knowledge")
        self.assertEqual([p["path"].name for p in result["docs"]], ["overview.md", "commands.md"])
        self.assertEqual(
            [(f["line"], f["after"]) for f in result["fixes"]],
            [(4, "# Acme Guide"), (9, "## Commands"), (14, "### Testing"), (19, "### Deploys")],
        )
        self.assertEqual(result["warnings"], [])
        commands = (self.root / "knowledge/commands.md").read_text()
        self.assertIn("\n# Commands\n", commands)
        self.assertIn("\n## Testing\n- unit tests", commands)
        self.assertIn("\n**Never push to main.**\n", commands)  # a rule, not a heading
        self.assertIn("\n## Deploys\n", commands)
        self.assertIn("Not a heading\n-------------\n**Not a heading either**", commands)
        overview = (self.root / "knowledge/overview.md").read_text()
        self.assertNotIn("Acme Guide", overview)  # the setext title was the file's title

    def test_rules_that_are_not_headings(self):
        lines = [
            "Para line one",
            "para line two",
            "---",  # under a multi-line paragraph: left alone
            "",
            "- item",
            "---",  # under a list item
            "",
            "Text before",
            "**Bold right after text**",  # not at the start of a block
            "",
            "**This bold line has far too many words to be a heading**",
            "",
            "**Setup** and more text",
        ]
        out, fixes = normalize_headings(lines)
        self.assertEqual((out, fixes), (lines, []))

    def test_bold_headings_nest_under_the_current_section(self):
        out, _ = normalize_headings(["## Ops", "", "**Deploys**", "", "**Rollback**", "", "x"])
        self.assertEqual(out[2:5], ["### Deploys", "", "### Rollback"])
        out, _ = normalize_headings(["**Setup**", "", "x"])
        self.assertEqual(out[0], "## Setup")  # no section yet: a top-level topic
