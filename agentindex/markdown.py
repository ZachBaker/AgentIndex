"""Markdown structure: headings, sections, links, summaries, and document parsing.

This is deliberately not a full CommonMark parser. It understands exactly what
the index needs and is careful about the one thing that matters most: lines
inside fenced code blocks (``# install deps`` in a shell snippet) and HTML
comments are never mistaken for headings or links.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import unquote

from .frontmatter import parse_frontmatter, split_frontmatter

_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_NESTED_FENCE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
_CLOSING_HASHES = re.compile(r"(?:^|[ \t]+)#+[ \t]*$")
_RULE = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_TABLE_RULE = re.compile(r"^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$")
_INLINE_LINK = re.compile(
    r"(!?)\[(?:[^\[\]\\]|\\.)*\]\(\s*(<[^>\n]*>|[^\s)]+)"
    r"(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?\s*\)"
)
# [label]: target "optional title", but not footnotes ([^1]: text) or "[Note]: prose".
_REF_DEFINITION = re.compile(
    r"^ {0,3}\[(?!\^)[^\]]+\]:[ \t]*(<[^>\n]*>|\S+)"
    r"(?:[ \t]+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?[ \t]*$"
)
_COMMENT_START = re.compile(r"^ {0,3}<!--")
_CODE_SPAN = re.compile(r"(`+)(?:(?!\1).)+?\1")
_SCHEME = re.compile(r"^(?:[A-Za-z][A-Za-z0-9+.-]*:|//)")
_WORD = re.compile(r"[^\W_]+")


# Line kinds yielded by iter_lines; anything but TEXT is not prose.
TEXT, FENCE, CODE, COMMENT = "", "fence", "code", "comment"


def iter_lines(lines: list[str], nested_fences: bool = False):
    """Yield ``(index, line, kind)`` where kind is TEXT, FENCE (a code fence line),
    CODE (inside a fence) or COMMENT (an HTML comment block, as CommonMark defines it).

    ``nested_fences`` also takes fences indented four or more spaces, as in nested
    list items, to be code.
    """
    fence_pattern = _NESTED_FENCE if nested_fences else _FENCE
    fence: tuple[str, int] | None = None
    in_comment = False
    for i, line in enumerate(lines):
        if in_comment:
            in_comment = "-->" not in line
            yield i, line, COMMENT
            continue
        match = fence_pattern.match(line)
        if fence is not None:
            closes = match and match.group(1)[0] == fence[0] and len(match.group(1)) >= fence[1]
            if closes and not match.group(2).strip():
                fence = None
                yield i, line, FENCE
            else:
                yield i, line, CODE
        elif match and not (match.group(1)[0] == "`" and "`" in match.group(2)):
            fence = (match.group(1)[0], len(match.group(1)))
            yield i, line, FENCE
        elif _COMMENT_START.match(line):
            in_comment = "-->" not in line[line.index("<!--") + 4 :]
            yield i, line, COMMENT
        else:
            yield i, line, TEXT


def plain_text(text: str, code_marks: bool = False) -> str:
    """Render inline markdown as plain text (keeps code-span contents verbatim, inside
    backticks if ``code_marks``)."""
    parts = re.split(r"(`+)(.+?)\1", text)
    out = []
    for i, part in enumerate(parts):
        if i % 3 == 2:
            out.append(f"`{part.strip()}`" if code_marks else part.strip())
        elif i % 3 == 0:
            out.append(_strip_inline(part))
    return " ".join("".join(out).split())


def _strip_inline(s: str) -> str:
    s = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"\[([^\]]*)\]\[[^\]]*\]", r"\1", s)
    s = re.sub(r"<[^>\n]+>", "", s)
    s = re.sub(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1", r"\2", s)
    s = re.sub(r"(?<![\w*])\*(?=\S)(.+?)(?<=\S)\*(?![\w*])", r"\1", s)
    s = re.sub(r"(?<!\w)_(?=\S)(.+?)(?<=\S)_(?!\w)", r"\1", s)
    s = re.sub(r"~~(.+?)~~", r"\1", s)
    return re.sub(r"\\([\\`*_{}\[\]()#+\-.!|>])", r"\1", s)


def slugify(text: str) -> str:
    """GitHub-style heading anchor, following github-slugger: lowercase; keep letters,
    combining marks, digits, connectors (``_``), dashes and spaces; spaces become ``-``.
    """
    return "".join(ch for ch in text.strip().lower() if _in_slug(ch)).replace(" ", "-")


def _in_slug(ch: str) -> bool:
    category = unicodedata.category(ch)
    return ch == " " or category[0] in "LM" or category in ("Nd", "Nl", "Pc", "Pd")


class Slugger:
    """Assigns unique anchors the way GitHub does (``setup``, ``setup-1``, ...)."""

    def __init__(self) -> None:
        self._seen: dict[str, int] = {}

    def slug(self, text: str) -> str:
        base = slugify(text) or "section"
        result = base
        while result in self._seen:
            self._seen[base] += 1
            result = f"{base}-{self._seen[base]}"
        self._seen[result] = 0
        return result


def word_count(text: str) -> int:
    return len(_WORD.findall(text))


@dataclass
class Heading:
    level: int
    text: str
    anchor: str
    line: int


@dataclass
class Section:
    """A heading and the text up to the next heading.

    ``end`` is where the section's own text stops; ``subtree_end`` also covers
    its subsections (what you get when reading the section). Level 0 is text
    before the first heading.
    """

    level: int
    heading: str
    anchor: str
    trail: list[str]
    start: int
    end: int
    subtree_end: int
    text: str


@dataclass
class Link:
    target: str  # path part, URL-decoded; "" for a same-document "#anchor"
    anchor: str
    line: int
    image: bool = False


@dataclass
class ParsedDoc:
    title: str
    summary: str
    body: str
    body_line: int  # file line (0-based) where the body starts, after front matter
    tags: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    sections: list[Section] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    words: int = 0
    has_title: bool = False
    has_summary: bool = False
    warnings: list[str] = field(default_factory=list)


def parse_headings(lines: list[str]) -> list[Heading]:
    slugger = Slugger()
    headings = []
    for i, line, kind in iter_lines(lines):
        if kind:
            continue
        match = _HEADING.match(line)
        if match:
            text = plain_text(_CLOSING_HASHES.sub("", match.group(2) or ""))
            headings.append(Heading(len(match.group(1)), text, slugger.slug(text), i))
    return headings


def split_sections(lines: list[str], headings: list[Heading], title: str) -> list[Section]:
    sections = []
    first = headings[0].line if headings else len(lines)
    preamble = "\n".join(lines[:first]).strip()
    if preamble:
        sections.append(Section(0, title, "", [], 0, first, first, preamble))
    stack: list[Heading] = []
    for n, heading in enumerate(headings):
        end = headings[n + 1].line if n + 1 < len(headings) else len(lines)
        subtree_end = next(
            (h.line for h in headings[n + 1 :] if h.level <= heading.level), len(lines)
        )
        while stack and stack[-1].level >= heading.level:
            stack.pop()
        stack.append(heading)
        text = "\n".join(lines[heading.line + 1 : end]).strip()
        sections.append(
            Section(
                heading.level,
                heading.text,
                heading.anchor,
                [h.text for h in stack],
                heading.line,
                end,
                subtree_end,
                text,
            )
        )
    return sections


def extract_links(lines: list[str]) -> list[Link]:
    """Relative links and images (external URLs are skipped)."""
    links = []

    def add(raw: str, line: int, image: bool) -> None:
        target = unquote(raw.strip("<>").strip())
        if not target or _SCHEME.match(target):
            return
        target, _, anchor = target.partition("#")
        target = target.partition("?")[0]
        if target or anchor:  # a bare "#" links to the top of the page
            links.append(Link(target, anchor, line, image))

    for i, line, kind in iter_lines(lines):
        if kind:
            continue
        line = _CODE_SPAN.sub(lambda m: " " * len(m.group(0)), line)
        for match in _INLINE_LINK.finditer(line):
            add(match.group(2), i, bool(match.group(1)))
        match = _REF_DEFINITION.match(line)
        if match:
            add(match.group(1), i, False)
    return links


def searchable_text(markdown: str) -> str:
    """Text for the full-text index: markup and link targets dropped, code kept."""
    out = []
    for _, line, kind in iter_lines(markdown.split("\n")):
        if kind == CODE:
            out.append(line)
            continue
        if kind or _REF_DEFINITION.match(line) or _RULE.match(line):
            continue
        if "|" in line and _TABLE_RULE.match(line):
            continue
        stripped = line.strip()
        if stripped.startswith("|"):  # table row: "| a | b |" becomes "a — b"
            stripped = " — ".join(cell.strip() for cell in stripped.strip("|").split("|"))
        stripped = _LIST_ITEM.sub("", re.sub(r"^(?:>\s?)+", "", stripped))
        out.append(plain_text(stripped))
    return "\n".join(out).strip()


def prose_blocks(lines: list[str]):
    """Yield ``(line, text, row)`` for each paragraph, list item and table row.

    ``line`` is the block's first line and ``text`` keeps its line breaks, minus list
    markers and blockquote marks. Table rows come one per block with ``row`` set and
    their cells joined by " — ". Code, comments, headings, rules, HTML blocks, link
    definitions and table separator rows are not prose and are skipped.
    """
    start, block = 0, []
    for i, line, kind in iter_lines(lines, nested_fences=True):
        text = re.sub(r"^(?:>\s?)+", "", line.strip())
        item = _LIST_ITEM.match(text)
        other = (
            kind
            or not text
            or _HEADING.match(text)
            or _RULE.match(text)
            or _REF_DEFINITION.match(text)
            or text.startswith(("<", "|"))
        )
        if block and (other or item):
            yield start, "\n".join(block), False
            block = []
        if text.startswith("|") and not kind:
            if not _TABLE_RULE.match(text):
                yield i, " — ".join(cell.strip() for cell in text.strip("|").split("|")), True
        elif not other:
            if not block:
                start = i
            block.append(text[item.end() :] if item else text)
    if block:
        yield start, "\n".join(block), False


def first_paragraph(lines: list[str]) -> str:
    """Plain text of the first prose paragraph (or first list item)."""
    para: list[str] = []
    for _, line, kind in iter_lines(lines):
        stripped = line.strip()
        skip = (
            kind
            or not stripped
            or _HEADING.match(line)
            or _RULE.match(line)
            or stripped.startswith(("|", "![", "<"))
        )
        if skip:
            if para:
                break
            continue
        if para and _LIST_ITEM.match(line):
            break
        para.append(_LIST_ITEM.sub("", re.sub(r"^(?:>\s?)+", "", stripped)))
    return plain_text(" ".join(para))


def shorten(text: str, limit: int = 220) -> str:
    """Trim to ``limit`` characters, preferring a sentence boundary."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    ends = [m.end() for m in re.finditer(r"[.!?](?=\s)", cut)]
    if ends and ends[-1] >= limit // 3:
        return cut[: ends[-1]]
    return cut.rsplit(" ", 1)[0].rstrip(",;:-") + "…"


