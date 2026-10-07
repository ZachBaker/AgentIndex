import json
import sqlite3

from agentindex import KnowledgeIndex, NotFoundError, QueryError, load_config
from agentindex.store import LONG_DOC_WORDS
from tests.helpers import ProjectTestCase

DEPLOY = """
---
title: Deploying to production
summary: How releases reach production and how to undo one.
tags: [deploy, ops]
related: [auth]
---

# Deploying to production

Run it. See [migrations](../migrations.md#rolling-back) and [code](../../src/deploy.py).

## Rollback

Roll back with `deploy --rollback`.

### Data

Data is not rolled back.

## Feature flags

Flags live in [the flag service](#rollback).
"""


class StoreTestCase(ProjectTestCase):
    files = {
        "src/deploy.py": "print('deploy')\n",
        "knowledge/ops/deploying.md": DEPLOY,
        "knowledge/migrations.md": """
            ---
            title: Database migrations
            summary: Writing and reverting schema migrations.
            tags: [database]
            ---
            # Database migrations

            Write reversible migrations.

            ## Rolling back

            Use `migrate down`.
        """,
        "knowledge/auth.md": "# Authentication\n\nSessions live in redis.\n",
    }


class SyncTest(StoreTestCase):
    def test_initial_sync_then_nothing_changes(self):
        index = self.open_index(auto_sync=False)
        report = index.sync()
        self.assertEqual(sorted(report.added), ["auth", "migrations", "ops/deploying"])
        again = index.sync()
        self.assertFalse(again.changed)
        self.assertEqual(again.unchanged, 3)

    def test_changes_additions_and_deletions(self):
        index = self.open_index(auto_sync=False)
        index.sync()
        self.write("knowledge/auth.md", "# Authentication\n\nTokens now.\n")
        self.write("knowledge/new.md", "# New\n")
        (self.root / "knowledge/migrations.md").unlink()
        report = index.sync()
        self.assertEqual(
            (report.added, report.updated, report.removed), (["new"], ["auth"], ["migrations"])
        )
        self.assertEqual(index.search("tokens")["results"][0]["id"], "auth")

    def test_touched_but_identical_file_is_not_reparsed(self):
        index = self.open_index(auto_sync=False)
        index.sync()
        path = self.root / "knowledge/auth.md"
        self.write("knowledge/auth.md", path.read_text(encoding="utf-8"))
        report = index.sync()
        self.assertEqual((report.updated, report.unchanged), ([], 3))
        self.assertEqual(index.sync(force=True).updated.__len__(), 3)

    def test_queries_sync_automatically(self):
        index = self.open_index()
        self.assertEqual(index.search("redis")["total"], 1)
        self.write("knowledge/cache.md", "# Cache\n\nAlso redis.\n")
        self.assertEqual(index.search("redis")["total"], 2)

    def test_min_sync_interval_throttles(self):
        index = self.open_index(min_sync_interval=3600)
        index.search("redis")
        self.write("knowledge/cache.md", "# Cache\n\nAlso redis.\n")
        self.assertEqual(index.search("redis")["total"], 1)

    def test_skips_hidden_unrelated_and_excluded_files(self):
        self.write(".agentindex.json", '{"sources": ["knowledge"], "exclude": ["**/drafts/**"]}')
        self.write("knowledge/.hidden/x.md", "# Hidden\n")
        self.write("knowledge/node_modules/y.md", "# Dep\n")
        self.write("knowledge/drafts/z.md", "# Draft\n")
        self.write("knowledge/notes.txt", "text\n")
        self.write("knowledge/page.mdx", "# Page\n")
        ids = [d["id"] for d in self.open_index().list_docs()["documents"]]
        self.assertEqual(ids, ["auth", "migrations", "ops/deploying", "page"])

    def test_duplicate_ids_and_missing_sources(self):
        self.write(".agentindex.json", '{"sources": ["knowledge", "more", "gone"]}')
        self.write("more/auth.md", "# Other auth\n")
        index = self.open_index(auto_sync=False)
        report = index.sync()
        self.assertEqual(report.duplicates, [("auth", "knowledge/auth.md", "more/auth.md")])
        self.assertEqual(report.missing_sources, ["gone"])
        messages = [i["message"] for i in index.check()["issues"] if i["severity"] == "error"]
        self.assertTrue(any("already used" in m for m in messages))
        self.assertTrue(any("does not exist" in m for m in messages))

    def test_single_file_source(self):
        self.write(".agentindex.json", '{"sources": ["knowledge", "README.md"]}')
        self.write("README.md", "# Readme\n\nHello.\n")
        self.assertEqual(self.open_index().read("README")["title"], "Readme")

    def test_invalid_utf8_is_indexed_with_a_warning(self):
        (self.root / "knowledge/bad.md").write_bytes(b"# Bad \xff bytes\n")
        index = self.open_index()
        self.assertIn("Bad", index.read("bad")["title"])
        warnings = [i["message"] for i in index.check()["issues"] if i["path"].endswith("bad.md")]
        self.assertTrue(any("UTF-8" in w for w in warnings))

    def test_schema_change_rebuilds_the_database(self):
        index = self.open_index()
        index.sync()
        index.conn.execute("UPDATE meta SET value = 'old' WHERE key = 'schema_version'")
        index.close()
        reopened = self.open_index(auto_sync=False)
        self.assertEqual(reopened.status()["documents"], 0)  # rebuilt, then empty until synced
        self.assertEqual(len(reopened.sync().added), 3)

    def test_corrupt_database_is_replaced(self):
        db = self.root / ".agentindex/index.db"
        db.parent.mkdir(parents=True)
        db.write_bytes(b"this is not a database" * 100)
        self.assertEqual(self.open_index().search("redis")["total"], 1)

    def test_memory_database(self):
        index = KnowledgeIndex(load_config(self.root, db=":memory:"))
        self.addCleanup(index.close)
        self.assertEqual(index.search("redis")["total"], 1)
        self.assertFalse((self.root / ".agentindex").exists())


