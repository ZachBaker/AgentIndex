import unittest

from agentindex.markdown import (
    extract_links,
    first_paragraph,
    parse_document,
    parse_headings,
    plain_text,
    searchable_text,
    shorten,
    slugify,
    split_sections,
)


def headings(text):
    return [(h.level, h.text, h.anchor) for h in parse_headings(text.split("\n"))]


class HeadingTest(unittest.TestCase):
    def test_lines_in_code_fences_are_not_headings(self):
        text = (
            "# Real\n```bash\n# install deps\n```\n~~~\n## nope\n~~~~\n"
            "## Also real\n````\n```\n# still code\n````\n"
        )
        self.assertEqual(headings(text), [(1, "Real", "real"), (2, "Also real", "also-real")])

    def test_closing_fence_must_be_as_long_as_the_opening_one(self):
        self.assertEqual(headings("````\n```\n# code\n````\n# Real\n"), [(1, "Real", "real")])
        self.assertEqual(headings("~~~~\n~~~\n# code\n"), [])

    def test_unclosed_fence_runs_to_the_end(self):
        self.assertEqual(headings("# A\n```\n# B\n"), [(1, "A", "a")])

    def test_atx_heading_rules(self):
        text = "#hashtag\n####### seven\n    # indented code\n## Closing ##\n# C#\n#\n"
        self.assertEqual(
            headings(text),
            [(2, "Closing", "closing"), (1, "C#", "c"), (1, "", "section")],
        )

    def test_inline_markup_is_removed_from_heading_text(self):
        text = "## The `__init__.py` **file** and [links](x.md)\n"
        self.assertEqual(headings(text)[0][1], "The __init__.py file and links")

    def test_github_style_anchors(self):
        self.assertEqual(slugify("What's new in v2.0? (2024)"), "whats-new-in-v20-2024")
        self.assertEqual(slugify("A & B"), "a--b")
        self.assertEqual(slugify("Ünïcode Straße"), "ünïcode-straße")
        text = "# Setup\n## Setup\n## Setup\n## Setup-1\n"
        self.assertEqual(
            [h[2] for h in headings(text)], ["setup", "setup-1", "setup-2", "setup-1-1"]
        )

    def test_slugs_follow_github_unicode_rules(self):
        self.assertEqual(slugify("हिन्दी"), "हिन्दी")  # combining vowel signs are kept
        self.assertEqual(slugify("Cafe\u0301 menu"), "cafe\u0301-menu")
        self.assertEqual(slugify("O(n²) lookups"), "on-lookups")  # other numbers are dropped
        self.assertEqual(slugify("🚀 Launch – now"), "-launch-–-now")


class SectionTest(unittest.TestCase):
    TEXT = "Intro text.\n# Title\nAbout.\n## A\na text\n### A1\ndeep\n## B\nb text\n"

    def sections(self):
        lines = self.TEXT.split("\n")
        return split_sections(lines, parse_headings(lines), "Doc")

    def test_sections_own_text_and_subtrees(self):
        s = {x.anchor: x for x in self.sections()}
        self.assertEqual(s[""].heading, "Doc")  # text before the first heading
        self.assertEqual(s[""].text, "Intro text.")
        self.assertEqual(s["a"].text, "a text")
        self.assertEqual((s["a"].start, s["a"].end, s["a"].subtree_end), (3, 5, 7))
        self.assertEqual(s["a1"].trail, ["Title", "A", "A1"])
        self.assertEqual(s["title"].subtree_end, 10)


class LinkTest(unittest.TestCase):
    def test_relative_links_are_extracted(self):
        text = (
            'See [a](a.md), [b](../b.md#part "title"), ![img](d.png), [c](<c d.md>),\n'
            "[ext](https://x.test/y.md), [mail](mailto:a@b.c), [here](#local),\n"
            "`[code](not.md)`, [e](e%20f.md?raw=1)\n"
            "```\n[fenced](no.md)\n```\n"
            "[ref]: ref.md\n"
        )
        links = [
            (link.target, link.anchor, link.line, link.image)
            for link in extract_links(text.split("\n"))
        ]
        self.assertEqual(
            links,
            [
                ("a.md", "", 0, False),
                ("../b.md", "part", 0, False),
                ("d.png", "", 0, True),
                ("c d.md", "", 0, False),
                ("", "local", 1, False),
                ("e f.md", "", 2, False),
                ("ref.md", "", 6, False),
            ],
        )