def parse_document(text: str, fallback_title: str) -> ParsedDoc:
    """Parse a markdown file's text into metadata, sections and links."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    front, body, body_line, error = split_frontmatter(text)
    warnings = [error] if error else []
    data: dict = {}
    if front is not None:
        data, front_warnings = parse_frontmatter(front)
        warnings.extend(front_warnings)

    lines = body.split("\n")
    headings = parse_headings(lines)
    h1 = next((h for h in headings if h.level == 1), None)
    explicit_title = _as_text(data.pop("title", ""), "title", warnings)
    title = explicit_title or (h1.text if h1 else "") or fallback_title

    summary = _as_text(data.pop("summary", ""), "summary", warnings)
    description = _as_text(data.pop("description", ""), "description", warnings)
    explicit_summary = summary or description
    sections = split_sections(lines, headings, title)
    return ParsedDoc(
        title=title,
        summary=shorten(explicit_summary or first_paragraph(lines)),
        body=body,
        body_line=body_line,
        tags=_unique(t.lstrip("#").lower() for t in _as_list(data.pop("tags", []))),
        keywords=_unique(_as_list(data.pop("keywords", []))),
        related=_unique(_as_list(data.pop("related", []))),
        meta=data,
        sections=sections,
        links=extract_links(lines),
        words=word_count(body),
        has_title=bool(explicit_title or h1),
        has_summary=bool(explicit_summary),
        warnings=warnings,
    )


def _as_text(value: object, key: str, warnings: list[str]) -> str:
    if isinstance(value, list):
        warnings.append(f"front matter '{key}' should be text, not a list")
        return ", ".join(value)
    return " ".join(str(value).split()) if value else ""


def _as_list(value: object) -> list[str]:
    if isinstance(value, str):
        value = value.split(",")
    return [v.strip() for v in value if v.strip()]


def _unique(values) -> list[str]:
    seen: dict[str, None] = {}
    for value in values:
        if value:
            seen.setdefault(value, None)
    return list(seen)
