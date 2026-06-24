"""CLI for the independent opportunity-evaluation panel."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from panel.service import PanelError, PanelService
from panel.store import PanelStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run and inspect the independent Phase-1 opportunity-evaluation panel."
    )
    parser.add_argument(
        "--db",
        default=str(Path(__file__).resolve().parent.parent / "data" / "contracts.db"),
        help="SQLite mirror path (default: data/contracts.db)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="Create additive panel tables if absent.")
    init.add_argument("--json", action="store_true")

    run = subparsers.add_parser("run", help="Evaluate one notice with the full Phase-1 panel.")
    run.add_argument("notice_id", help="SAM notice ID or solicitation-number fallback.")
    run.add_argument("--json", action="store_true")

    show = subparsers.add_parser("show", help="Show the latest stored panel verdict.")
    show.add_argument("notice_id", help="SAM notice ID or solicitation-number fallback.")
    show.add_argument("--json", action="store_true")
    show.add_argument("--raw", action="store_true", help="Include raw expert JSON outputs.")
    return parser


def _display(result: dict[str, Any], json_output: bool) -> None:
    if json_output:
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return
    print(f"Run: {result['run_id']}")
    print(f"Notice: {result['notice_id']}")
    print(f"Final verdict: {result['final_verdict']}")
    print(f"Consensus score: {result['consensus_score']}")
    for verdict in result.get("verdicts", []):
        print(
            f"  {verdict['expert']:<12} {verdict['verdict']:<15} "
            f"score={verdict['score']:>3} confidence={verdict['confidence']:.2f}"
        )


def main() -> int:
    args = build_parser().parse_args()
    store = PanelStore(args.db)
    try:
        if args.command == "init":
            store.ensure_schema()
            result = {"ok": True, "database": str(store.db_path), "tables": ["panel_runs", "panel_verdicts"]}
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                print(f"Panel tables ready in {store.db_path}")
            return 0
        if args.command == "run":
            result = asyncio.run(PanelService(store=store).evaluate(args.notice_id))
            _display(result, args.json)
            return 0
        result = store.latest_for_notice(args.notice_id)
        if result is None:
            raise PanelError(f"No stored panel verdict found for {args.notice_id!r}")
        _display(result.to_dict(include_raw=args.raw), args.json)
        return 0
    except PanelError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
