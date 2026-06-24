"""Build a DMV NAICS 541512 buyer-intelligence target list.

The USAspending advanced-search endpoint provides award summaries. The award
detail endpoint adds the awarding office and the potential period-of-
performance end date. SAM.gov does not publish a guaranteed future recompete
date for most awards, so this report uses a clearly labeled planning estimate:
potential PoP end minus nine calendar months.
"""

from __future__ import annotations

import argparse
import calendar
import csv
import http.client
import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib import error, parse, request


PROJECT_ROOT = Path(__file__).resolve().parents[2]
API_BASE = "https://api.usaspending.gov/api/v2"
USER_AGENT = "SW-Contracting-Bots/2.2 (Stormwind Contracting buyer research)"
AWARD_TYPE_CODES = ["A", "B", "C", "D"]
DEFAULT_STATES = ["MD", "VA", "DC"]
SUMMARY_FIELDS = [
    "Award ID",
    "Recipient Name",
    "Award Amount",
    "Description",
    "Contract Award Type",
    "Awarding Agency",
    "Awarding Sub Agency",
    "NAICS",
    "PSC",
    "Start Date",
    "End Date",
    "Place of Performance State Code",
    "generated_internal_id",
]


@dataclass
class Target:
    estimated_recompete_date: str
    pop_end_date: str
    pop_end_basis: str
    pop_state: str
    buying_agency_office: str
    recent_award_value: float
    incumbent_vendor: str
    award_id: str
    award_url: str
    description: str


@dataclass
class SamSignal:
    title: str
    agency_office: str
    notice_type: str
    response_deadline: str
    pop_state: str
    notice_url: str


def _json_request(
    url: str,
    *,
    body: dict[str, Any] | None = None,
    timeout: int = 45,
    attempts: int = 5,
) -> dict[str, Any]:
    headers = {"User-Agent": USER_AGENT}
    data = None
    method = "GET"
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
        method = "POST"
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        req = request.Request(url, data=data, headers=headers, method=method)
        try:
            with request.urlopen(req, timeout=timeout) as response:
                return json.load(response)
        except (
            error.HTTPError,
            error.URLError,
            TimeoutError,
            ConnectionError,
            http.client.RemoteDisconnected,
        ) as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(min(15, 2**attempt))
    raise RuntimeError(f"USAspending request failed for {url}: {last_error}") from last_error


