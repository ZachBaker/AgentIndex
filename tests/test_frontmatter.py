import unittest

from agentindex.frontmatter import parse_frontmatter, split_frontmatter


class SplitTest(unittest.TestCase):
    def test_no_front_matter(self):
        self.assertEqual(split_frontmatter("# Title\n"), (None, "# Title\n", 0, None))

    def test_front_matter_and_body_offset(self):
        front, body, offset, error = split_frontmatter("---\ntitle: X\n---\n# Body\n")
        self.assertEqual((front, body, offset, error), ("title: X", "# Body\n", 3, None))

    def test_dots_close_the_block(self):
        self.assertEqual(split_frontmatter("---\na: 1\n...\nbody")[1], "body")

    def test_unclosed_block_is_body_with_error(self):
        front, body, offset, error = split_frontmatter("---\ntitle: X\n# Body")
        self.assertIsNone(front)
        self.assertEqual(body, "---\ntitle: X\n# Body")
        self.assertIn("never closed", error)

    def test_rule_later_in_file_is_not_front_matter(self):
        self.assertIsNone(split_frontmatter("text\n---\nmore")[0])


class ParseTest(unittest.TestCase):
    def parse(self, text):
        return parse_frontmatter(text)

    def test_scalars_quotes_and_comments(self):
        data, warnings = self.parse(
            'title: "Deploy: the \\"guide\\""  # comment\n'
            "single: 'it''s # not a comment'\n"
            "plain: value # trailing comment\n"
            "url: http://x.test/#frag\n"
        )
        self.assertEqual(data["title"], 'Deploy: the "guide"')
        self.assertEqual(data["single"], "it's # not a comment")
        self.assertEqual(data["plain"], "value")
        self.assertEqual(data["url"], "http://x.test/#frag")
        self.assertEqual(warnings, [])

    def test_inline_and_block_lists(self):
        data, _ = self.parse(
            'tags: [ops, "a, b", \'c\']\nkeywords:\n  - db\n  - "schema"  # c\nempty: []\n'
        )
        self.assertEqual(data["tags"], ["ops", "a, b", "c"])
        self.assertEqual(data["keywords"], ["db", "schema"])
        self.assertEqual(data["empty"], [])

    def test_unindented_block_list(self):
        self.assertEqual(self.parse("tags:\n- a\n- b\n")[0]["tags"], ["a", "b"])

    def test_inline_list_spanning_lines(self):
        data, warnings = self.parse("tags: [a,\n  b]\n")
        self.assertEqual((data["tags"], warnings), (["a", "b"], []))

    def test_folded_and_literal_blocks(self):
        data, _ = self.parse(
            "summary: >\n  One\n  two.\n\n  Three.\nnotes: |\n  line 1\n  line 2\nnext: x\n"
        )
        self.assertEqual(data["summary"], "One two.\nThree.")
        self.assertEqual(data["notes"], "line 1\nline 2")
        self.assertEqual(data["next"], "x")

    def test_plain_scalar_continuation(self):
        self.assertEqual(self.parse("summary: first\n  second\n")[0]["summary"], "first second")

    def test_keys_are_case_insensitive(self):
        self.assertIn("title", self.parse("Title: X\n")[0])

    def test_problems_are_warnings_not_failures(self):
        data, warnings = self.parse("title: X\nnot a key\nnested:\n  sub: y\ntitle: Y\ntags: [a\n")
        self.assertEqual(data["title"], "Y")
        self.assertEqual(len(warnings), 4)
        self.assertIn("line 3", warnings[0])  # file line: block starts on line 2


if __name__ == "__main__":
    unittest.main()
