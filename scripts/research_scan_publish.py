"""Publish final chat-research scan results into the Workbench.

This is the local fallback for Codex/Claude chats when the
`publish_research_scan` MCP tool is unavailable. It writes to the same
`digest_runs` table used by the Workbench scan history.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from scoring import available_profiles, score_opportunity
from watchlist import Store, db_path_for_env

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONTRACTS_DB = PROJECT_ROOT / "data" / "contracts.db"
LOCAL_TIMEZONE = ZoneInfo("America/New_York")


def _load_payload(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    if path == "-":
        text = sys.stdin.read()
    else:
        text = Path(path).read_text(encoding="utf-8")
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("scan payload must be a JSON object")
    return payload


def _mirror_opportunity(notice_id: str) -> dict[str, Any]:
    if not CONTRACTS_DB.exists():
        return {}
    with sqlite3.connect(CONTRACTS_DB) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT notice_id, title, sol_number, department, sub_tier, posted_date,
                   type, set_aside, set_aside_code, response_deadline, naics_code,
                   pop_city, pop_state, active, link, description
              FROM opportunities
             WHERE notice_id = ?
            """,
            (notice_id,),
        ).fetchone()
    return dict(row) if row else {}


def _deadline_status(value: str | None) -> tuple[bool | None, str]:
    local_now = datetime.now(LOCAL_TIMEZONE)
    if not value:
        return None, "response deadline not provided"
    candidate = value.strip().replace("Z", "+00:00")
    try:
        deadline = datetime.fromisoformat(candidate)
    except ValueError:
        try:
            deadline_date = date.fromisoformat(candidate[:10])
        except ValueError:
            return None, f"unparseable response deadline: {value}"
        is_open = deadline_date >= local_now.date()
        return is_open, "open by date" if is_open else "response deadline passed"
    if deadline.tzinfo is None:
        is_open = deadline.date() >= local_now.date()
    else:
        is_open = deadline.astimezone(LOCAL_TIMEZONE) >= local_now
    return is_open, "open" if is_open else "response deadline passed"


def _note_text(value: Any) -> str:
    if isinstance(value, list):
        return "; ".join(str(item) for item in value if str(item).strip())
    return str(value or "").strip()


def _research_delivery_read(item: dict[str, Any]) -> dict[str, str] | None:
    disposition = str(item.get("disposition") or "").strip().lower()
    if not disposition:
        return None
    detail = (
        _note_text(item.get("blockers"))
        or _note_text(item.get("concern"))
        or _note_text(item.get("supported_fit"))
        or "See the AI research notes."
    )
    if disposition == "assess now":
        return {"label": "Assess now", "detail": detail, "level": "solo"}
    if disposition == "monitor/partner":
        return {"label": "Monitor / partner", "detail": detail, "level": "team"}
    if disposition == "reject":
        return {"label": "Reject", "detail": detail, "level": "monitor"}
    return {"label": disposition, "detail": detail, "level": "monitor"}


def normalize_research_item(item: dict[str, Any], profile: str) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("each research-scan item must be an object")
    notice_id = str(item.get("notice_id") or "").strip()
    if not notice_id:
        raise ValueError("each research-scan item must include notice_id")

    mirror = _mirror_opportunity(notice_id)
    scored: dict[str, Any] = {}
    if mirror:
        scored = score_opportunity(mirror, profile=profile).to_dict()

    normalized = {**mirror, **scored, **item, "notice_id": notice_id}
    title = str(normalized.get("title") or "").strip()
    if not title:
        raise ValueError(
            f"research-scan item {notice_id!r} needs a title because it is not in the local mirror"
        )
    normalized["title"] = title
    normalized.setdefault("band", "monitor")
    normalized.setdefault("lanes", [])
    deadline_open, deadline_note = _deadline_status(normalized.get("response_deadline"))
    normalized["deadline_open"] = deadline_open
    normalized["deadline_note"] = deadline_note
    delivery_read = _research_delivery_read(normalized)
    if delivery_read:
        normalized["delivery_read"] = delivery_read
    return normalized


def publish_scan(
    *,
    summary: str,
    items: list[dict[str, Any]],
    candidates_scanned: int = 0,
    profile: str = "technical_services",
    db_path: str | Path | None = None,
    env: str | None = None,
) -> dict[str, Any]:
    if profile not in available_profiles():
        raise ValueError(f"Unknown profile {profile!r}. Valid: {available_profiles()}")
    if not summary.strip():
        raise ValueError("summary must be non-empty")

    normalized_items = [normalize_research_item(item, profile) for item in items]
    store = Store(db_path=db_path, env=env)
    run_id = store.publish_research_scan(
        summary=summary,
        items=normalized_items,
        profile=profile,
        candidates_scanned=max(0, candidates_scanned),
    )
    return {
        "ok": True,
        "scan_id": run_id,
        "source": "ai_research",
        "profile": profile,
        "candidates_scanned": max(candidates_scanned, len(normalized_items)),
        "candidates_shown": len(normalized_items),
        "summary": summary,
        "items": normalized_items,
        "watchlist_db": str(Path(db_path) if db_path else db_path_for_env(env)),
    }


def _parse_item(raw: str) -> dict[str, Any]:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("--item must be a JSON object")
    return value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Publish final chat-research scan results into the Workbench."
    )
    parser.add_argument(
        "-i",
        "--input",
        help="JSON payload file, or '-' for stdin. Expected keys: summary, items, candidates_scanned, profile.",
    )
    parser.add_argument("--summary", help="Scan summary. Overrides input summary.")
    parser.add_argument("--profile", help="Scoring profile. Overrides input profile.")
    parser.add_argument(
        "--candidates-scanned",
        type=int,
        help="Number of candidate notices reviewed. Overrides input candidates_scanned.",
    )
    parser.add_argument(
        "--item",
        action="append",
        default=[],
        help="Curated item as a JSON object. May be repeated and is appended to input items.",
    )
    parser.add_argument("--env", choices=["prod", "dev"], default=None, help="Workbench runtime env.")
    parser.add_argument("--db", help="Explicit watchlist DB path, mainly for tests.")
    parser.add_argument("--json", action="store_true", help="Print JSON result.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    payload = _load_payload(args.input)
    profile = args.profile or payload.get("profile") or "technical_services"
    summary = args.summary or payload.get("summary") or ""
    items = payload.get("items") or []
    if not isinstance(items, list):
        raise ValueError("items must be a list")
    items = [*items, *[_parse_item(raw) for raw in args.item]]
    candidates_scanned = (
        args.candidates_scanned
        if args.candidates_scanned is not None
        else int(payload.get("candidates_scanned") or 0)
    )

    result = publish_scan(
        summary=summary,
        items=items,
        candidates_scanned=candidates_scanned,
        profile=profile,
        db_path=args.db,
        env=args.env,
    )
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(
            f"Published Workbench scan {result['scan_id']}: "
            f"{result['candidates_shown']} shown / {result['candidates_scanned']} scanned"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