def _date_value(raw: Any) -> date | None:
    if not raw:
        return None
    text = str(raw).strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _subtract_months(value: date, months: int) -> date:
    year = value.year
    month = value.month - months
    while month <= 0:
        year -= 1
        month += 12
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _money(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0


def _agency_office(detail: dict[str, Any], summary: dict[str, Any]) -> str:
    agency = detail.get("awarding_agency") or {}
    top = (agency.get("toptier_agency") or {}).get("name")
    sub = (agency.get("subtier_agency") or {}).get("name")
    office = agency.get("office_agency_name")
    values = [
        str(value).strip()
        for value in (top, sub, office)
        if value and str(value).strip()
    ]
    if not values:
        values = [
            str(value).strip()
            for value in (
                summary.get("Awarding Agency"),
                summary.get("Awarding Sub Agency"),
            )
            if value and str(value).strip()
        ]
    deduped: list[str] = []
    for value in values:
        if not deduped or deduped[-1].casefold() != value.casefold():
            deduped.append(value)
    return " / ".join(deduped) or "Office not reported"


def fetch_award_summaries(
    *,
    naics: str,
    states: list[str],
    years_back: int,
    pages_per_state: int,
) -> list[dict[str, Any]]:
    end = date.today()
    start = end - timedelta(days=365 * years_back)
    found: dict[str, dict[str, Any]] = {}
    for state in states:
        for page in range(1, pages_per_state + 1):
            body = {
                "filters": {
                    "award_type_codes": AWARD_TYPE_CODES,
                    "time_period": [
                        {"start_date": start.isoformat(), "end_date": end.isoformat()}
                    ],
                    "naics_codes": [naics],
                    "place_of_performance_locations": [
                        {"country": "USA", "state": state}
                    ],
                },
                "fields": SUMMARY_FIELDS,
                "page": page,
                "limit": 100,
                "sort": "Award Amount",
                "order": "desc",
                "subawards": False,
            }
            payload = _json_request(f"{API_BASE}/search/spending_by_award/", body=body)
            rows = payload.get("results") or []
            for row in rows:
                internal_id = str(row.get("generated_internal_id") or "").strip()
                if internal_id:
                    found[internal_id] = row
            if not (payload.get("page_metadata") or {}).get("hasNext"):
                break
            time.sleep(0.5)
    return list(found.values())


def fetch_award_detail(internal_id: str) -> dict[str, Any]:
    encoded_id = parse.quote(internal_id, safe="")
    return _json_request(f"{API_BASE}/awards/{encoded_id}/")


def build_targets(
    summaries: list[dict[str, Any]],
    *,
    minimum_award_value: float,
    rows: int,
    max_per_office: int,
    workers: int,
) -> list[Target]:
    today = date.today()
    active_summaries = [
        summary
        for summary in summaries
        if _money(summary.get("Award Amount")) >= minimum_award_value
        and (_date_value(summary.get("End Date")) or date.min) >= today
    ]
    details: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(fetch_award_detail, str(summary["generated_internal_id"])): str(
                summary["generated_internal_id"]
            )
            for summary in active_summaries
        }
        for future in as_completed(futures):
            internal_id = futures[future]
            try:
                details[internal_id] = future.result()
            except RuntimeError as exc:
                print(f"warning: {exc}")

    targets: list[Target] = []
    for summary in active_summaries:
        internal_id = str(summary["generated_internal_id"])
        detail = details.get(internal_id)
        if not detail:
            continue
        pop = detail.get("period_of_performance") or {}
        potential_end = _date_value(pop.get("potential_end_date"))
        current_end = _date_value(pop.get("end_date")) or _date_value(summary.get("End Date"))
        pop_end = potential_end or current_end
        if not pop_end or pop_end < today:
            continue
        estimate = _subtract_months(pop_end, 9)
        amount = _money(detail.get("total_obligation"))
        if not amount:
            amount = _money(summary.get("Award Amount"))
        award_id = str(detail.get("piid") or summary.get("Award ID") or "")
        targets.append(
            Target(
                estimated_recompete_date=estimate.isoformat(),
                pop_end_date=pop_end.isoformat(),
                pop_end_basis="potential" if potential_end else "current",
                pop_state=str((detail.get("place_of_performance") or {}).get("state_code") or summary.get("Place of Performance State Code") or ""),
                buying_agency_office=_agency_office(detail, summary),
                recent_award_value=amount,
                incumbent_vendor=str((detail.get("recipient") or {}).get("recipient_name") or summary.get("Recipient Name") or ""),
                award_id=award_id,
                award_url=f"https://www.usaspending.gov/award/{parse.quote(internal_id, safe='')}",
                description=str(detail.get("description") or summary.get("Description") or "").strip(),
            )
        )

    targets.sort(
        key=lambda item: (
            item.estimated_recompete_date,
            item.pop_end_date,
            item.buying_agency_office.casefold(),
            -item.recent_award_value,
        )
    )
    selected: list[Target] = []
    overflow: list[Target] = []
    office_counts: dict[str, int] = {}
    for target in targets:
        office_key = target.buying_agency_office.casefold()
        if office_counts.get(office_key, 0) < max_per_office:
            selected.append(target)
            office_counts[office_key] = office_counts.get(office_key, 0) + 1
        else:
            overflow.append(target)
        if len(selected) >= rows:
            return selected
    selected.extend(overflow[: max(0, rows - len(selected))])
    selected.sort(
        key=lambda item: (
            item.estimated_recompete_date,
            item.pop_end_date,
            item.buying_agency_office.casefold(),
            -item.recent_award_value,
        )
    )
    return selected[:rows]


