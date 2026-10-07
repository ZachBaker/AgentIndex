"""Plain-text rendering shared by the CLI and the MCP server.

This text is what agents actually read, so it is compact, stable, and always
ends by saying what to do next.
"""

from __future__ import annotations


def render_search(result: dict, hint: str) -> str:
    query, results = result["query"], result["results"]
    if not results:
        if result["indexed"] == 0:
            return (
                f'No results for "{query}": the knowledge base is empty. Check that its'
                " directory exists (status) or create one (init)."
            )
        return (
            f'No docs match "{query}" ({result["indexed"]} docs indexed). Try other keywords or'
            " synonyms, fewer words, or browse all docs with list."
        )
    header = f'{result["total"]} docs match "{query}"'
    if result["total"] > len(results):
        header += f", showing the top {len(results)}"
    lines = [header + ":", ""]
    for n, doc in enumerate(results, 1):
        lines.append(f"{n}. {doc['id']} — {doc['title']}{_tags(doc['tags'])}")
        if doc["summary"]:
            lines.append(f"   {doc['summary']}")
        for section in doc["sections"]:
            ref = f"{doc['id']}#{section['anchor']}" if section["anchor"] else doc["id"]
            lines.append(f"   § {section['heading']} ({ref})")
            if section["snippet"]:
                lines.append(f"     {section['snippet']}")
        lines.append("")
    lines.append(hint)
    return "\n".join(lines)


def render_doc(doc: dict) -> str:
    section = doc["section"]
    header = [f"id: {doc['id']}#{section['anchor']}" if section else f"id: {doc['id']}"]
    header.append(f"file: {doc['path']}:{doc['line']}" if section else f"file: {doc['path']}")
    if doc["tags"]:
        header.append("tags: " + ", ".join(doc["tags"]))
    lines = [" | ".join(header), ""]
    if not section and not doc["content"].startswith("# "):
        lines += [f"# {doc['title']}", ""]
    lines.append(doc["content"])

    footer = []
    if section:
        others = [e["anchor"] for e in doc["outline"] if e["anchor"] != section["anchor"]]
        if others:
            more = " …" if len(others) > 15 else ""
            footer.append("Other sections: " + ", ".join("#" + a for a in others[:15]) + more)
    if doc["links"]:
        footer.append("Links to: " + "; ".join(_doc_ref(d) for d in doc["links"]))
    if doc["backlinks"]:
        footer.append("Linked from: " + "; ".join(_doc_ref(d) for d in doc["backlinks"]))
    if footer:
        lines += ["", "---", *footer]
    return "\n".join(lines)


def render_outline(doc: dict, hint: str) -> str:
    lines = [f"id: {doc['id']} | file: {doc['path']} | {doc['words']} words", ""]
    if not doc["outline"]:
        lines.append("(no headings)")
    for entry in doc["outline"]:
        indent = "  " * (entry["level"] - 1)
        lines.append(
            f"{indent}{'#' * entry['level']} {entry['heading']}"
            f"  #{entry['anchor']}  ({entry['words']} words)"
        )
    lines += ["", hint]
    return "\n".join(lines)


def render_list(result: dict, hint: str) -> str:
    docs = result["documents"]
    if not docs:
        return "No docs. Check that the knowledge directory exists (status) or create one (init)."
    width = min(max(len(d["id"]) for d in docs), 36)
    lines = [f"{result['total']} docs:", ""]
    for doc in docs:
        summary = f" — {doc['summary']}" if doc["summary"] else ""
        lines.append(f"{doc['id'].ljust(width)}  {doc['title']}{summary}")
    if result["tags"]:
        tags = ", ".join(f"{t['tag']} ({t['count']})" for t in result["tags"])
        lines += ["", f"Tags: {tags}"]
    lines += ["", hint]
    return "\n".join(lines)


def render_status(status: dict) -> str:
    sources = ", ".join(
        s["path"] + ("" if s["exists"] else " (missing!)") for s in status["sources"]
    )
    rows = [
        ("root", status["root"]),
        ("config", status["config_file"] or "(none: using defaults)"),
        ("sources", sources),
        ("exclude", ", ".join(status["exclude"]) or "(none)"),
        ("database", status["database"]),
        ("documents", status["documents"]),
        ("sections", status["sections"]),
        ("links", status["links"]),
        ("tags", ", ".join(t["tag"] for t in status["tags"]) or "(none)"),
        ("last sync", status["last_sync"]),
        (
            "version",
            f"agentindex {status['version']}, schema {status['schema_version']},"
            f" SQLite {status['sqlite_version']}",
        ),
    ]
    return "\n".join(f"{name + ':':<11}{value}" for name, value in rows)


def render_check(result: dict) -> str:
    lines = []
    for issue in result["issues"]:
        where = issue["path"] + (f":{issue['line']}" if issue["line"] else "")
        lines.append(f"{where}: {issue['severity']}: {issue['message']}")
    if lines:
        lines.append("")
    lines.append(
        f"{result['documents']} docs checked: {_plural(result['errors'], 'error')},"
        f" {_plural(result['warnings'], 'warning')}."
    )
    return "\n".join(lines)


def render_sync(report: dict) -> str:
    total = len(report["added"]) + len(report["updated"]) + report["unchanged"]
    lines = [
        f"Indexed {_plural(total, 'doc')}: {len(report['added'])} added,"
        f" {len(report['updated'])} updated, {len(report['removed'])} removed,"
        f" {report['unchanged']} unchanged ({report['seconds']:.2f}s)."
    ]
    lines += [f"warning: source {s} does not exist" for s in report["missing_sources"]]
    lines += [
        f"warning: skipped {skipped}: doc id {doc_id!r} is already used by {kept}"
        for doc_id, kept, skipped in report["duplicates"]
    ]
    lines += [f"warning: could not read {path}: {msg}" for path, msg in report["errors"]]
    return "\n".join(lines)


def _tags(tags: list[str]) -> str:
    return f"  [{', '.join(tags)}]" if tags else ""


def _doc_ref(doc: dict) -> str:
    return f"{doc['id']} ({doc['title']})"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")