class ReadTest(StoreTestCase):
    def test_whole_doc(self):
        doc = self.open_index().read("ops/deploying")
        self.assertEqual(doc["path"], "knowledge/ops/deploying.md")
        self.assertTrue(doc["content"].startswith("# Deploying to production"))
        self.assertEqual(doc["line"], 8)
        self.assertIsNone(doc["section"])
        self.assertEqual(
            [e["anchor"] for e in doc["outline"]],
            ["deploying-to-production", "rollback", "data", "feature-flags"],
        )

    def test_section_by_anchor_heading_or_prefix(self):
        index = self.open_index()
        by_anchor = index.read("ops/deploying#rollback")
        self.assertEqual(
            by_anchor["content"],
            "## Rollback\n\nRoll back with `deploy --rollback`.\n\n### Data\n\n"
            "Data is not rolled back.",
        )
        self.assertEqual(by_anchor["line"], 12)
        self.assertEqual(
            index.read("ops/deploying", section="Feature flags")["section"]["anchor"],
            "feature-flags",
        )
        self.assertEqual(
            index.read("ops/deploying", section="#feat")["section"]["anchor"], "feature-flags"
        )

    def test_unknown_section_lists_anchors(self):
        with self.assertRaises(NotFoundError) as ctx:
            self.open_index().read("ops/deploying#nope")
        self.assertIn("ops/deploying#rollback", ctx.exception.suggestions)

    def test_forgiving_references(self):
        index = self.open_index()
        for ref in (
            "knowledge/ops/deploying.md",
            "./knowledge/ops/deploying.md",
            "ops/deploying.md",
            "OPS/Deploying",
            "deploying",
            str(self.root / "knowledge/ops/deploying.md"),
        ):
            self.assertEqual(index.read(ref)["id"], "ops/deploying", ref)

    def test_ambiguous_suffix(self):
        self.write("knowledge/other/deploying.md", "# Other\n")
        with self.assertRaises(NotFoundError) as ctx:
            self.open_index().read("deploying")
        self.assertEqual(ctx.exception.suggestions, ["ops/deploying", "other/deploying"])

    def test_unknown_doc_suggests_close_ids_or_search_hits(self):
        index = self.open_index()
        with self.assertRaises(NotFoundError) as ctx:
            index.read("ops/deployng")
        self.assertEqual(ctx.exception.suggestions[0], "ops/deploying")
        with self.assertRaises(NotFoundError) as ctx:
            index.read("redis")
        self.assertEqual(ctx.exception.suggestions, ["auth"])

    def test_links_and_backlinks(self):
        index = self.open_index()
        deploy = index.read("ops/deploying")
        self.assertEqual([d["id"] for d in deploy["links"]], ["auth", "migrations"])
        self.assertEqual(
            [d["id"] for d in index.read("migrations")["backlinks"]], ["ops/deploying"]
        )
        self.assertEqual([d["id"] for d in index.read("auth")["backlinks"]], ["ops/deploying"])

    def test_outline_word_counts_include_subsections(self):
        outline = {
            e["anchor"]: e["words"] for e in self.open_index().outline("ops/deploying")["outline"]
        }
        self.assertGreater(outline["rollback"], outline["data"])

    def test_metadata_in_read(self):
        doc = self.open_index().read("ops/deploying")
        self.assertEqual(doc["tags"], ["deploy", "ops"])
        self.assertEqual(doc["summary"], "How releases reach production and how to undo one.")