def fetch_sam_signals(db_path: Path, *, naics: str, states: list[str]) -> list[SamSignal]:
    if not db_path.exists():
        return []
    now = datetime.now().astimezone().isoformat()
    placeholders = ",".join("?" for _ in states)
    sql = f"""
        SELECT title, department, sub_tier, office, type, response_deadline,
               pop_state, link, posted_date
          FROM opportunities
         WHERE naics_code = ?
           AND pop_state IN ({placeholders})
           AND response_deadline >= ?
           AND lower(type) NOT IN ('award notice', 'justification')
         ORDER BY response_deadline ASC, posted_date DESC
    """
    deduped: dict[tuple[str, str, str], SamSignal] = {}
    with sqlite3.connect(db_path) as connection:
        for row in connection.execute(sql, [naics, *states, now]):
            title, department, sub_tier, office, notice_type, deadline, state, link, _ = row
            key = (
                str(title or "").strip().casefold(),
                str(office or "").strip().casefold(),
                str(deadline or "").strip(),
            )
            if key not in deduped:
                office_values = [
                    str(value).strip()
                    for value in (department, sub_tier, office)
                    if value and str(value).strip()
                ]
                deduped[key] = SamSignal(
                    title=str(title or "").strip(),
                    agency_office=" / ".join(office_values),
                    notice_type=str(notice_type or "").strip(),
                    response_deadline=str(deadline or "").strip(),
                    pop_state=str(state or "").strip(),
                    notice_url=str(link or "").strip(),
                )
    return list(deduped.values())


def _last_updated() -> str:
    try:
        payload = _json_request(f"{API_BASE}/awards/last_updated/")
    except RuntimeError:
        return "not retrieved"
    return str(
        payload.get("last_updated")
        or payload.get("last_updated_date")
        or payload.get("date")
        or payload
    )


def write_csv(path: Path, targets: list[Target]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(targets[0]).keys()))
        writer.writeheader()
        for target in targets:
            writer.writerow(asdict(target))


def _escape(value: Any) -> str:
    return (
        str(value or "")
        .replace("\ufffd", "'")
        .replace("|", "\\|")
        .replace("\n", " ")
        .strip()
    )


def _currency(value: float) -> str:
    return f"${value:,.0f}"


