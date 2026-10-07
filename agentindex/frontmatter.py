"""Front matter: the small YAML subset that knowledge docs actually use.

Supported, which covers typical doc metadata without a YAML dependency:

    ---
    title: Plain or "quoted" scalar     # comments are ignored
    tags: [inline, list]
    keywords:
      - block
      - list
    summary: >
      Folded block scalars (and `|` literal blocks), or plain
      scalars continued on indented lines.
    ---

Nested mappings, anchors and other YAML features are reported as warnings
instead of failing the whole document.
"""

from __future__ import annotations

import re

_KEY = re.compile(r"^([A-Za-z_][\w-]*)[ \t]*:(?:[ \t]+(.*))?$")
_ITEM = re.compile(r"^[ \t]*-(?:[ \t]+(.*))?$")
_BLOCK_SCALAR = re.compile(r"^([|>])[+-]?$")


def split_frontmatter(text: str) -> tuple[str | None, str, int, str | None]:
    """Split ``text`` into ``(front matter, body, body line offset, error)``.

    The front matter must open on the first line with ``---`` and close with
    ``---`` (or ``...``). An unclosed block is treated as body text.
    """
    lines = text.split("\n")
    if not lines or lines[0].rstrip() != "---":
        return None, text, 0, None
    for i in range(1, len(lines)):
        if lines[i].rstrip() in ("---", "..."):
            return "\n".join(lines[1:i]), "\n".join(lines[i + 1 :]), i + 1, None
    return None, text, 0, "front matter opened with '---' on line 1 but never closed"


def parse_frontmatter(block: str) -> tuple[dict, list[str]]:
    """Parse a front matter block into ``{key: str | list[str]}`` plus warnings."""
    data: dict = {}
    warnings: list[str] = []
    lines = block.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        match = _KEY.match(line)
        if not match:
            warnings.append(f"front matter line {i + 2} not understood: {stripped[:60]}")
            i += 1
            continue
        key, raw = match.group(1).lower(), _strip_comment(match.group(2) or "")
        i += 1
        nested: list[str] = []
        while i < len(lines) and (
            not lines[i].strip() or lines[i][0] in " \t" or _ITEM.match(lines[i])
        ):
            nested.append(lines[i])
            i += 1
        while nested and not nested[-1].strip():
            nested.pop()
        if key in data:
            warnings.append(f"front matter key '{key}' appears more than once; using the last one")
        data[key] = _value(key, raw, nested, warnings)
    return data, warnings


def _value(key: str, raw: str, nested: list[str], warnings: list[str]) -> str | list[str]:
    block = _BLOCK_SCALAR.match(raw)
    if block:
        text = _dedent(nested)
        if block.group(1) == "|":
            return "\n".join(text).strip()
        paragraphs = "\n".join(text).split("\n\n")
        return "\n".join(" ".join(p.split()) for p in paragraphs).strip()
    if raw.startswith("["):
        joined = " ".join([raw] + [_strip_comment(n.strip()) for n in nested])
        if not joined.rstrip().endswith("]"):
            warnings.append(f"front matter key '{key}': unterminated [list]")
        return _inline_list(joined.strip().lstrip("[").rstrip("]"))
    items = [_ITEM.match(n) for n in nested]
    if not raw and nested and all(items):
        return [_scalar(_strip_comment(m.group(1) or "")) for m in items if m.group(1)]
    if not raw and nested:
        if any(_KEY.match(n.strip()) for n in nested):
            warnings.append(f"front matter key '{key}': nested mappings are not supported")
        return " ".join(n.strip() for n in nested)
    if nested:
        # A plain scalar continued on indented lines folds into one line.
        return " ".join([_scalar(raw)] + [_strip_comment(n.strip()) for n in nested if n.strip()])
    return _scalar(raw)


def _scalar(raw: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] == '"':
        return re.sub(r'\\(["\\/])', r"\1", raw[1:-1]).replace("\\n", "\n").replace("\\t", "\t")
    if len(raw) >= 2 and raw[0] == raw[-1] == "'":
        return raw[1:-1].replace("''", "'")
    return raw


def _inline_list(inner: str) -> list[str]:
    items, start = [], 0
    for i in _unquoted_positions(inner):
        if inner[i] == ",":
            items.append(inner[start:i])
            start = i + 1
    items.append(inner[start:])
    return [v for v in (_scalar(item) for item in items) if v]


def _strip_comment(raw: str) -> str:
    """Drop a trailing ``# comment`` that is outside quotes."""
    for i in _unquoted_positions(raw):
        if raw[i] == "#" and (i == 0 or raw[i - 1] in " \t"):
            return raw[:i].rstrip()
    return raw.strip()


def _unquoted_positions(text: str):
    """Yield the indexes of characters outside YAML quoted strings.

    Handles ``''`` inside single quotes and backslash escapes inside double quotes.
    A quote only opens a string at the start of a value or list item.
    """
    quote = None
    i = 0
    while i < len(text):
        ch = text[i]
        if quote is None:
            if ch in "\"'" and (i == 0 or text[i - 1] in " \t[,"):
                quote = ch
            else:
                yield i
        elif quote == '"' and ch == "\\":
            i += 1  # skip the escaped character
        elif quote == "'" and ch == "'" and text[i + 1 : i + 2] == "'":
            i += 1  # '' is an escaped single quote
        elif ch == quote:
            quote = None
        i += 1


def _dedent(lines: list[str]) -> list[str]:
    indents = [len(n) - len(n.lstrip()) for n in lines if n.strip()]
    cut = min(indents) if indents else 0
    return [n[cut:] if n.strip() else "" for n in lines]
