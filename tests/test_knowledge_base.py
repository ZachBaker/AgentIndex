"""This repository's own knowledge base and CLAUDE.md stay healthy and useful."""

import os
import unittest
from pathlib import Path
from unittest import mock

from agentindex import KnowledgeIndex, load_config

REPO_ROOT = Path(__file__).resolve().parent.parent

# Questions an agent working on this repo would ask, and the doc that answers each.
QUESTIONS = [
    ("how do I add a new doc", "writing-docs"),
    ("why does ranking use a smoothed idf", "architecture/search-ranking"),
    ("database schema tables", "architecture/database"),
    ("mcp tool names", "interfaces/mcp-server"),
    ("configure sources and exclude patterns", "configuration"),
    ("run the tests", "development/testing"),
    ("python version compatibility", "development/conventions"),
    ("migrate an existing claude.md", "guides/adopting-agentindex"),
    ("restructure claude.md headings before import", "migrating-claude-md"),
    ("http endpoints", "interfaces/http-api"),
    ("exit codes", "interfaces/cli"),
    ("code fences", "architecture/markdown-parsing"),
    ("read a single section", "using-the-index"),
    ("what is agentindex", "start-here"),
    ("find docs that contradict each other", "architecture/contradictions"),
]


class KnowledgeBaseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with mock.patch.dict(os.environ):
            os.environ.pop("AGENTINDEX_ROOT", None)
            config = load_config(REPO_ROOT, db=":memory:")
        cls.index = KnowledgeIndex(config)

    @classmethod
    def tearDownClass(cls):
        cls.index.close()

    def test_check_is_clean(self):
        result = self.index.check()
        self.assertEqual(result["issues"], [])

    def test_docs_do_not_contradict_each_other(self):
        self.assertEqual(self.index.conflicts()["conflicts"], [])

    def test_questions_find_their_docs(self):
        for question, expected in QUESTIONS:
            with self.subTest(question=question):
                top = [r["id"] for r in self.index.search(question, limit=3)["results"]]
                self.assertIn(expected, top)

    def test_claude_md_stays_a_pointer(self):
        text = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertLessEqual(len(text.splitlines()), 25, "move knowledge into knowledge/ instead")
        self.assertIn("python3 -m agentindex search", text)
        self.assertIn("read start-here", text)
