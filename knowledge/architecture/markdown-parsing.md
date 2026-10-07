---
title: Markdown parsing
summary: What the indexer understands in a markdown file. Covers the front matter subset, titles and summaries, headings and anchors, sections, links, and the code-fence rules that keep it from misreading snippets.
tags: [architecture, parsing]
keywords: [front matter, frontmatter, yaml, headings, anchors, slugs, sections, links, summary, code fences, commonmark, title]
related: [architecture/database]
---

# Markdown parsing

Parsing lives in [markdown.py](../../agentindex/markdown.py) and
[frontmatter.py](../../agentindex/frontmatter.py). It is not a full CommonMark parser. It
extracts what the index needs and is strict about the one thing that matters most: lines
inside fenced code blocks and HTML comments are never headings or links, so
`# install deps` in a shell snippet does not start a section, and a commented-out
`## Old setup` does not either. Comments are also left out of the index.

## Front matter

Front matter is an optional block between `---` lines at the very top of a file. The
supported YAML is: `key: value` (plain, `"double"` or `'single'` quoted), inline lists
`[a, b]`, block lists (`- a`), `>` folded and `|` literal blocks, plain values continued on
indented lines, and `#` comments. Anything else, such as nested mappings, is kept as text
and reported as a warning by `check`; it never fails the doc. A block that is never closed
is treated as body text, with a warning.

The recognized keys are `title`, `summary` (or `description`), `tags` (lowercased),
`keywords` and `related`. Other keys are stored in `meta` and returned by `read --json`.

## Titles and summaries

- The title is front matter `title`, else the first `# H1`, else the file name made
  readable (`release-process` becomes "Release process").
- The summary is front matter `summary` or `description`, else the first paragraph of
  prose (skipping headings, code, tables, images and HTML comments), trimmed to about 220
  characters at a sentence boundary.

## Headings, anchors and sections

ATX headings (`#` to `######` followed by a space) outside code fences start sections.
Setext headings, underlined with `===` or `---`, are not recognized; `import` converts
them (and bold-line headings) to ATX headings before splitting a file. Anchors follow
GitHub's rules (github-slugger): lowercase; keep letters, combining marks, digits, `_`
and dashes; drop other punctuation and symbols; turn spaces into `-`; number repeated
headings `-1`, `-2` and so on. So anchors copied from GitHub work, in any script.

A section's own text runs to the next heading of any level, and that is what gets indexed
and scored. Reading a section returns it with all of its subsections, up to the next
heading of the same or a higher level. Text before the first heading forms a section
without an anchor.

## Links

Inline links, images and reference definitions (`[label]: target "title"`) with relative
targets are recorded, and external URLs and bare `#` links are ignored. Footnotes
(`[^1]: text`) and lines like `[Note]: prose` are text, not links. Targets resolve relative to the doc, or to the root when they
start with `/`. Links to markdown files feed "Links to" and "Linked from" when a doc is
read. Links to any other path are verified by `check`, which keeps references to code
honest when files move.

## Indexed text

Before indexing, inline markup is reduced to plain text: links keep their text but lose
the URL, emphasis markers and HTML tags are removed, and code blocks are kept verbatim.
This stops URLs from matching queries and makes snippets readable.
