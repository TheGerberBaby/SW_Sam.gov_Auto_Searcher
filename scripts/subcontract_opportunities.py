"""Rank prime-with-subcontractor opportunity candidates from the SAM mirror.

This is an optional pursuit lane for opportunities where Stormwind would bid as
the prime contractor and source a qualified first-tier small-business
subcontractor for field performance. It is not a pass-through approval tool:
the prime remains responsible for delivery and each solicitation still needs a
clause, licensing, scope, margin, and similarly-situated-entity review.

Examples:
  python scripts/subcontract_opportunities.py
  python scripts/swcb.py subcontract-leads --limit 25 --json
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from source_vendors import VENDOR_PROFILES

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "contracts.db"
DEFAULT_MARKDOWN_PATH = PROJECT_ROOT / "reports" / "subcontract-opportunities.md"
DEFAULT_CSV_PATH = PROJECT_ROOT / "reports" / "subcontract-opportunities.csv"
MINIMUM_RUNWAY_DAYS = 3
ALLOWED_NOTICE_TYPES = {"Combined Synopsis/Solicitation", "Solicitation"}
ALLOWED_SET_ASIDE_CODES = {"", "NONE", "SBA", "SBP"}
DOMESTIC_COUNTRIES = {"", "USA", "US", "UNITED STATES"}
LOWER_RISK_NAICS = {"561720", "561730", "561790", "562111"}
DMV_STATES = {"DC", "MD", "VA"}
PROFILE_SCOPE_TERMS = {
    "561621": (
        "access control",
        "badge reader",
        "camera",
        "card reader",
        "cctv",
        "pacs",
        "security system",
        "video monitoring",
        "video surveillance",
    ),
    "238210": (
        "cabling",
        "cat6",
        "data cable",
        "fiber",
        "low voltage",
        "network drop",
        "patch panel",
        "structured cable",
    ),
    "561790": ("exhaust hood", "hood cleaning", "hoods and ducts", "kitchen hood"),
    "562111": ("dumpster", "garbage", "recycling", "refuse", "solid waste", "trash"),
    "561720": ("cleaning service", "custodial", "janitorial"),
    "561730": (
        "grounds maintenance",
        "landscaping",
        "mowing",
        "prune",
        "tree maintenance",
        "tree removal",
        "vista maintenance",
    ),
    "238220": ("air conditioning", "boiler", "hvac", "mechanical", "plumbing"),
}
DIRECT_BUY_EXCLUSIONS = (
    "sources sought",
    "source sought",
    "request for information",
    "this is not a solicitation",
    "presolicitation",
    "pre-solicitation",
    "notice of intent",
    "sole source",
    "award notice",
    "justification",
)
RISK_TERMS = {
    "life-safety / fire-system review": ("fire alarm", "fire sprinkler", "life safety"),
    "construction-scope review": ("construction", "design-build", "design build", "renovation"),
    "OEM / proprietary-system review": (
        "brand name only",
        "authorized installer",
        "lenel",
        "genetec",
        "amag",
        "gallagher",
        "milestone",
    ),
    "licensing / code review": ("licensed", "license", "permit", "code compliance", "nfpa"),
    "multi-site / travel review": ("multiple locations", "multi-site", "nationwide", "various locations"),
    "response-SLA / staffing review": ("24/7", "24 hours", "emergency response", "on-call"),
    "special-access review": ("clearance", "background check", "badging", "base access"),
    "hazardous-material review": ("asbestos", "hazardous", "hazmat", "lead paint"),
    "managed-service / product review": ("alarm services", "cloud-managed", "monitoring service"),
}
NARROW_SCOPE_TERMS = (
    "cleaning",
    "collection",
    "custodial",
    "dumpster",
    "grounds",
    "hood",
    "landscaping",
    "maintenance",
    "mowing",
    "trash",
    "waste",
    "access control",
    "camera",
    "cabling",
    "cctv",
    "fiber",
    "security system",
    "video monitoring",
)


@dataclass(frozen=True)
class SubcontractOpportunity:
    rank: int
    score: int
    disposition: str
    notice_id: str
    title: str
    solicitation_number: str
    department: str
    notice_type: str
    set_aside: str
    set_aside_code: str
    response_deadline: str
    naics_code: str
    performer_lane: str
    place_of_performance: str
    risk_flags: str
    vendor_command: str
    link: str


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _parse_date(value: Any) -> date | None:
    raw = _clean(value)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return None


def _normalize_set_aside_code(raw_code: Any, raw_description: Any) -> str:
    code = _clean(raw_code).upper()
    if code.startswith("["):
        try:
            parsed = json.loads(code)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list) and len(parsed) == 1:
            code = _clean(parsed[0]).upper()
    if code:
        return code
    description = _clean(raw_description).lower()
    if "partial small business" in description:
        return "SBP"
    if "total small business" in description:
        return "SBA"
    if description == "no set aside used":
        return "NONE"
    return ""


def _place(row: dict[str, Any]) -> tuple[bool, str]:
    city = _clean(row.get("pop_city"))
    state = _clean(row.get("pop_state")).upper()
    country = _clean(row.get("pop_country")).upper()
    label = ", ".join(value for value in (city, state) if value) or "Verify place of performance"
    return country in DOMESTIC_COUNTRIES, label


def _dedupe_key(row: dict[str, Any]) -> tuple[str, ...]:
    solicitation = _clean(row.get("sol_number")).casefold()
    if solicitation:
        return ("solicitation", solicitation)
    return ("notice", _clean(row.get("notice_id")).casefold())


def _latest_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in rows:
        key = _dedupe_key(row)
        existing = deduped.get(key)
        if existing is None or _clean(row.get("posted_date")) > _clean(existing.get("posted_date")):
            deduped[key] = row
    return list(deduped.values())


def _risk_flags(text: str) -> list[str]:
    lowered = text.casefold()
    return [
        label
        for label, terms in RISK_TERMS.items()
        if any(term in lowered for term in terms)
    ]


def _vendor_command(naics: str, place: str, due: str) -> str:
    return f'python scripts/swcb.py vendors --naics {naics} --place "{place}" --due "{due[:10]}"'


def select_opportunities(
    rows: Iterable[dict[str, Any]],
    today: date,
    minimum_runway_days: int = MINIMUM_RUNWAY_DAYS,
) -> tuple[list[SubcontractOpportunity], dict[str, int]]:
    """Apply hard gates and rank candidates for manual pursuit review."""
    counts = {
        "source_rows": 0,
        "inactive_or_short_runway": 0,
        "not_direct_buy": 0,
        "outside_sourcing_profiles": 0,
        "scope_mismatch": 0,
        "restricted_set_aside": 0,
        "foreign": 0,
        "awarded": 0,
        "survivors_before_dedupe": 0,
        "duplicates_removed": 0,
        "ranked_rows": 0,
    }
    minimum_deadline = today + timedelta(days=max(0, minimum_runway_days))
    survivors: list[dict[str, Any]] = []
    for row in rows:
        counts["source_rows"] += 1
        deadline = _parse_date(row.get("response_deadline"))
        if _clean(row.get("active")).casefold() != "yes" or not deadline or deadline < minimum_deadline:
            counts["inactive_or_short_runway"] += 1
            continue
        text = " ".join((_clean(row.get("title")), _clean(row.get("description")))).casefold()
        if _clean(row.get("type")) not in ALLOWED_NOTICE_TYPES or any(term in text for term in DIRECT_BUY_EXCLUSIONS):
            counts["not_direct_buy"] += 1
            continue
        naics = _clean(row.get("naics_code"))
        profile = VENDOR_PROFILES.get(naics)
        if not profile:
            counts["outside_sourcing_profiles"] += 1
            continue
        if not any(term in text for term in PROFILE_SCOPE_TERMS[naics]):
            counts["scope_mismatch"] += 1
            continue
        set_aside_code = _normalize_set_aside_code(row.get("set_aside_code"), row.get("set_aside"))
        if set_aside_code not in ALLOWED_SET_ASIDE_CODES:
            counts["restricted_set_aside"] += 1
            continue
        domestic, place = _place(row)
        if not domestic:
            counts["foreign"] += 1
            continue
        if _clean(row.get("awardee")) or _clean(row.get("award_number")):
            counts["awarded"] += 1
            continue
        normalized = dict(row)
        normalized["deadline_date"] = deadline
        normalized["place"] = place
        normalized["profile"] = profile
        normalized["set_aside_code"] = set_aside_code
        normalized["flags"] = _risk_flags(text)
        normalized["text"] = text
        survivors.append(normalized)

    counts["survivors_before_dedupe"] = len(survivors)
    deduped = _latest_rows(survivors)
    counts["duplicates_removed"] = len(survivors) - len(deduped)

    ranked_rows: list[tuple[int, dict[str, Any]]] = []
    for row in deduped:
        score = 3
        if row["set_aside_code"] in {"SBA", "SBP"}:
            score += 2
        if _clean(row.get("type")) == "Combined Synopsis/Solicitation":
            score += 1
        if _clean(row.get("naics_code")) in LOWER_RISK_NAICS:
            score += 1
        if _clean(row.get("pop_state")).upper() in DMV_STATES:
            score += 1
        if any(term in row["text"] for term in NARROW_SCOPE_TERMS):
            score += 1
        score -= min(len(row["flags"]), 3)
        ranked_rows.append((score, row))
    ranked_rows.sort(
        key=lambda item: (
            -item[0],
            item[1]["deadline_date"],
            _clean(item[1].get("title")).casefold(),
        )
    )

    results = []
    for rank, (score, row) in enumerate(ranked_rows, start=1):
        flags = row["flags"]
        results.append(
            SubcontractOpportunity(
                rank=rank,
                score=score,
                disposition=(
                    "assess now"
                    if score >= 7
                    and not flags
                    and _clean(row.get("naics_code")) in LOWER_RISK_NAICS
                    and row["place"] != "Verify place of performance"
                    else "manual review"
                ),
                notice_id=_clean(row.get("notice_id")),
                title=_clean(row.get("title")),
                solicitation_number=_clean(row.get("sol_number")),
                department=_clean(row.get("department")),
                notice_type=_clean(row.get("type")),
                set_aside=_clean(row.get("set_aside")) or "Unrestricted / not stated",
                set_aside_code=row["set_aside_code"] or "UNRESTRICTED-BLANK",
                response_deadline=_clean(row.get("response_deadline")),
                naics_code=_clean(row.get("naics_code")),
                performer_lane=_clean(row["profile"].get("label")),
                place_of_performance=row["place"],
                risk_flags="; ".join(flags) or "none detected from notice text",
                vendor_command=_vendor_command(
                    _clean(row.get("naics_code")),
                    row["place"],
                    _clean(row.get("response_deadline")),
                ),
                link=_clean(row.get("link")),
            )
        )
    counts["ranked_rows"] = len(results)
    return results, counts


def _load_rows(path: Path) -> list[dict[str, Any]]:
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        return [
            dict(row)
            for row in connection.execute(
                """
                SELECT notice_id, title, sol_number, department, posted_date,
                       type, set_aside, set_aside_code, response_deadline,
                       naics_code, pop_city, pop_state, pop_country, active,
                       award_number, awardee, link, description
                  FROM opportunities
                """
            )
        ]


def write_csv(path: Path, opportunities: list[SubcontractOpportunity]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(SubcontractOpportunity.__dataclass_fields__))
        writer.writeheader()
        for opportunity in opportunities:
            writer.writerow(asdict(opportunity))


def write_markdown(
    path: Path,
    opportunities: list[SubcontractOpportunity],
    counts: dict[str, int],
    today: date,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Prime-With-Subcontractor Opportunity Candidates",
        "",
        f"_Generated: `{today.isoformat()}` from `data/contracts.db`._",
        "",
        "This is a discovery report, not a bid approval. Stormwind remains responsible",
        "for contract delivery. Before bidding, verify the current SAM notice, scope,",
        "clauses, margin, licensing, insurance, place of performance, and whether the",
        "chosen first-tier subcontractor qualifies as similarly situated when required.",
        "",
        "## Gate Counts",
        "",
        "| Metric | Rows |",
        "| --- | ---: |",
    ]
    for key, count in counts.items():
        lines.append(f"| `{key}` | {count:,} |")
    lines.extend(
        [
            "",
            "## Candidates",
            "",
            "| Rank | Score | Disposition | Due | Set-aside | NAICS | Performer lane | Place | Risks | Opportunity |",
            "| ---: | ---: | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for opportunity in opportunities:
        values = [
            str(opportunity.rank),
            str(opportunity.score),
            opportunity.disposition,
            opportunity.response_deadline,
            opportunity.set_aside_code,
            opportunity.naics_code,
            opportunity.performer_lane,
            opportunity.place_of_performance,
            opportunity.risk_flags,
            f"[{opportunity.title}]({opportunity.link})",
        ]
        lines.append("| " + " | ".join(value.replace("|", "\\|").replace("\n", " ") for value in values) + " |")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN_PATH)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV_PATH)
    parser.add_argument("--today", type=date.fromisoformat, default=date.today())
    parser.add_argument("--min-runway", type=int, default=MINIMUM_RUNWAY_DAYS)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.db.exists():
        raise SystemExit(f"SAM SQLite mirror not found: {args.db}. Run `swcb sync` first.")
    opportunities, counts = select_opportunities(_load_rows(args.db), args.today, args.min_runway)
    opportunities = opportunities[: max(1, args.limit)]
    write_csv(args.csv, opportunities)
    write_markdown(args.markdown, opportunities, counts, args.today)
    summary = {
        "source": str(args.db),
        "minimum_deadline": (args.today + timedelta(days=max(0, args.min_runway))).isoformat(),
        "markdown": str(args.markdown),
        "csv": str(args.csv),
        "gate_counts": counts,
        "shown": len(opportunities),
        "opportunities": [asdict(opportunity) for opportunity in opportunities],
    }
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"Wrote {len(opportunities):,} candidates to {args.markdown} and {args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
