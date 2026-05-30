"""swcb — unified CLI for the SW Contracting Bots toolkit.

A thin dispatcher in front of the existing scripts so the operator has a
single entry point. Each subcommand simply forwards to the implementation
module's CLI, which keeps the per-module CLIs usable standalone too.

Examples:

    python scripts/swcb.py sync
    python scripts/swcb.py search "Elasticsearch" --days 14
    python scripts/swcb.py score --profile elastic_only --min-score 4
    python scripts/swcb.py digest --days 3
    python scripts/swcb.py dashboard
    python scripts/swcb.py watch list
    python scripts/swcb.py watch add NOTICE-ID --title "..."

Run `python scripts/swcb.py <command> --help` for per-command flags.
"""

from __future__ import annotations

import argparse
import runpy
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

COMMANDS = {
    "sync":         ("sync_bulk.py",      "Refresh the local SAM.gov SQLite mirror"),
    "search":       ("search_bulk.py",    "Search the local SAM mirror"),
    "live":         ("find_contracts.py", "Live SAM.gov API lookup"),
    "score":        ("scoring.py",        "Score candidates against the technical-services rubric"),
    "digest":       ("digest.py",         "Generate a daily digest report"),
    "watch":        ("watchlist.py",      "Manage the opportunity watchlist + saved searches"),
    "tasks":        ("tasks_lib.py",      "Manage the business-task spine (tasks/ directory)"),
    "incumbents":   ("usaspending.py",    "USAspending — incumbent / award-history analysis"),
    "ecfr":         ("ecfr.py",           "eCFR — FAR/CFR clause grounding and search"),
    "harness":      ("harness.py",        "Run the labeled-gold-set scoring harness"),
    "dashboard":    ("dashboard.py",      "Launch the local web dashboard"),
    "docs":         ("document_store.py", "Document index status / ingest / search"),
}


def _print_help() -> None:
    print("swcb — SW Contracting Bots CLI\n")
    print("Usage: python scripts/swcb.py <command> [args]\n")
    print("Commands:")
    width = max(len(name) for name in COMMANDS)
    for name, (_, help_text) in COMMANDS.items():
        print(f"  {name:<{width}}  {help_text}")
    print("\nRun `python scripts/swcb.py <command> --help` for command-specific flags.")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in {"-h", "--help", "help"}:
        _print_help()
        return 0

    command, rest = argv[0], argv[1:]
    if command not in COMMANDS:
        print(f"Unknown command: {command!r}\n", file=sys.stderr)
        _print_help()
        return 2

    script_name, _ = COMMANDS[command]
    target = SCRIPT_DIR / script_name
    if not target.exists():
        print(f"Implementation script missing: {target}", file=sys.stderr)
        return 1

    # Replace argv so the target script's argparse sees its own name + args.
    sys.argv = [str(target), *rest]
    runpy.run_path(str(target), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