def write_markdown(
    path: Path,
    targets: list[Target],
    sam_signals: list[SamSignal],
    *,
    naics: str,
    states: list[str],
    years_back: int,
    summaries_scanned: int,
    minimum_award_value: float,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    lines = [
        "# DMV NAICS 541512 Buyer Target List",
        "",
        f"_Generated: {today}. Profile: `TECHNICAL_SERVICES_PROFILE`. NAICS: `{naics}`. "
        f"Place of performance: `{', '.join(states)}`._",
        "",
        "## Method",
        "",
        f"- USAspending award activity window: last {years_back} years through `{today}`. "
        f"Scanned `{summaries_scanned}` award summaries and retained current awards with "
        f"at least `{_currency(minimum_award_value)}` in obligations.",
        "- `PoP end` uses the potential end date when USAspending reports one; otherwise "
        "it uses the current end date.",
        "- `Est. recompete date` is an inference for pipeline planning: `PoP end - 9 "
        "calendar months`. It is not a government-published solicitation date. Check "
        "SAM.gov, agency forecasts, and incumbent contract modifications before outreach.",
        f"- Estimated planning dates earlier than `{today}` are urgent follow-up signals: "
        "check for an extension, bridge, posted follow-on, or teaming path now.",
        "- USAspending has documented completeness and accuracy gaps. Treat this as a "
        "directional target list and verify individual records before using them in outreach.",
        "- NAICS `541512` is a conditional discovery hint under the active technical-"
        "services profile. These rows are buyer and teaming intelligence, not automatic "
        "small-team prime recommendations.",
        "",
        "## Target Buyers",
        "",
        "| Est. recompete planning date | PoP end | State | Buying agency / office | Recent award value | Incumbent vendor | Award |",
        "| --- | --- | --- | --- | ---: | --- | --- |",
    ]
    for target in targets:
        lines.append(
            "| "
            + " | ".join(
                [
                    _escape(target.estimated_recompete_date),
                    _escape(target.pop_end_date),
                    _escape(target.pop_state),
                    _escape(target.buying_agency_office),
                    _escape(_currency(target.recent_award_value)),
                    _escape(target.incumbent_vendor),
                    f"[{_escape(target.award_id)}]({_escape(target.award_url)})",
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Current SAM.gov Demand Signals",
            "",
            "These are current local-mirror notices under NAICS `541512` with DMV places of "
            "performance and future response deadlines. They are a separate current-demand "
            "check; they are not asserted as follow-ons to the USAspending rows above.",
            "",
            "| Response deadline | State | Notice type | Agency / office | Notice |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for signal in sam_signals[:20]:
        lines.append(
            "| "
            + " | ".join(
                [
                    _escape(signal.response_deadline),
                    _escape(signal.pop_state),
                    _escape(signal.notice_type),
                    _escape(signal.agency_office),
                    f"[{_escape(signal.title)}]({_escape(signal.notice_url)})",
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Sources",
            "",
            "- [USAspending API endpoint index](https://api.usaspending.gov/docs/endpoints)",
            "- [USAspending introductory tutorial](https://api.usaspending.gov/docs/intro-tutorial)",
            "- Award links in the target table resolve to official USAspending award pages.",
            "- SAM.gov notice links in the signal table resolve to official SAM.gov notice pages.",
            f"- USAspending award API last-updated response: `{_escape(_last_updated())}`.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--naics", default="541512")
    parser.add_argument("--states", default=",".join(DEFAULT_STATES))
    parser.add_argument("--years-back", type=int, default=3)
    parser.add_argument("--pages-per-state", type=int, default=3)
    parser.add_argument("--rows", type=int, default=40)
    parser.add_argument("--max-per-office", type=int, default=2)
    parser.add_argument("--minimum-award-value", type=float, default=1_000_000)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--markdown",
        type=Path,
        default=PROJECT_ROOT / "reports" / "dmv-541512-buyer-targets.md",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=PROJECT_ROOT / "reports" / "dmv-541512-buyer-targets.csv",
    )
    parser.add_argument(
        "--sam-db",
        type=Path,
        default=PROJECT_ROOT / "data" / "contracts.db",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    states = [state.strip().upper() for state in args.states.split(",") if state.strip()]
    summaries = fetch_award_summaries(
        naics=args.naics,
        states=states,
        years_back=args.years_back,
        pages_per_state=args.pages_per_state,
    )
    targets = build_targets(
        summaries,
        minimum_award_value=args.minimum_award_value,
        rows=args.rows,
        max_per_office=args.max_per_office,
        workers=args.workers,
    )
    if not targets:
        raise SystemExit("No qualifying USAspending targets found.")
    sam_signals = fetch_sam_signals(args.sam_db, naics=args.naics, states=states)
    write_csv(args.csv, targets)
    write_markdown(
        args.markdown,
        targets,
        sam_signals,
        naics=args.naics,
        states=states,
        years_back=args.years_back,
        summaries_scanned=len(summaries),
        minimum_award_value=args.minimum_award_value,
    )
    print(
        json.dumps(
            {
                "markdown": str(args.markdown),
                "csv": str(args.csv),
                "summaries_scanned": len(summaries),
                "target_rows": len(targets),
                "sam_signals": len(sam_signals),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
