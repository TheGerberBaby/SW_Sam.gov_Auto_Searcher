"""Select simplified-acquisition candidates from the local SAM.gov mirror.

This workflow deliberately does not score keywords or capability fit. It is a
hard-gate pipeline for finding small, executable buys that may help build past
performance.

The SAM bulk Contract Opportunities CSV does not currently expose an estimated
solicitation-value field. If the SQLite mirror gains ``estimated_value`` later,
this selector uses it automatically. Until then, populated ``award_amount``
(``Award$`` in the bulk CSV) values are used only as a conservative ceiling
fallback; blank values remain eligible and sort in the middle bucket.
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


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "contracts.db"
DEFAULT_MARKDOWN_PATH = PROJECT_ROOT / "reports" / "sap-opportunities.md"
DEFAULT_CSV_PATH = PROJECT_ROOT / "reports" / "sap-opportunities.csv"
DEFAULT_ENCODINGS_PATH = PROJECT_ROOT / "reports" / "sam-opportunity-encodings.md"

SIMPLIFIED_ACQUISITION_THRESHOLD = 350_000.0
MINIMUM_RUNWAY_DAYS = 3
ALLOWED_NOTICE_TYPES = {"Combined Synopsis/Solicitation", "Solicitation"}
ALLOWED_NAICS = {
    "541511",
    "541512",
    "541513",
    "541519",
    "541611",
    "541990",
    "518210",
}
ALLOWED_SET_ASIDE_CODES = {"", "NONE", "SBA", "SBP"}
SMALL_BUSINESS_SET_ASIDE_CODES = {"SBA", "SBP"}
EXCLUDED_PSC_PREFIXES = {"C", "S", "Y", "Z"}
DMV_STATES = {"MD", "VA", "DC"}
DOMESTIC_COUNTRIES = {"", "USA", "US", "UNITED STATES"}
VALUE_COLUMN_PREFERENCE = ("estimated_value", "award_amount")


@dataclass(frozen=True)
class SelectionContext:
    today: date
    minimum_deadline: date
    value_column: str | None
    value_source: str


@dataclass(frozen=True)
class SapOpportunity:
    rank: int
    notice_id: str
    title: str
    solicitation_number: str
    department: str
    sub_tier: str
    office: str
    notice_type: str
    set_aside: str
    set_aside_code: str
    response_deadline: str
    naics_code: str
    psc_code: str
    psc_lane: str
    place_of_performance: str
    reported_value: float | None
    value_source: str
    posted_date: str
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


def _parse_money(value: Any) -> float | None:
    raw = _clean(value)
    if not raw:
        return None
    normalized = raw.replace("$", "").replace(",", "")
    try:
        return float(normalized)
    except ValueError:
        return None


def _table_columns(connection: sqlite3.Connection) -> set[str]:
    return {str(row[1]) for row in connection.execute("PRAGMA table_info(opportunities)")}


def _value_column(columns: set[str]) -> tuple[str | None, str]:
    for column in VALUE_COLUMN_PREFERENCE:
        if column in columns:
            if column == "estimated_value":
                return column, "estimated_value"
            return column, "Award$ fallback"
    return None, "unavailable"


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


def _set_aside_label(code: str, raw_description: Any) -> str:
    description = _clean(raw_description)
    if description:
        return description
    if code in {"", "NONE"}:
        return "Unrestricted"
    return code


def _set_aside_sort(code: str) -> int:
    return 0 if code in SMALL_BUSINESS_SET_ASIDE_CODES else 1


def _psc_lane(raw_code: Any) -> str:
    code = _clean(raw_code).upper()
    if not code:
        return "blank"
    if re.fullmatch(r"D3\d{2}", code):
        return "D301-D399"
    if code.startswith("D"):
        return "D-family"
    return "allowed non-excluded"


def _place_of_performance(row: sqlite3.Row | dict[str, Any]) -> tuple[bool, str]:
    city = _clean(row["pop_city"])
    state = _clean(row["pop_state"]).upper()
    country = _clean(row["pop_country"]).upper()
    street = _clean(row["pop_street"])
    combined = " ".join((street, city, state, country)).lower()
    label = ", ".join(value for value in (city, state, country) if value) or "Blank / nationwide"
    if state in DMV_STATES:
        return True, label
    if "remote" in combined:
        return True, label or "Remote"
    if "nationwide" in combined:
        return True, label or "Nationwide"
    if not state and country in DOMESTIC_COUNTRIES:
        return True, label
    return False, label


def _dedupe_key(row: dict[str, Any]) -> tuple[str, ...]:
    solicitation_number = _clean(row.get("sol_number")).casefold()
    if solicitation_number:
        return ("solicitation", solicitation_number)
    title = re.sub(r"\s+", " ", _clean(row.get("title"))).casefold()
    office = _clean(row.get("office")).casefold()
    deadline = _clean(row.get("response_deadline"))
    return ("fallback", title, office, deadline)


def _latest_row(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in rows:
        key = _dedupe_key(row)
        existing = deduped.get(key)
        if existing is None or _clean(row.get("posted_date")) > _clean(existing.get("posted_date")):
            deduped[key] = row
    return list(deduped.values())


def _load_opportunities(connection: sqlite3.Connection, value_column: str | None) -> list[dict[str, Any]]:
    selected_value = value_column or "NULL"
    sql = f"""
        SELECT notice_id, title, sol_number, department, sub_tier, office,
               posted_date, type, set_aside, set_aside_code, response_deadline,
               naics_code, classification_code, pop_street, pop_city, pop_state,
               pop_country, active, link, {selected_value} AS selected_value
          FROM opportunities
    """
    return [dict(row) for row in connection.execute(sql)]


def select_opportunities(
    rows: Iterable[dict[str, Any]],
    context: SelectionContext,
) -> tuple[list[SapOpportunity], dict[str, int]]:
    gate_counts = {
        "source_rows": 0,
        "inactive_or_short_runway": 0,
        "over_sat": 0,
        "notice_type": 0,
        "naics": 0,
        "psc": 0,
        "place_of_performance": 0,
        "set_aside": 0,
        "survivors_before_dedupe": 0,
        "duplicates_removed": 0,
        "ranked_rows": 0,
    }
    survivors: list[dict[str, Any]] = []
    for row in rows:
        gate_counts["source_rows"] += 1
        deadline = _parse_date(row.get("response_deadline"))
        if _clean(row.get("active")).casefold() != "yes" or not deadline or deadline < context.minimum_deadline:
            gate_counts["inactive_or_short_runway"] += 1
            continue
        value = _parse_money(row.get("selected_value"))
        if value is not None and value > SIMPLIFIED_ACQUISITION_THRESHOLD:
            gate_counts["over_sat"] += 1
            continue
        if _clean(row.get("type")) not in ALLOWED_NOTICE_TYPES:
            gate_counts["notice_type"] += 1
            continue
        if _clean(row.get("naics_code")) not in ALLOWED_NAICS:
            gate_counts["naics"] += 1
            continue
        psc = _clean(row.get("classification_code")).upper()
        if psc[:1] in EXCLUDED_PSC_PREFIXES:
            gate_counts["psc"] += 1
            continue
        allowed_pop, pop_label = _place_of_performance(row)
        if not allowed_pop:
            gate_counts["place_of_performance"] += 1
            continue
        set_aside_code = _normalize_set_aside_code(row.get("set_aside_code"), row.get("set_aside"))
        if set_aside_code not in ALLOWED_SET_ASIDE_CODES:
            gate_counts["set_aside"] += 1
            continue
        normalized = dict(row)
        normalized["deadline_date"] = deadline
        normalized["reported_value"] = value
        normalized["pop_label"] = pop_label
        normalized["psc"] = psc
        normalized["canonical_set_aside_code"] = set_aside_code
        survivors.append(normalized)

    gate_counts["survivors_before_dedupe"] = len(survivors)
    deduped = _latest_row(survivors)
    gate_counts["duplicates_removed"] = len(survivors) - len(deduped)
    deduped.sort(
        key=lambda row: (
            1 if row["reported_value"] is None else 0,
            row["reported_value"] if row["reported_value"] is not None else 0,
            _set_aside_sort(row["canonical_set_aside_code"]),
            row["deadline_date"],
            _clean(row.get("title")).casefold(),
        )
    )

    ranked: list[SapOpportunity] = []
    for index, row in enumerate(deduped, start=1):
        ranked.append(
            SapOpportunity(
                rank=index,
                notice_id=_clean(row.get("notice_id")),
                title=_clean(row.get("title")),
                solicitation_number=_clean(row.get("sol_number")),
                department=_clean(row.get("department")),
                sub_tier=_clean(row.get("sub_tier")),
                office=_clean(row.get("office")),
                notice_type=_clean(row.get("type")),
                set_aside=_set_aside_label(row["canonical_set_aside_code"], row.get("set_aside")),
                set_aside_code=row["canonical_set_aside_code"] or "UNRESTRICTED-BLANK",
                response_deadline=_clean(row.get("response_deadline")),
                naics_code=_clean(row.get("naics_code")),
                psc_code=row["psc"] or "BLANK",
                psc_lane=_psc_lane(row["psc"]),
                place_of_performance=row["pop_label"],
                reported_value=row["reported_value"],
                value_source=context.value_source if row["reported_value"] is not None else "null",
                posted_date=_clean(row.get("posted_date")),
                link=_clean(row.get("link")),
            )
        )
    gate_counts["ranked_rows"] = len(ranked)
    return ranked, gate_counts


def observed_set_asides(connection: sqlite3.Connection) -> list[tuple[str, str, int]]:
    sql = """
        SELECT COALESCE(NULLIF(TRIM(set_aside), ''), '<blank>') AS description,
               COALESCE(NULLIF(TRIM(set_aside_code), ''), '<blank>') AS code,
               COUNT(*) AS row_count
          FROM opportunities
         GROUP BY 1, 2
         ORDER BY 1, 2
    """
    return [(str(row[0]), str(row[1]), int(row[2])) for row in connection.execute(sql)]


def observed_psc_codes(connection: sqlite3.Connection) -> list[tuple[str, int]]:
    sql = """
        SELECT COALESCE(NULLIF(TRIM(classification_code), ''), '<blank>') AS psc,
               COUNT(*) AS row_count
          FROM opportunities
         GROUP BY 1
         ORDER BY 1
    """
    return [(str(row[0]), int(row[1])) for row in connection.execute(sql)]


def print_encodings(
    set_asides: list[tuple[str, str, int]],
    psc_codes: list[tuple[str, int]],
) -> None:
    print("# Distinct SAM.gov set-aside encodings present in opportunities")
    for description, code, count in set_asides:
        print(f"{code:<14} {count:>7,}  {description}")
    print(f"\n# Distinct SAM.gov PSC codes present in opportunities ({len(psc_codes):,})")
    print(", ".join(code for code, _ in psc_codes))


def _escape(value: Any) -> str:
    return _clean(value).replace("|", "\\|").replace("\n", " ")


def _money(value: float | None) -> str:
    return "null" if value is None else f"${value:,.0f}"


def write_csv(path: Path, opportunities: list[SapOpportunity]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(SapOpportunity.__dataclass_fields__)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for opportunity in opportunities:
            writer.writerow(asdict(opportunity))


def write_encodings_markdown(
    path: Path,
    set_asides: list[tuple[str, str, int]],
    psc_codes: list[tuple[str, int]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# SAM Opportunity Encoding Inventory",
        "",
        "Observed directly from `data/contracts.db` table `opportunities`.",
        "",
        "## Set-Aside Encodings",
        "",
        "| Set-aside code | Rows | Description |",
        "| --- | ---: | --- |",
    ]
    for description, code, count in set_asides:
        lines.append(f"| `{_escape(code)}` | {count:,} | {_escape(description)} |")
    lines.extend(
        [
            "",
            "## PSC Codes",
            "",
            f"Distinct PSC codes: `{len(psc_codes):,}`.",
            "",
            "| PSC | Rows |",
            "| --- | ---: |",
        ]
    )
    for code, count in psc_codes:
        lines.append(f"| `{_escape(code)}` | {count:,} |")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_markdown(
    path: Path,
    opportunities: list[SapOpportunity],
    gate_counts: dict[str, int],
    context: SelectionContext,
    encodings_path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    value_note = (
        "`estimated_value`"
        if context.value_source == "estimated_value"
        else "`Award$` fallback when populated; blank values retained as null"
    )
    lines = [
        "# Ranked SAM.gov Simplified-Acquisition Candidates",
        "",
        f"_Generated: `{context.today.isoformat()}` from local SAM.gov SQLite mirror "
        "`data/contracts.db`. No keyword or capability scoring is used._",
        "",
        "## Selection Rules",
        "",
        f"- Active notice with response deadline on or after `{context.minimum_deadline.isoformat()}`.",
        f"- Value gate: `{SIMPLIFIED_ACQUISITION_THRESHOLD:,.0f}` Simplified Acquisition "
        f"Threshold. Source used: {value_note}.",
        "- Notice type: `Combined Synopsis/Solicitation` or `Solicitation`.",
        f"- NAICS: `{', '.join(sorted(ALLOWED_NAICS))}`.",
        "- PSC: allow D-family services and other non-excluded PSCs; exclude PSC families "
        "`C*`, `S*`, `Y*`, and `Z*`.",
        "- Place of performance: `MD`, `VA`, `DC`, domestic blank/nationwide, or remote.",
        "- Set-aside: `SBA`, `SBP`, `NONE`, or blank/unrestricted. Restricted program "
        "set-asides such as `8A`, `HZC`, and `WOSB` are excluded.",
        "- Ranking: value ascending with null values after populated values, small-business "
        "set-asides before unrestricted, then soonest response deadline.",
        "- Amendment copies are deduplicated by solicitation number when one is present; "
        "the latest posted copy is retained.",
        "",
        "## Gate Counts",
        "",
        "| Metric | Rows |",
        "| --- | ---: |",
    ]
    for key, count in gate_counts.items():
        lines.append(f"| `{_escape(key)}` | {count:,} |")
    lines.extend(
        [
            "",
            "## Observed Encoding Map",
            "",
            f"Full set-aside and PSC inventory: [{encodings_path.name}]({encodings_path.name})",
            "",
            "Allowed real set-aside encodings observed in the mirror:",
            "",
            "| Meaning | Stored code |",
            "| --- | --- |",
            "| Total Small Business Set-Aside | `SBA` |",
            "| Partial Small Business Set-Aside | `SBP` |",
            "| Unrestricted | `NONE` or blank |",
            "",
            "## Ranked Opportunities",
            "",
            "| Rank | Value used for SAT gate | Set-aside | Response deadline | NAICS | PSC | Place of performance | Notice type | Opportunity |",
            "| ---: | ---: | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for opportunity in opportunities:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(opportunity.rank),
                    _money(opportunity.reported_value),
                    _escape(opportunity.set_aside_code),
                    _escape(opportunity.response_deadline),
                    _escape(opportunity.naics_code),
                    _escape(opportunity.psc_code),
                    _escape(opportunity.place_of_performance),
                    _escape(opportunity.notice_type),
                    f"[{_escape(opportunity.title)}]({_escape(opportunity.link)})",
                ]
            )
            + " |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN_PATH)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV_PATH)
    parser.add_argument("--encodings", type=Path, default=DEFAULT_ENCODINGS_PATH)
    parser.add_argument("--today", type=date.fromisoformat, default=date.today())
    parser.add_argument("--print-encodings-only", action="store_true")
    parser.add_argument("--json", action="store_true", help="Print summary JSON after writing files")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.db.exists():
        raise SystemExit(f"SAM SQLite mirror not found: {args.db}. Run `swcb sync` first.")
    with sqlite3.connect(args.db) as connection:
        connection.row_factory = sqlite3.Row
        columns = _table_columns(connection)
        value_column, value_source = _value_column(columns)
        set_asides = observed_set_asides(connection)
        psc_codes = observed_psc_codes(connection)
        print_encodings(set_asides, psc_codes)
        write_encodings_markdown(args.encodings, set_asides, psc_codes)
        if args.print_encodings_only:
            return 0
        context = SelectionContext(
            today=args.today,
            minimum_deadline=args.today + timedelta(days=MINIMUM_RUNWAY_DAYS),
            value_column=value_column,
            value_source=value_source,
        )
        rows = _load_opportunities(connection, value_column)
    opportunities, gate_counts = select_opportunities(rows, context)
    write_csv(args.csv, opportunities)
    write_markdown(args.markdown, opportunities, gate_counts, context, args.encodings)
    summary = {
        "source": str(args.db),
        "value_column": value_column,
        "value_source": value_source,
        "minimum_deadline": context.minimum_deadline.isoformat(),
        "markdown": str(args.markdown),
        "csv": str(args.csv),
        "encodings": str(args.encodings),
        "gate_counts": gate_counts,
    }
    if args.json:
        print("\n" + json.dumps(summary, indent=2))
    else:
        print(
            f"\nWrote {gate_counts['ranked_rows']:,} ranked SAP candidates to "
            f"{args.markdown} and {args.csv}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
