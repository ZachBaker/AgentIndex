"""Command line for the benchmark: ``python3 -m bench <fetch|check|run> [corpus ...]``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .corpora import BENCH_DIR, fetch, is_fetched, load_corpora
from .evaluate import SPLITS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m bench", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("fetch", "download the pinned corpora into bench/.cache/"),
        ("check", "check every case's answers exist in its corpus"),
        ("pool", "print, as JSON, top results of any system that no one has judged yet"),
        ("run", "run the benchmark and write the report"),
    ):
        p = sub.add_parser(name, help=help_text, description=help_text)
        p.add_argument("corpora", nargs="*", help="corpus names (default: all)")
        if name == "run":
            p.add_argument(
                "--out",
                type=Path,
                help="directory for results.md and results.json (default: bench/, or none"
                " with --split)",
            )
            p.add_argument(
                "--split",
                choices=SPLITS,
                help="only the cases in this half: choose ranking changes on dev, confirm on"
                " test (prints the summary; writes files only with --out)",
            )
    args = parser.parse_args(argv)
    corpora = load_corpora(args.corpora)

    for corpus in corpora:
        if args.command == "fetch" or not is_fetched(corpus):
            fetch(corpus, log=lambda message: print(message, file=sys.stderr))
    if args.command == "fetch":
        return 0

    from .evaluate import check_cases, pool_candidates, run_benchmark
    from .report import render_report, write_results

    if args.command == "pool":
        print(json.dumps(pool_candidates(corpora), indent=1, ensure_ascii=False))
        return 0
    if args.command == "check":
        problems = check_cases(corpora)
        for problem in problems:
            print(problem)
        print(f"{len(problems)} problems" if problems else "All cases check out.")
        return 1 if problems else 0

    results = run_benchmark(
        corpora, log=lambda message: print(message, file=sys.stderr), split=args.split
    )
    print(render_report(results, summary_only=True))
    out = args.out or (None if args.split else BENCH_DIR)
    if out:
        paths = write_results(results, out)
        print("\nWrote " + " and ".join(str(p) for p in paths))
    return 0


if __name__ == "__main__":
    sys.exit(main())