class ListAndStatusTest(StoreTestCase):
    def test_list_and_tag_filters(self):
        index = self.open_index()
        listing = index.list_docs()
        self.assertEqual(listing["total"], 3)
        self.assertIn({"tag": "deploy", "count": 1}, listing["tags"])
        self.assertEqual(
            [d["id"] for d in index.list_docs(tags=["DEPLOY"])["documents"]], ["ops/deploying"]
        )
        self.assertEqual(index.list_docs(tags=["deploy", "database"])["total"], 0)

    def test_status(self):
        status = self.open_index().status()
        self.assertEqual(status["documents"], 3)
        self.assertEqual(status["sources"], [{"path": "knowledge", "exists": True}])
        self.assertTrue(status["database"].endswith("index.db"))
        self.assertIsNotNone(status["last_sync"])


class SearchApiTest(StoreTestCase):
    def test_result_shape(self):
        result = self.open_index().search("rollback", limit=1)
        self.assertEqual(result["indexed"], 3)
        top = result["results"][0]
        self.assertEqual(
            set(top), {"id", "title", "path", "summary", "tags", "words", "score", "sections"}
        )
        self.assertEqual(top["sections"][0]["anchor"], "rollback")
        self.assertIn("**", top["sections"][0]["snippet"])

    def test_limit_total_and_tags(self):
        index = self.open_index()
        result = index.search("rolling back", limit=1)
        self.assertEqual((result["total"], len(result["results"])), (2, 1))
        self.assertEqual(index.search("rolling back", tags=["database"])["total"], 1)
        self.assertEqual(len(index.search("back", limit=0)["results"]), 1)  # clamped to >= 1

    def test_phrases_and_exclusions(self):
        index = self.open_index()
        self.assertEqual(
            [r["id"] for r in index.search('"migrate down"')["results"]], ["migrations"]
        )
        self.assertNotIn("migrations", [r["id"] for r in index.search("back -migrate")["results"]])
        with self.assertRaises(QueryError):
            index.search("-migrate")

    def test_empty_knowledge_base(self):
        for path in (self.root / "knowledge").rglob("*.md"):
            path.unlink()
        self.assertEqual(
            self.open_index().search("anything"),
            {"query": "anything", "total": 0, "indexed": 0, "results": []},
        )


