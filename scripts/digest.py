"""Daily digest generator.

Scans the local SAM mirror for recently posted opportunities, scores them
with `scoring.py`, groups the strongest hits by capability lane, and writes
a markdown + HTML report. Each run is recorded in the watchlist DB so a
history is preserved.

Usage:
    python scripts/digest.py
    python scripts/digest.py --profile elastic_only --days 3 --min-score 4
    python scripts/digest.py --no-write   # print to stdout only
"""

from __future__ import annotations

import argparse
import html
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from scoring import (  # noqa: E402
    LOCAL_TZ,
    ScoreResult,
    available_profiles,
    bulk_score,
)
from watchlist import Store  # noqa: E402

PROJECT_ROOT = SCRIPT_DIR.parent
DB_PATH = PROJECT_ROOT / "data" / "contracts.db"
REPORTS_DIR = PROJECT_ROOT / "data" / "digests"

LANE_LABELS = {
    "elastic_search": "Elastic / Search",
    "ai_retrieval": "AI / Retrieval (RAG, vector, semantic)",
    "observability_siem": "Observability / SIEM / Log Analytics",
    "data_platform": "Data Platform / DevSecOps",
    "network_vtc": "Network / VTC / UC",
    "unclassified": "Unclassified (no lane match)",
}


def _query_recent(days: int, limit: int) -> list[dict[str, Any]]:
    if not DB_PATH.exists():
        raise SystemExit(f"DB not found at {DB_PATH}. Run scripts/sync_bulk.py first.")
    cutoff = (datetime.now(LOCAL_TZ).date() - timedelta(days=days)).isoformat()
    sql = """
        SELECT notice_id, title, sol_number, department, sub_tier, posted_date,
               type, set_aside, set_aside_code, response_deadline, naics_code,
               pop_city, pop_state, active, link, description
          FROM opportunities
         WHERE active = 'Yes' AND posted_date >= ?
         ORDER BY posted_date DESC
         LIMIT ?
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, (cutoff, limit)).fetchall()
    return [dict(row) for row in rows]


def _opportunity_lookup(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {row["notice_id"]: row for row in rows}


def _group_by_lane(scored: list[ScoreResult]) -> dict[str, list[ScoreResult]]:
    grouped: dict[str, list[ScoreResult]] = defaultdict(list)
    for result in scored:
        lanes = result.lanes or ["unclassified"]
        for lane in lanes:
            grouped[lane].append(result)
    for lane in grouped:
        grouped[lane].sort(key=lambda r: r.score, reverse=True)
    return grouped


def render_markdown(
    profile: str,
    days: int,
    min_score: int,
    scored: list[ScoreResult],
    opportunities: dict[str, dict[str, Any]],
    generated_at: datetime,
) -> str:
    lines: list[str] = []
    lines.append(f"# SAM.gov Daily Digest — {generated_at.date().isoformat()}")
    lines.append("")
    lines.append(f"Profile: **{profile}** · Window: last **{days}** days · Min score: **{min_score}** · Generated: {generated_at.isoformat(timespec='seconds')}")
    lines.append("")
    lines.append(f"Scored opportunities surfaced: **{len(scored)}**")
    lines.append("")
    if not scored:
        lines.append("_No opportunities cleared the threshold this run._")
        return "\n".join(lines)

    grouped = _group_by_lane(scored)
    lane_order = [lane for lane in LANE_LABELS if lane in grouped]
    for lane in lane_order:
        results = grouped[lane]
        lines.append(f"## {LANE_LABELS[lane]} ({len(results)})")
        lines.append("")
        for result in results[:10]:
            opp = opportunities.get(result.notice_id, {})
            deadline = opp.get("response_deadline") or "-"
            naics = opp.get("naics_code") or "-"
            set_aside = opp.get("set_aside") or "-"
            agency = opp.get("department") or "-"
            link = opp.get("link") or ""
            link_md = f"[notice]({link})" if link else ""
            lines.append(f"### [{result.band.upper()} +{result.score}] {result.title}")
            lines.append("")
            lines.append(f"- **Agency:** {agency}")
            lines.append(f"- **NAICS:** {naics} · **Set-aside:** {set_aside}")
            lines.append(f"- **Posted:** {opp.get('posted_date') or '-'} · **Response due:** {deadline}")
            lines.append(f"- **Notice ID:** `{result.notice_id}` {link_md}")
            lines.append("")
            lines.append("**Why:**")
            for reason in result.reasons:
                sign = "+" if reason.points > 0 else ""
                lines.append(f"  - `{sign}{reason.points}` {reason.kind} — {reason.detail}")
            lines.append("")
    return "\n".join(lines)


def render_html(
    profile: str,
    days: int,
    min_score: int,
    scored: list[ScoreResult],
    opportunities: dict[str, dict[str, Any]],
    generated_at: datetime,
) -> str:
    BAND_COLORS = {
        "strong": "#16a34a",
        "promising": "#2563eb",
        "monitor": "#a16207",
        "reject": "#9ca3af",
    }
    grouped = _group_by_lane(scored) if scored else {}
    lane_order = [lane for lane in LANE_LABELS if lane in grouped]

    css = """
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 1100px; margin: 2rem auto; padding: 0 1.5rem; color: #1f2937; background: #f9fafb; }
    h1 { border-bottom: 2px solid #2563eb; padding-bottom: .4rem; }
    h2 { margin-top: 2.5rem; color: #1e3a8a; border-bottom: 1px solid #d1d5db; padding-bottom: .25rem; }
    .meta { color: #4b5563; font-size: .95rem; margin-bottom: 1rem; }
    .card { background: white; border-radius: 8px; padding: 1rem 1.25rem; margin-bottom: 1rem; box-shadow: 0 1px 2px rgba(0,0,0,.05); border-left: 4px solid #2563eb; }
    .card .title { font-weight: 600; font-size: 1.05rem; margin-bottom: .25rem; }
    .badge { display: inline-block; padding: .15rem .55rem; border-radius: 999px; color: white; font-size: .8rem; font-weight: 600; margin-right: .35rem; }
    .meta-row { color: #4b5563; font-size: .88rem; margin: .1rem 0; }
    .reasons { margin-top: .4rem; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .82rem; color: #374151; }
    .reasons span { display: inline-block; padding: .1rem .45rem; margin: .1rem .25rem .1rem 0; background: #eef2ff; border-radius: 4px; }
    .reasons .neg { background: #fef2f2; color: #991b1b; }
    a { color: #2563eb; text-decoration: none; }
    a:hover { text-decoration: underline; }
    .empty { padding: 2rem; background: white; border-radius: 8px; text-align: center; color: #6b7280; }
    """

    parts: list[str] = [
        "<!DOCTYPE html>",
        "<html lang='en'><head><meta charset='utf-8'>",
        f"<title>SAM Digest {generated_at.date().isoformat()}</title>",
        f"<style>{css}</style>",
        "</head><body>",
        f"<h1>SAM.gov Daily Digest — {generated_at.date().isoformat()}</h1>",
        f"<div class='meta'>Profile: <b>{html.escape(profile)}</b> · Window: last <b>{days}</b> days · Min score: <b>{min_score}</b> · "
        f"Generated: {generated_at.isoformat(timespec='seconds')}<br>"
        f"Scored opportunities surfaced: <b>{len(scored)}</b></div>",
    ]
    if not scored:
        parts.append("<div class='empty'>No opportunities cleared the threshold this run.</div>")
    for lane in lane_order:
        parts.append(f"<h2>{html.escape(LANE_LABELS[lane])} <small style='color:#6b7280'>({len(grouped[lane])})</small></h2>")
        for result in grouped[lane][:10]:
            opp = opportunities.get(result.notice_id, {})
            band = result.band
            color = BAND_COLORS.get(band, "#374151")
            badge = f"<span class='badge' style='background:{color}'>{band.upper()} +{result.score}</span>"
            link = opp.get("link") or ""
            link_html = f"<a href='{html.escape(link)}' target='_blank' rel='noopener'>open notice</a>" if link else ""
            reasons_html = "".join(
                f"<span class='{'neg' if r.points < 0 else ''}'>"
                f"{('+' if r.points > 0 else '')}{r.points} {html.escape(r.kind)}: {html.escape(r.detail)}</span>"
                for r in result.reasons
            )
            parts.append(
                f"<div class='card'>"
                f"<div class='title'>{badge}{html.escape(result.title)}</div>"
                f"<div class='meta-row'><b>Agency:</b> {html.escape(opp.get('department') or '-')} / {html.escape(opp.get('sub_tier') or '-')}</div>"
                f"<div class='meta-row'><b>NAICS:</b> {html.escape(opp.get('naics_code') or '-')} · "
                f"<b>Set-aside:</b> {html.escape(opp.get('set_aside') or '-')} · "
                f"<b>Type:</b> {html.escape(opp.get('type') or '-')}</div>"
                f"<div class='meta-row'><b>Posted:</b> {html.escape(opp.get('posted_date') or '-')} · "
                f"<b>Response due:</b> {html.escape(opp.get('response_deadline') or '-')}</div>"
                f"<div class='meta-row'><b>Notice ID:</b> <code>{html.escape(result.notice_id)}</code> · {link_html}</div>"
                f"<div class='reasons'>{reasons_html}</div>"
                f"</div>"
            )
    parts.append("</body></html>")
    return "\n".join(parts)


def generate_digest(
    profile: str = "technical_services",
    days: int = 3,
    min_score: int = 2,
    limit_scan: int = 2000,
    write: bool = True,
) -> dict[str, Any]:
    if profile not in available_profiles():
        raise ValueError(f"Unknown profile {profile!r}. Available: {available_profiles()}")
    generated_at = datetime.now(LOCAL_TZ)
    rows = _query_recent(days=days, limit=limit_scan)
    scored_all = bulk_score(rows, profile=profile)
    scored = [s for s in scored_all if s.score >= min_score]
    scored.sort(key=lambda r: r.score, reverse=True)
    opportunities = _opportunity_lookup(rows)

    markdown = render_markdown(profile, days, min_score, scored, opportunities, generated_at)
    html_doc = render_html(profile, days, min_score, scored, opportunities, generated_at)

    md_path: Path | None = None
    html_path: Path | None = None
    if write:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = generated_at.strftime("%Y%m%d_%H%M%S")
        md_path = REPORTS_DIR / f"digest_{profile}_{stamp}.md"
        html_path = REPORTS_DIR / f"digest_{profile}_{stamp}.html"
        md_path.write_text(markdown, encoding="utf-8")
        html_path.write_text(html_doc, encoding="utf-8")

        try:
            store = Store()
            store.record_digest_run(
                profile=profile,
                candidates_scanned=len(rows),
                candidates_shown=len(scored),
                report_path=str(html_path),
                summary=f"{len(scored)} of {len(rows)} scored at >= {min_score}",
            )
        except Exception as exc:  # noqa: BLE001
            print(f"WARN: failed to record digest run: {exc}", file=sys.stderr)

    return {
        "generated_at": generated_at.isoformat(),
        "profile": profile,
        "scanned": len(rows),
        "shown": len(scored),
        "markdown": markdown,
        "html": html_doc,
        "markdown_path": str(md_path) if md_path else None,
        "html_path": str(html_path) if html_path else None,
        "results": [s.to_dict() for s in scored],
    }


def _cli() -> None:
    parser = argparse.ArgumentParser(description="Generate a daily SAM.gov digest.")
    parser.add_argument("--profile", default="technical_services", choices=available_profiles())
    parser.add_argument("--days", type=int, default=3, help="Look at notices posted in the last N days (default 3).")
    parser.add_argument("--min-score", dest="min_score", type=int, default=2)
    parser.add_argument("--limit-scan", dest="limit_scan", type=int, default=2000)
    parser.add_argument("--no-write", action="store_true", help="Don't write files; print markdown to stdout.")
    args = parser.parse_args()

    result = generate_digest(
        profile=args.profile,
        days=args.days,
        min_score=args.min_score,
        limit_scan=args.limit_scan,
        write=not args.no_write,
    )
    if args.no_write:
        print(result["markdown"])
    else:
        print(f"Generated digest: {result['shown']} / {result['scanned']} scored")
        print(f"  markdown: {result['markdown_path']}")
        print(f"  html:     {result['html_path']}")


if __name__ == "__main__":
    _cli()
