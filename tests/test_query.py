import sqlite3
import unittest

from agentindex.errors import QueryError
from agentindex.query import MAX_TERMS, parse_query


class ParseQueryTest(unittest.TestCase):
    def test_stop_words_dropped_and_pairs_kept(self):
        q = parse_query("How do I roll back a deploy?")
        self.assertEqual(q.terms, ["roll", "back", "deploy"])
        self.assertEqual(q.pairs, [("roll", "back")])

    def test_only_stop_words_are_kept(self):
        self.assertEqual(parse_query("how to").terms, ["how", "to"])

    def test_prefix_only_for_longer_non_numeric_terms(self):
        alternatives = parse_query("db auth 404").alternatives()
        self.assertIn('"auth"*', alternatives)
        self.assertNotIn('"db"*', alternatives)
        self.assertNotIn('"404"*', alternatives)

    def test_punctuation_breaks_pairs(self):
        self.assertEqual(parse_query("deploy, rollback").pairs, [])
        self.assertEqual(parse_query("front-end build").pairs, [("front", "end"), ("end", "build")])

    def test_underscores_split_like_the_tokenizer(self):
        self.assertEqual(parse_query("snake_case").terms, ["snake", "case"])

    def test_quoted_phrases_are_required(self):
        q = parse_query('"feature flag" rollout')
        self.assertEqual(q.phrases, [["feature", "flag"]])
        self.assertEqual(q.terms, ["rollout"])
        self.assertIn('AND "feature flag"', q.to_fts())

    def test_quoted_single_word_is_a_term(self):
        q = parse_query('"deploy"')
        self.assertEqual((q.terms, q.phrases), (["deploy"], []))

    def test_exclusions(self):
        q = parse_query("deploy -staging --verbose")
        self.assertEqual(q.excluded, ["staging"])
        self.assertIn("verbose", q.terms)
        self.assertTrue(q.to_fts().endswith('NOT ("staging")'))

    def test_empty_and_exclusion_only_queries_fail(self):
        for text in ("", "   "):
            with self.assertRaises(QueryError):
                parse_query(text)
        with self.assertRaises(QueryError):
            parse_query("-foo").to_fts()
        with self.assertRaises(QueryError):
            parse_query("?!").to_fts()

    def test_many_exclusions_stay_flat(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE VIRTUAL TABLE t USING fts5(a)")
        expression = parse_query("deploy " + " ".join(f"-x{i}" for i in range(300))).to_fts()
        conn.execute("SELECT * FROM t WHERE t MATCH ?", (expression,)).fetchall()

    def test_terms_are_capped(self):
        q = parse_query(" ".join(f"word{i}" for i in range(40)))
        self.assertEqual(len(q.terms), MAX_TERMS)

    def test_hostile_input_never_breaks_fts5(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE VIRTUAL TABLE t USING fts5(a, tokenize='porter unicode61')")
        conn.execute("INSERT INTO t VALUES ('hello world')")
        for text in [
            '" AND OR NOT',
            "NEAR(a b)",
            "a* ^b {a}: c",
            'x"y',
            "café 🚀 日本語",
            "-a b",
            "(((",
            "col:value",
            '"unbalanced',
        ]:
            try:
                expression = parse_query(text).to_fts()
            except QueryError:
                continue
            conn.execute("SELECT * FROM t WHERE t MATCH ?", (expression,)).fetchall()


if __name__ == "__main__":
    unittest.main()