class CheckTest(ProjectTestCase):
    files = {
        "src/real.py": "",
        "elsewhere/notes.md": "# Not indexed but exists\n",
        "knowledge/good.md": """
            ---
            title: Good
            summary: A good doc.
            related: [missing-doc]
            ---
            # Good

            [ok](other.md#section-one), [code](../src/real.py), [outside](../elsewhere/notes.md),
            [broken doc](nope.md), [broken code](../src/gone.py), [bad anchor](other.md#nope),
            [self](#good), [self missing](#nowhere), [escape](../../../x.md), [web](https://x.test)
        """,
        "knowledge/other.md": "---\nsummary: S.\n---\n# Other\n\n## Section one\n\ntext\n",
        "knowledge/bare.md": "no title, no summary here\n",
        "knowledge/empty.md": "---\ntitle: Empty\nsummary: Nothing.\n---\n",
        "knowledge/weird.md": "---\ntitle: Weird\nsummary: S.\nnested:\n  a: b\n---\n# Weird\n",
        "knowledge/long.md": "---\ntitle: Long\nsummary: S.\n---\n"
        + "word " * (LONG_DOC_WORDS + 1),
    }

    def test_issues(self):
        result = self.open_index().check()
        found = {
            (i["path"].split("/")[-1], i["severity"], i["line"], i["message"].split(":")[0])
            for i in result["issues"]
        }
        expected = {
            ("good.md", "error", 1, "related doc 'missing-doc' does not exist"),
            ("good.md", "error", 9, "broken link"),
            ("good.md", "error", 9, "broken link"),
            ("good.md", "warning", 9, "link to missing section knowledge/other.md#nope"),
            ("good.md", "warning", 10, "link to missing section #nowhere"),
            ("bare.md", "warning", None, "no title"),
            ("bare.md", "warning", None, "no summary"),
            ("empty.md", "warning", None, "document is empty"),
            ("weird.md", "warning", None, "front matter key 'nested'"),
            ("long.md", "warning", None, f"{LONG_DOC_WORDS + 1} words"),
        }
        self.assertEqual(found, expected)
        self.assertEqual((result["errors"], result["warnings"]), (3, 7))
        broken = sorted(i["message"] for i in result["issues"] if "broken" in i["message"])
        self.assertEqual(
            broken,
            [
                "broken link: knowledge/nope.md does not exist",
                "broken link: src/gone.py does not exist",
            ],
        )

    def test_check_resyncs_and_stores_nothing_extra(self):
        index = self.open_index()
        index.check()
        tables = {
            r[0] for r in index.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        self.assertIn("documents", tables)
        meta = dict(index.conn.execute("SELECT key, value FROM meta").fetchall())
        self.assertEqual(set(meta), {"schema_version", "last_sync"})


class ConfigFileTest(ProjectTestCase):
    def test_bad_config_is_reported(self):
        from agentindex import ConfigError

        for text in (
            '{"source": ["x"]}',
            "not json",
            '{"sources": []}',
            '{"sources": ["../x"]}',
            '{"db": 3}',
            "[]",
        ):
            self.write(".agentindex.json", text)
            with self.assertRaises(ConfigError, msg=text):
                load_config(self.root)

    def test_comment_keys_and_normalized_sources(self):
        self.write(".agentindex.json", json.dumps({"//": "c", "sources": ["./docs/"]}))
        self.assertEqual(load_config(self.root).sources, ["docs"])

    def test_database_is_a_regular_sqlite_file(self):
        self.write("knowledge/a.md", "# A\n")
        self.open_index().sync()
        with sqlite3.connect(self.root / ".agentindex/index.db") as conn:
            self.assertEqual(conn.execute("SELECT id FROM documents").fetchall(), [("a",)])


class SourceChangesTest(ProjectTestCase):
    files = {"docs/v1/setup.md": "# Setup v1\n", "docs/adr/one.md": "# ADR one\n"}

    def test_overlapping_sources_index_each_file_once(self):
        self.write(".agentindex.json", '{"sources": ["docs", "docs/adr", "docs/v1/setup.md"]}')
        index = self.open_index()
        self.assertEqual([d["id"] for d in index.list_docs()["documents"]], ["adr/one", "v1/setup"])
        self.assertEqual(index.check()["errors"], 0)

    def test_ids_follow_changes_to_the_sources(self):
        self.write(".agentindex.json", '{"sources": ["docs/v1"]}')
        self.assertEqual([d["id"] for d in self.open_index().list_docs()["documents"]], ["setup"])
        self.write(".agentindex.json", '{"sources": ["docs"]}')
        self.write("docs/setup.md", "# Setup now\n")
        index = self.open_index(auto_sync=False)
        report = index.sync()
        self.assertEqual(report.duplicates, [])
        self.assertEqual(
            [d["id"] for d in index.list_docs()["documents"]], ["adr/one", "setup", "v1/setup"]
        )
        self.assertEqual(index.read("v1/setup")["title"], "Setup v1")

    def test_config_with_a_byte_order_mark(self):
        self.write(".agentindex.json", '\ufeff{"sources": ["docs"]}')
        self.assertEqual(load_config(self.root).sources, ["docs"])
