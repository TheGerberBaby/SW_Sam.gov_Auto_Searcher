"""USAspending.gov client — incumbent and award-history analysis.

The USAspending API is keyless and CORS-friendly. We hit the
`spending_by_award` and `recipient` endpoints for the two
operator-facing questions:

1. "Who has been winning contracts for NAICS X / agency Y?" — used
   to identify incumbents before bidding.
2. "What's the award history of recipient Z?" — used to size up an
   incumbent or a potential teaming partner.

Responses are cached to `data/usaspending_cache.json` with a 24-hour
TTL so repeated queries don't hammer the API. Cache is keyed by the
exact request body.

Caveats (per GAO and per the deep-research report): USAspending has
documented completeness/accuracy gaps. Treat results as directional.

CLI:

    python scripts/usaspending.py incumbents --naics 541512 --limit 10
    python scripts/usaspending.py award-history --recipient "BOOZ ALLEN HAMILTON" --limit 20
    python scripts/usaspending.py recipient "BOOZ ALLEN HAMILTON"
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib import error, request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = PROJECT_ROOT / "data" / "usaspending_cache.json"
DEFAULT_TTL_SECONDS = 24 * 3600

API_BASE = "https://api.usaspending.gov/api/v2"
USER_AGENT = "SW-Contracting-Bots/2.2 (Stormwind Contracting research)"

# Procurement-only "Contract" award_type_codes per USAspending docs
PROCUREMENT_AWARD_TYPES = ["A", "B", "C", "D"]

# Columns we want from spending_by_award. Names must match the API.
AWARD_FIELDS = [
    "Award ID",
    "Recipient Name",
    "Recipient UEI",
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

RECIPIENT_FIELDS = [
    "Recipient Name",
    "Recipient UEI",
    "Recipient DUNS Number",
    "Award Amount",
    "Award Count",
]


# ---------------------------------------------------------------------------
# Errors / dataclasses
# ---------------------------------------------------------------------------


class USAspendingError(RuntimeError):
    """Raised when an API call fails after retries."""


@dataclass
class Award:
    award_id: str
    recipient_name: str
    recipient_uei: str | None
    amount: float | None
    description: str
    contract_type: str | None
    agency: str | None
    sub_agency: str | None
    naics: str | None
    psc: str | None
    start_date: str | None
    end_date: str | None
    pop_state: str | None
    internal_id: str | None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Award":
        return cls(
            award_id=str(row.get("Award ID") or ""),
            recipient_name=str(row.get("Recipient Name") or ""),
            recipient_uei=row.get("Recipient UEI"),
            amount=_to_float(row.get("Award Amount")),
            description=str(row.get("Description") or "")[:500],
            contract_type=row.get("Contract Award Type"),
            agency=row.get("Awarding Agency"),
            sub_agency=row.get("Awarding Sub Agency"),
            naics=_flatten_code(row.get("NAICS")),
            psc=_flatten_code(row.get("PSC")),
            start_date=row.get("Start Date"),
            end_date=row.get("End Date"),
            pop_state=row.get("Place of Performance State Code"),
            internal_id=row.get("generated_internal_id"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Recipient:
    name: str
    uei: str | None
    total_award_amount: float | None
    award_count: int | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def _load_cache() -> dict[str, Any]:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(data: dict[str, Any]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def _cache_key(path: str, body: dict[str, Any]) -> str:
    payload = json.dumps({"path": path, "body": body}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# HTTP client (stdlib only)
# ---------------------------------------------------------------------------


def _post(
    path: str,
    body: dict[str, Any],
    *,
    timeout: int = 30,
    cache_ttl: int = DEFAULT_TTL_SECONDS,
    cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = f"{API_BASE}{path}"
    cache = cache if cache is not None else _load_cache()
    key = _cache_key(path, body)
    entry = cache.get(key)
    if entry and (time.time() - entry["fetched_at"]) < cache_ttl:
        return entry["data"]

    data_bytes = json.dumps(body).encode("utf-8")
    req = request.Request(
        url,
        data=data_bytes,
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        msg = exc.read().decode("utf-8", errors="replace")[:300] if exc.fp else str(exc)
        raise USAspendingError(f"USAspending {exc.code}: {msg}") from exc
    except error.URLError as exc:
        raise USAspendingError(f"USAspending network error: {exc.reason}") from exc

    cache[key] = {"fetched_at": time.time(), "data": payload}
    _save_cache(cache)
    return payload


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _flatten_code(value: Any) -> str | None:
    """USAspending sometimes returns {code, description} dicts for NAICS/PSC."""
    if value is None:
        return None
    if isinstance(value, dict):
        code = value.get("code")
        desc = value.get("description")
        if code and desc:
            return f"{code} ({desc})"
        return str(code or desc or "")
    return str(value)


def _default_time_period(years_back: int = 3) -> list[dict[str, str]]:
    end = date.today()
    start = end - timedelta(days=365 * years_back)
    return [{"start_date": start.isoformat(), "end_date": end.isoformat()}]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def find_incumbents(
    naics: str | None = None,
    agency: str | None = None,
    keyword: str | None = None,
    pop_state: str | None = None,
    years_back: int = 3,
    limit: int = 20,
) -> list[Award]:
    """Return recent procurement awards matching the filter — these are the
    incumbents you'd be running against on a similar future opportunity.
    """
    filters: dict[str, Any] = {
        "award_type_codes": PROCUREMENT_AWARD_TYPES,
        "time_period": _default_time_period(years_back=years_back),
    }
    if naics:
        filters["naics_codes"] = [naics]
    if agency:
        filters["agencies"] = [{"type": "awarding", "tier": "toptier", "name": agency}]
    if keyword:
        filters["keywords"] = [keyword]
    if pop_state:
        filters["place_of_performance_locations"] = [
            {"country": "USA", "state": pop_state.upper()}
        ]

    body = {
        "filters": filters,
        "fields": AWARD_FIELDS,
        "page": 1,
        "limit": max(1, min(limit, 100)),
        "sort": "Award Amount",
        "order": "desc",
        "subawards": False,
    }
    payload = _post("/search/spending_by_award/", body)
    rows = payload.get("results") or []
    return [Award.from_row(row) for row in rows]


def award_history(
    recipient_name: str | None = None,
    recipient_uei: str | None = None,
    naics: str | None = None,
    agency: str | None = None,
    years_back: int = 5,
    limit: int = 30,
) -> list[Award]:
    """Award history for a specific recipient (or a recipient + NAICS / agency
    cut). Used to evaluate an incumbent or a potential teaming partner.
    """
    if not (recipient_name or recipient_uei):
        raise ValueError("specify recipient_name or recipient_uei")
    filters: dict[str, Any] = {
        "award_type_codes": PROCUREMENT_AWARD_TYPES,
        "time_period": _default_time_period(years_back=years_back),
    }
    if recipient_name:
        filters["recipient_search_text"] = [recipient_name]
    if recipient_uei:
        filters["recipient_id"] = recipient_uei
    if naics:
        filters["naics_codes"] = [naics]
    if agency:
        filters["agencies"] = [{"type": "awarding", "tier": "toptier", "name": agency}]

    body = {
        "filters": filters,
        "fields": AWARD_FIELDS,
        "page": 1,
        "limit": max(1, min(limit, 100)),
        "sort": "Award Amount",
        "order": "desc",
        "subawards": False,
    }
    payload = _post("/search/spending_by_award/", body)
    rows = payload.get("results") or []
    return [Award.from_row(row) for row in rows]


def top_recipients_by_naics(
    naics: str,
    years_back: int = 3,
    limit: int = 10,
) -> list[Recipient]:
    """Top recipients (by dollars) for a NAICS code over the window."""
    body = {
        "category": "recipient",
        "filters": {
            "award_type_codes": PROCUREMENT_AWARD_TYPES,
            "time_period": _default_time_period(years_back=years_back),
            "naics_codes": [naics],
        },
        "limit": max(1, min(limit, 100)),
        "page": 1,
    }
    payload = _post("/search/spending_by_category/", body)
    rows = payload.get("results") or []
    return [
        Recipient(
            name=str(row.get("name") or ""),
            uei=row.get("recipient_id"),
            total_award_amount=_to_float(row.get("amount")),
            award_count=row.get("code") if isinstance(row.get("code"), int) else None,
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_awards(awards: list[Award]) -> None:
    if not awards:
        print("(no awards found)")
        return
    for i, award in enumerate(awards, 1):
        amount = f"${award.amount:,.0f}" if award.amount else "-"
        print(f"\n[{i}] {amount}  {award.recipient_name}")
        print(f"    Award:    {award.award_id}")
        print(f"    Agency:   {award.agency or '-'} / {award.sub_agency or '-'}")
        print(f"    NAICS:    {award.naics or '-'}    PSC: {award.psc or '-'}")
        print(f"    Period:   {award.start_date or '-'} -> {award.end_date or '-'}")
        print(f"    PoP:      {award.pop_state or '-'}")
        if award.description:
            print(f"    Desc:     {award.description[:140]}")


def _print_recipients(recipients: list[Recipient]) -> None:
    if not recipients:
        print("(no recipients found)")
        return
    for i, r in enumerate(recipients, 1):
        amount = f"${r.total_award_amount:,.0f}" if r.total_award_amount else "-"
        print(f"  [{i:>2}] {amount:<16}  {r.name}")


def _cli() -> None:
    parser = argparse.ArgumentParser(description="USAspending.gov client — incumbent + award-history analysis.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_inc = sub.add_parser("incumbents", help="Recent recipients matching NAICS/agency/keyword filters.")
    p_inc.add_argument("--naics")
    p_inc.add_argument("--agency")
    p_inc.add_argument("--keyword")
    p_inc.add_argument("--state", dest="pop_state")
    p_inc.add_argument("--years-back", dest="years_back", type=int, default=3)
    p_inc.add_argument("--limit", type=int, default=20)
    p_inc.add_argument("--json", action="store_true")

    p_hist = sub.add_parser("award-history", help="Award history for a specific recipient.")
    p_hist.add_argument("--recipient")
    p_hist.add_argument("--uei")
    p_hist.add_argument("--naics")
    p_hist.add_argument("--agency")
    p_hist.add_argument("--years-back", dest="years_back", type=int, default=5)
    p_hist.add_argument("--limit", type=int, default=30)
    p_hist.add_argument("--json", action="store_true")

    p_top = sub.add_parser("top-recipients", help="Top recipients by NAICS over the window.")
    p_top.add_argument("--naics", required=True)
    p_top.add_argument("--years-back", dest="years_back", type=int, default=3)
    p_top.add_argument("--limit", type=int, default=10)
    p_top.add_argument("--json", action="store_true")

    args = parser.parse_args()

    if args.cmd == "incumbents":
        awards = find_incumbents(
            naics=args.naics, agency=args.agency, keyword=args.keyword,
            pop_state=args.pop_state, years_back=args.years_back, limit=args.limit,
        )
        if args.json:
            print(json.dumps([a.to_dict() for a in awards], indent=2, default=str))
        else:
            _print_awards(awards)
    elif args.cmd == "award-history":
        if not (args.recipient or args.uei):
            raise SystemExit("specify --recipient or --uei")
        awards = award_history(
            recipient_name=args.recipient, recipient_uei=args.uei,
            naics=args.naics, agency=args.agency,
            years_back=args.years_back, limit=args.limit,
        )
        if args.json:
            print(json.dumps([a.to_dict() for a in awards], indent=2, default=str))
        else:
            _print_awards(awards)
    elif args.cmd == "top-recipients":
        recipients = top_recipients_by_naics(
            naics=args.naics, years_back=args.years_back, limit=args.limit,
        )
        if args.json:
            print(json.dumps([r.to_dict() for r in recipients], indent=2, default=str))
        else:
            _print_recipients(recipients)


if __name__ == "__main__":
    _cli()
