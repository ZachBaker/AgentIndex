"""Set up a repository (``init``) and migrate a large CLAUDE.md into docs (``import``)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .config import CONFIG_FILE, load_config
from .errors import AgentIndexError
from .frontmatter import split_frontmatter
from .markdown import first_paragraph, iter_lines, parse_headings, shorten, word_count

TEMPLATES = Path(__file__).with_name("templates")
_HEADING_HASHES = re.compile(r"^( {0,3})(#{1,6})(?=[ \t]|$)")
# The opening line Claude Code's /init writes into every CLAUDE.md; not knowledge.
_BOILERPLATE = re.compile(r"^\s*This file provides guidance to Claude Code\b", re.IGNORECASE)


def invocation(root: Path) -> str:
    """How agents in ``root`` should run AgentIndex."""
    if (root / "agentindex" / "__init__.py").is_file():  # a vendored copy (or this repo)
        return "python3 -m agentindex"
    return "agentindex"


def mcp_entry(command: str) -> dict:
    executable, *args = command.split()
    return {"command": executable, "args": [*args, "mcp"]}


def render_template(name: str, command: str, docs: str) -> str:
    text = (TEMPLATES / name).read_text(encoding="utf-8")
    return text.replace("{cmd}", command).replace("{docs}", docs)


def init(root: Path, docs: str | None = None, mcp: bool = True) -> dict:
    """Create the config, starter docs, .gitignore entry, MCP registration and CLAUDE.md.

    Existing files are never overwritten; the result says what was kept.
    """
    root = root.resolve()
    command = invocation(root)
    actions: list[str] = []
    notes: list[str] = []

    config_path = root / CONFIG_FILE
    if config_path.exists():
        sources = load_config(root).sources
        if docs is None:
            docs = sources[0]
        elif docs not in sources:
            notes.append(f"{CONFIG_FILE} does not index {docs}/; add it to 'sources'.")
        actions.append(f"kept {CONFIG_FILE}")
    else:
        docs = docs or "knowledge"
        _write_json(config_path, {"sources": [docs]})
        actions.append(f"created {CONFIG_FILE} (indexes {docs}/)")

    docs_dir = root / docs
    docs_dir.mkdir(parents=True, exist_ok=True)
    for name in ("start-here.md", "writing-docs.md"):
        target = docs_dir / name
        if target.exists():
            actions.append(f"kept {docs}/{name}")
        else:
            target.write_text(render_template(name, command, docs), encoding="utf-8")
            actions.append(f"created {docs}/{name}")

    gitignore = root / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    if not {".agentindex", ".agentindex/", "/.agentindex/"} & {
        line.strip() for line in existing.splitlines()
    }:
        prefix = "" if not existing or existing.endswith("\n") else "\n"
        with gitignore.open("a", encoding="utf-8") as fh:
            fh.write(f"{prefix}# AgentIndex search index (rebuilt automatically)\n.agentindex/\n")
        actions.append("added .agentindex/ to .gitignore")

    if mcp:
        mcp_path = root / ".mcp.json"
        try:
            text = mcp_path.read_text(encoding="utf-8-sig") if mcp_path.exists() else "{}"
            data = json.loads(text)
        except ValueError as exc:
            raise AgentIndexError(
                f"{mcp_path} is not valid JSON ({exc}); fix it and retry"
            ) from None
        if not isinstance(data, dict) or not isinstance(data.get("mcpServers", {}), dict):
            raise AgentIndexError(f"{mcp_path} has an unexpected shape; expected mcpServers: {{}}")
        servers = data.setdefault("mcpServers", {})
        if "agentindex" in servers:
            actions.append("kept the agentindex server in .mcp.json")
        else:
            servers["agentindex"] = mcp_entry(command)
            _write_json(mcp_path, data)
            actions.append("registered the agentindex MCP server in .mcp.json")

    claude_md = root / "CLAUDE.md"
    pointer = render_template("CLAUDE.md", command, docs)
    if not claude_md.exists():
        claude_md.write_text(pointer, encoding="utf-8")
        actions.append("created CLAUDE.md pointing agents at the index")
    elif "agentindex" in claude_md.read_text(encoding="utf-8", errors="replace").lower():
        actions.append("kept CLAUDE.md (it already mentions agentindex)")
    else:
        notes.append(
            f"CLAUDE.md already exists. Move its knowledge into {docs}/ with"
            f" `{command} import CLAUDE.md`, then replace it with the pointer below,"
            " keeping only rules that every task must follow."
        )
    return {
        "root": str(root),
        "command": command,
        "docs": docs,
        "actions": actions,
        "notes": notes,
        "claude_md": pointer,
    }


def import_markdown(
    source: Path, into: Path, level: int = 2, force: bool = False, dry_run: bool = False
) -> list[dict]:
    """Split ``source`` at headings of ``level`` (and above) into one doc per section.

    Each new doc gets a title and summary in front matter, and its headings are
    shifted so the section heading becomes the doc's ``# Title``. Text before
    the first split becomes ``overview.md``. Existing files are skipped unless
    ``force`` is set.
    """
    if not source.is_file():
        raise AgentIndexError(f"{source} is not a file")
    if not 1 <= level <= 6:
        raise AgentIndexError("the split level must be between 1 and 6")
    text = source.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    _, body, _, _ = split_frontmatter(text)
    lines = body.split("\n")
    headings = parse_headings(lines)
    doc_title = headings[0] if headings and headings[0].level == 1 and level > 1 else None
    breaks = [h for h in headings if h.level <= level and h is not doc_title]

    chunks: list[tuple[str, list[str]]] = []
    first = breaks[0].line if breaks else len(lines)
    intro = [
        line
        for i, line in enumerate(lines[:first])
        if (not doc_title or i != doc_title.line) and not _BOILERPLATE.match(line)
    ]
    if word_count("\n".join(intro)):
        chunks.append(("Overview", ["# Overview", "", *intro]))
    for n, heading in enumerate(breaks):
        end = breaks[n + 1].line if n + 1 < len(breaks) else len(lines)
        if word_count("\n".join(lines[heading.line + 1 : end])):
            chunks.append(
                (heading.text, _shift_headings(lines[heading.line : end], heading.level - 1))
            )

    planned: list[dict] = []
    used: set[str] = set()
    for title, content in chunks:
        name = _filename(title, used)
        target = into / name
        if target.exists() and not force:
            status = "exists, skipped"
        elif dry_run:
            status = "would overwrite" if target.exists() else "would create"
        else:
            status = "overwrote" if target.exists() else "created"
            into.mkdir(parents=True, exist_ok=True)
            target.write_text(_doc_text(title, content), encoding="utf-8")
        planned.append(
            {
                "path": target,
                "title": title,
                "words": word_count("\n".join(content)),
                "status": status,
            }
        )
    return planned


def _shift_headings(lines: list[str], shift: int) -> list[str]:
    if shift <= 0:
        return list(lines)
    out = []
    for _, line, kind in iter_lines(lines):
        match = None if kind else _HEADING_HASHES.match(line)
        if match:
            level = max(1, len(match.group(2)) - shift)
            line = match.group(1) + "#" * level + line[match.end() :]
        out.append(line)
    return out


def _doc_text(title: str, content: list[str]) -> str:
    front = ["---", f"title: {_yaml_text(title)}"]
    summary = shorten(first_paragraph(content), 200)
    if summary:
        front.append(f"summary: {_yaml_text(summary)}")
    front.append("---")
    return "\n".join(front) + "\n\n" + "\n".join(content).strip("\n") + "\n"


def _yaml_text(value: str) -> str:
    if re.search(r"[:#\[\]{},&*!|>'\"%@`]", value) or value != value.strip():
        return json.dumps(value, ensure_ascii=False)
    return value


def _filename(title: str, used: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60].rstrip("-") or "section"
    name, n = base, 1
    while name in used:
        n += 1
        name = f"{base}-{n}"
    used.add(name)
    return name + ".md"


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
