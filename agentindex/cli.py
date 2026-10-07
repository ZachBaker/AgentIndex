"""Command-line interface: ``agentindex <command>`` or ``python3 -m agentindex <command>``."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

from . import __version__, render
from .config import load_config
from .errors import AgentIndexError, NotFoundError
from .store import KnowledgeIndex

EPILOG = """examples:
  {prog} search "deploy rollback"       find docs about a topic
  {prog} read ops/deploying             print a whole doc
  {prog} read ops/deploying#rollback    print just one section
  {prog} read ops/deploying --outline   list a long doc's sections first
  {prog} list                           every doc with its summary
  {prog} check                          lint the knowledge base (for CI)

The index updates itself from the markdown sources before every command."""


def main(argv: list[str] | None = None, prog: str | None = None) -> int:
    prog = prog or _prog()
    parser = build_parser(prog)
    args = parser.parse_args(_protect_query(list(sys.argv[1:] if argv is None else argv)))
    if not getattr(args, "handler", None):
        parser.print_help()
        return 2
    _utf8_output()
    try:
        return args.handler(args, prog)
    except (AgentIndexError, OSError, sqlite3.Error) as exc:  # OSError: unwritable --db etc.
        return _fail(args, exc)
    except KeyboardInterrupt:
        return 130


def build_parser(prog: str) -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--root",
        default=argparse.SUPPRESS,
        help="project root (default: nearest dir with .agentindex.json, else the git root)",
    )
    common.add_argument(
        "--db", default=argparse.SUPPRESS, help="index database (default: .agentindex/index.db)"
    )
    parser = argparse.ArgumentParser(
        prog=prog,
        parents=[common],
        description="Search and read the project knowledge base.",
        epilog=EPILOG.format(prog=prog),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"agentindex {__version__}")
    sub = parser.add_subparsers(title="commands", metavar="<command>")

    def command(name: str, handler, help: str) -> argparse.ArgumentParser:  # noqa: A002
        p = sub.add_parser(name, parents=[common], help=help, description=help)
        p.set_defaults(handler=handler)
        return p

    p = command("search", cmd_search, "search docs by keywords")
    p.add_argument("query", nargs="+", help='keywords; "quoted phrase" required, -word excluded')
    p.add_argument("-n", "--limit", type=int, default=8, help="maximum results (default 8)")
    p.add_argument("-t", "--tag", action="append", default=[], help="only docs with this tag")
    p.add_argument("--json", action="store_true", help="print JSON")

    p = command("read", cmd_read, "print a doc, or one section of it")
    p.add_argument("ref", help="doc id (or path), optionally with #section-anchor")
    p.add_argument("-s", "--section", help="section anchor or heading text")
    p.add_argument("--outline", action="store_true", help="show headings and sizes only")
    p.add_argument("--json", action="store_true", help="print JSON")

    p = command("list", cmd_list, "list every doc with its summary")
    p.add_argument("-t", "--tag", action="append", default=[], help="only docs with this tag")
    p.add_argument("--json", action="store_true", help="print JSON")

    p = command("sync", cmd_sync, "update the index now (search and read do this themselves)")
    p.add_argument("--force", action="store_true", help="re-parse every file")
    p.add_argument("--json", action="store_true", help="print JSON")

    p = command("status", cmd_status, "show configuration and index statistics")
    p.add_argument("--json", action="store_true", help="print JSON")

    p = command("check", cmd_check, "lint docs: broken links, duplicate ids, missing metadata")
    p.add_argument("--strict", action="store_true", help="also fail on warnings")
    p.add_argument("--json", action="store_true", help="print JSON")

    p = command("serve", cmd_serve, "serve the HTTP JSON API")
    p.add_argument("--host", default="127.0.0.1", help="interface to bind (default 127.0.0.1)")
    p.add_argument("--port", type=int, default=8765, help="port (default 8765)")
    p.add_argument("--quiet", action="store_true", help="do not log requests")

    command("mcp", cmd_mcp, "run the MCP server on stdio (for Claude Code and other agents)")

    p = command("init", cmd_init, "set up a knowledge base in this repository")
    p.add_argument("--dir", dest="docs", help="knowledge directory (default: knowledge)")
    p.add_argument("--no-mcp", action="store_true", help="do not register the MCP server")

    p = command("import", cmd_import, "split a large markdown file (e.g. CLAUDE.md) into docs")
    p.add_argument("file", type=Path, nargs="?", help="markdown file to split")
    p.add_argument(
        "--guide", action="store_true", help="print the guide to preparing a file for import"
    )
    p.add_argument("--level", type=int, default=2, help="split at headings of this level (2 = ##)")
    p.add_argument("--into", type=Path, help="target directory (default: the first source)")
    p.add_argument("--force", action="store_true", help="overwrite existing docs")
    p.add_argument("--dry-run", action="store_true", help="show what would be created")
    return parser


_GLOBAL_VALUE_OPTIONS = ("--root", "--db")
_SEARCH_VALUE_OPTIONS = ("-n", "-t", "--limit", "--tag", *_GLOBAL_VALUE_OPTIONS)
_SEARCH_LONG_VALUE_OPTIONS = ("--limit", "--tag", *_GLOBAL_VALUE_OPTIONS)
_SEARCH_FLAGS = ("--json", "-h", "--help")


def _protect_query(argv: list[str]) -> list[str]:
    """Keep ``search deploy -staging`` from being read as options.

    argparse would reject ``-staging`` as an unknown option, read ``-tests`` as
    ``-t ests`` and ``-heroku`` as ``-h``. So after ``search``, only real search
    options go to argparse and every other word is passed as query text after ``--``.
    """
    i = 0
    while i < len(argv) and argv[i].startswith("-"):  # skip global options
        i += 2 if argv[i] in _GLOBAL_VALUE_OPTIONS else 1
    if i >= len(argv) or argv[i] != "search":
        return argv
    options, words = [], []
    rest = argv[i + 1 :]
    j = 0
    while j < len(rest):
        token = rest[j]
        if token == "--":
            words += rest[j + 1 :]
            break
        if token in _SEARCH_VALUE_OPTIONS and j + 1 < len(rest):
            options += rest[j : j + 2]
            j += 1
        elif token in _SEARCH_FLAGS or token.split("=", 1)[0] in _SEARCH_LONG_VALUE_OPTIONS:
            options.append(token)  # flags, and --limit=5, --tag=x, --root=x, --db=x
        else:
            words.append(token)
        j += 1
    return argv[: i + 1] + options + ["--"] + words


def _index(args: argparse.Namespace) -> KnowledgeIndex:
    return KnowledgeIndex(load_config(getattr(args, "root", None), getattr(args, "db", None)))


def cmd_search(args: argparse.Namespace, prog: str) -> int:
    with _index(args) as index:
        result = index.search(" ".join(args.query), limit=args.limit, tags=args.tag)
    hint = f"Read one: {prog} read <id>  (or <id>#<section> for just that section)"
    _emit(args, result, lambda r: render.render_search(r, hint))
    return 0


def cmd_read(args: argparse.Namespace, prog: str) -> int:
    with _index(args) as index:
        if args.outline:
            result = index.outline(args.ref)
            hint = f"Read one section: {prog} read {result['id']}#<anchor>"
            _emit(args, result, lambda r: render.render_outline(r, hint))
        else:
            _emit(args, index.read(args.ref, section=args.section), render.render_doc)
    return 0


def cmd_list(args: argparse.Namespace, prog: str) -> int:
    with _index(args) as index:
        result = index.list_docs(tags=args.tag)
    hint = f'Search: {prog} search "<keywords>"  ·  read: {prog} read <id>'
    _emit(args, result, lambda r: render.render_list(r, hint))
    return 0


def cmd_sync(args: argparse.Namespace, prog: str) -> int:
    with _index(args) as index:
        report = index.sync(force=args.force)
    _emit(args, report.to_dict(), render.render_sync)
    return 0


def cmd_status(args: argparse.Namespace, prog: str) -> int:
    with _index(args) as index:
        _emit(args, index.status(), render.render_status)
    return 0


def cmd_check(args: argparse.Namespace, prog: str) -> int:
    with _index(args) as index:
        result = index.check()
    _emit(args, result, render.render_check)
    failed = result["errors"] or (args.strict and result["warnings"])
    return 1 if failed else 0


def cmd_serve(args: argparse.Namespace, prog: str) -> int:
    from .http_api import serve

    serve(_config(args), host=args.host, port=args.port, quiet=args.quiet)
    return 0


def cmd_mcp(args: argparse.Namespace, prog: str) -> int:
    from .mcp_server import run

    return run(_config(args))


def cmd_init(args: argparse.Namespace, prog: str) -> int:
    from .scaffold import init

    root = getattr(args, "root", None) or load_config().root
    result = init(Path(root), docs=args.docs, mcp=not args.no_mcp)
    print(f"Set up AgentIndex in {result['root']}:")
    for action in result["actions"]:
        print(f"  - {action}")
    for note in result["notes"]:
        print(f"\nNote: {note}")
    if result["notes"]:
        print("\n" + result["claude_md"])
    cmd = result["command"]
    print(
        f"\nNext: write docs in {result['docs']}/, then try `{cmd} search <topic>`"
        f" and `{cmd} check`."
    )
    return 0


def cmd_import(args: argparse.Namespace, prog: str) -> int:
    from .frontmatter import split_frontmatter
    from .scaffold import TEMPLATES, import_markdown, invocation, render_template

    if args.guide:
        guide = (TEMPLATES / "migrating-claude-md.md").read_text(encoding="utf-8")
        print(split_frontmatter(guide)[1].strip("\n"))
        return 0
    if args.file is None:
        raise AgentIndexError("give the markdown file to import, or --guide")
    config = _config(args)
    command = invocation(config.root)
    into = args.into or config.root / config.sources[0]
    result = import_markdown(
        args.file, into, level=args.level, force=args.force, dry_run=args.dry_run
    )
    planned = result["docs"]
    if not planned:
        print(f"Nothing to import: {args.file} has no text.")
        return 0
    if result["fixes"]:
        print(f"Converted {len(result['fixes'])} headings the index would not recognize:")
        for fix in result["fixes"]:
            print(f"  line {fix['line']}: {fix['before']}  ->  {fix['after']}")
        print()
    width = max(len(_relative(p["path"], config.root)) for p in planned)
    print(f"{'Planned' if args.dry_run else 'Imported'} {len(planned)} docs from {args.file}:")
    for p in planned:
        print(
            f"  {_relative(p['path'], config.root).ljust(width)}  {p['title']}"
            f" ({p['words']} words, {p['status']})"
        )
    docs = _relative(into, config.root)
    if not any(docs == s or docs.startswith(s.rstrip("/") + "/") for s in config.sources):
        print(f"\nNote: {docs}/ is not in the index sources ({', '.join(config.sources)}).")
    if result["warnings"]:
        print()
        for warning in result["warnings"]:
            print(f"Warning: {warning}")
        print(
            f"Restructure {args.file.name} and import again; `{command} import --guide`"
            " explains how."
        )
    if args.dry_run:
        return 0
    print(
        "\nNext steps:\n"
        "  1. Review the new docs: sharpen each summary, add tags and keywords, and split or\n"
        "     merge docs so each covers one topic.\n"
        f"  2. Keep in {args.file.name} only rules that every task must follow; agents will\n"
        "     not search for rules they do not know about.\n"
        f"  3. Replace the rest of {args.file.name} with this pointer:\n"
    )
    print(render_template("CLAUDE.md", command, docs))
    print(f"  4. Run `{command} check` and fix what it reports.")
    print(f"\nThe full checklist: `{command} import --guide`.")
    return 0


def _config(args: argparse.Namespace):
    return load_config(getattr(args, "root", None), getattr(args, "db", None))


def _emit(args: argparse.Namespace, result: dict, render_text) -> None:
    if getattr(args, "json", False):
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    else:
        print(render_text(result))


def _fail(args: argparse.Namespace, exc: Exception) -> int:
    suggestions = exc.suggestions if isinstance(exc, NotFoundError) else []
    if getattr(args, "json", False):
        print(json.dumps({"error": str(exc), "suggestions": suggestions}, indent=2))
    else:
        print(f"error: {exc}", file=sys.stderr)
        if suggestions:
            print("did you mean: " + ", ".join(suggestions), file=sys.stderr)
    return 1 if isinstance(exc, NotFoundError) else 2


def _relative(path: Path, root: Path) -> str:
    try:
        return Path(path).resolve().relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _prog() -> str:
    """How this process was started, so hints show a command that works."""
    name = os.path.basename(sys.argv[0]) if sys.argv and sys.argv[0] else ""
    return "python3 -m agentindex" if name in ("__main__.py", "-c", "") else "agentindex"


def _utf8_output() -> None:
    # Docs are UTF-8: write UTF-8 even where the console default is narrower (Windows
    # pipes), and never crash on a character that cannot be encoded.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