class CommentAndFootnoteTest(unittest.TestCase):
    TEXT = (
        "# Guide\n\nSee the cache docs.[^ttl]\n\n"
        "[^ttl]: Configured by the varnish TTL setting.\n"
        "[Deprecated]: use v2 instead\n"
        "[Back to top](#)\n"
        "<!--\n## Setup\nOld instructions with [a link](gone.md).\n-->\n"
        "<!-- a one-line comment with [another](gone.md) -->\n"
        "## Setup\nCurrent steps.\n"
    )

    def test_html_comments_hide_headings_and_links(self):
        lines = self.TEXT.split("\n")
        self.assertEqual(headings(self.TEXT), [(1, "Guide", "guide"), (2, "Setup", "setup")])
        self.assertEqual(extract_links(lines), [])

    def test_footnotes_and_label_lines_are_text(self):
        text = searchable_text(self.TEXT)
        self.assertIn("varnish TTL setting", text)
        self.assertIn("use v2 instead", text)
        self.assertNotIn("Old instructions", text)

    def test_reference_definitions_still_work(self):
        links = extract_links(['[ref]: docs/a.md "Title"', "[ref2]: <b c.md>"])
        self.assertEqual([link.target for link in links], ["docs/a.md", "b c.md"])


class TextTest(unittest.TestCase):
    def test_plain_text(self):
        self.assertEqual(
            plain_text("Use **bold**, _em_, `__init__.py`, [link](x), <b>tag</b> and snake_case"),
            "Use bold, em, __init__.py, link, tag and snake_case",
        )

    def test_first_paragraph_skips_non_prose(self):
        text = (
            "# T\n\n<!--\ncomment\n-->\n```\ncode\n```\n| a | b |\n\n"
            "> Quoted **first**\nline two\n\nSecond.\n"
        )
        self.assertEqual(first_paragraph(text.split("\n")), "Quoted first line two")

    def test_first_paragraph_of_a_list_is_its_first_item(self):
        self.assertEqual(first_paragraph(["- one", "  more", "- two"]), "one more")

    def test_searchable_text(self):
        text = (
            "| A | B |\n|---|:-:|\n| [x](u.md) | **y** |\n- item\n---\n"
            "```\nkeep `this` | as is\n```\n[r]: r.md"
        )
        self.assertEqual(searchable_text(text), "A — B\nx — y\nitem\nkeep `this` | as is")

    def test_shorten(self):
        self.assertEqual(shorten("Short."), "Short.")
        long = "First sentence is here. " + "word " * 60
        self.assertEqual(shorten(long, 60), "First sentence is here.")
        self.assertTrue(shorten("word " * 60, 40).endswith("…"))


class ParseDocumentTest(unittest.TestCase):
    def test_metadata_precedence_and_normalization(self):
        doc = parse_document(
            '\ufeff---\r\ntitle: Front\r\ndescription: Desc.\r\ntags: [Ops, "#Deploy"]\r\n'
            "owner: me\r\n---\r\n# Heading\r\n\r\nFirst paragraph.\r\n",
            "fallback",
        )
        self.assertEqual(doc.title, "Front")
        self.assertEqual(doc.summary, "Desc.")
        self.assertEqual(doc.tags, ["ops", "deploy"])
        self.assertEqual(doc.meta, {"owner": "me"})
        self.assertEqual(doc.body_line, 6)
        self.assertTrue(doc.has_title and doc.has_summary)

    def test_fallbacks(self):
        doc = parse_document("# From H1\n\nFirst paragraph here.\n", "fallback")
        self.assertEqual((doc.title, doc.summary), ("From H1", "First paragraph here."))
        self.assertTrue(doc.has_title)
        self.assertFalse(doc.has_summary)
        bare = parse_document("Just text.\n", "Release process")
        self.assertEqual(bare.title, "Release process")
        self.assertFalse(bare.has_title)

    def test_warnings_are_collected(self):
        doc = parse_document("---\ntitle: [a, b]\n---\nx\n", "f")
        self.assertEqual(doc.title, "a, b")
        self.assertTrue(any("should be text" in w for w in doc.warnings))


if __name__ == "__main__":
    unittest.main()
