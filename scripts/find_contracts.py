"""Find federal contract opportunities via SAM.gov.

Loads SAM_API_KEY from the project `.env` file.

Examples:
  python find_contracts.py "Elasticsearch" --days 30
  python find_contracts.py "observability" --naics 541512
  python find_contracts.py "SIEM" --limit 50 --json
"""
import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

API_URL = "https://api.sam.gov/opportunities/v2/search"

SET_ASIDE_CODES = {
    "SBA": "Total Small Business",
    "SBP": "Partial Small Business",
    "8A": "8(a) Set-Aside",
    "8AN": "8(a) Sole Source",
    "WOSB": "Women-Owned Small Business",
    "EDWOSB": "Economically Disadvantaged WOSB",
    "SDVOSBC": "Service-Disabled Veteran-Owned SB",
    "HZC": "HUBZone Set-Aside",
    "HZS": "HUBZone Sole Source",
    "IEE": "Indian Economic Enterprise",
    "ISBEE": "Indian Small Business Economic Enterprise",
}


def parse_args():
    p = argparse.ArgumentParser(
        description="Search SAM.gov for federal contract opportunities.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Common set-aside codes:\n  " + "\n  ".join(f"{k:8} {v}" for k, v in SET_ASIDE_CODES.items()),
    )
    p.add_argument("keyword", nargs="?", help="Free-text title search (e.g. 'Elasticsearch')")
    p.add_argument("--naics", help="NAICS code (e.g. 541512 for systems design)")
    p.add_argument("--state", help="2-letter state code (place of performance)")
    p.add_argument("--set-aside", dest="set_aside", help="Set-aside code (see list below)")
    p.add_argument("--ptype", default="o,k,p", help="Procurement type codes (default: o,k,p)")
    p.add_argument("--days", type=int, default=14, help="Look back N days (default: 14)")
    p.add_argument("--limit", type=int, default=20, help="Max results (default: 20, cap 1000)")
    p.add_argument("--json", action="store_true", help="Output JSON instead of formatted text")
    return p.parse_args()


def fmt(value, default="-"):
    return value if value else default


def main():
    script_dir = Path(__file__).resolve().parent
    skill_root = script_dir.parent
    for env_path in [skill_root / ".env", script_dir / ".env"]:
        if env_path.exists():
            load_dotenv(env_path)
            break
    else:
        load_dotenv()

    api_key = os.getenv("SAM_API_KEY")
    if not api_key:
        sys.exit(f"ERROR: SAM_API_KEY not set. Add it to {skill_root / '.env'}")

    args = parse_args()

    posted_to = date.today()
    posted_from = posted_to - timedelta(days=args.days)

    params = {
        "api_key": api_key,
        "limit": min(args.limit, 1000),
        "offset": 0,
        "postedFrom": posted_from.strftime("%m/%d/%Y"),
        "postedTo": posted_to.strftime("%m/%d/%Y"),
        "ptype": args.ptype,
    }
    if args.keyword:
        params["title"] = args.keyword
    if args.naics:
        params["ncode"] = args.naics
    if args.state:
        params["state"] = args.state.upper()
    if args.set_aside:
        params["typeOfSetAside"] = args.set_aside.upper()

    try:
        r = requests.get(API_URL, params=params, timeout=(10, 120))
    except requests.Timeout:
        sys.exit("SAM.gov is slow or unresponsive (>120s). Try again in a few minutes — this is a SAM-side issue, not the skill.")
    except requests.RequestException as e:
        sys.exit(f"Network error: {e}")

    if r.status_code in (401, 403):
        sys.exit(f"Auth error ({r.status_code}): check SAM_API_KEY. Response: {r.text[:300]}")
    if r.status_code == 429:
        sys.exit("Rate limited by SAM.gov. Wait and retry.")
    if r.status_code != 200:
        sys.exit(f"API error {r.status_code}: {r.text[:500]}")

    data = r.json()
    total = data.get("totalRecords", 0)
    opps = data.get("opportunitiesData", [])

    if args.json:
        out = {
            "total": total,
            "shown": len(opps),
            "postedFrom": posted_from.isoformat(),
            "postedTo": posted_to.isoformat(),
            "filters": {
                "keyword": args.keyword,
                "naics": args.naics,
                "state": args.state.upper() if args.state else None,
                "set_aside": args.set_aside.upper() if args.set_aside else None,
            },
            "opportunities": opps,
        }
        print(json.dumps(out, indent=2, default=str))
        return

    filters = []
    if args.keyword:
        filters.append(f'title~"{args.keyword}"')
    if args.naics:
        filters.append(f"naics={args.naics}")
    if args.state:
        filters.append(f"state={args.state.upper()}")
    if args.set_aside:
        filters.append(f"set-aside={args.set_aside.upper()}")
    filter_str = ", ".join(filters) if filters else "(no filters)"

    print(f"\nSAM.gov search: {filter_str}")
    print(f"Posted {posted_from} -> {posted_to}")
    print(f"Total matching: {total}   Showing: {len(opps)}")
    print("=" * 80)

    if not opps:
        print("\nNo opportunities found. Try widening --days or dropping a filter.\n")
        return

    for i, o in enumerate(opps, 1):
        title = fmt(o.get("title"), "(no title)")
        sol = fmt(o.get("solicitationNumber"))
        agency = fmt(o.get("fullParentPathName") or o.get("department"))
        naics = fmt(o.get("naicsCode"))
        set_aside = fmt(o.get("typeOfSetAsideDescription"))
        posted = fmt(o.get("postedDate"))
        deadline = fmt(o.get("responseDeadLine"))
        place = o.get("placeOfPerformance") or {}
        city = (place.get("city") or {}).get("name", "") if isinstance(place.get("city"), dict) else ""
        st = (place.get("state") or {}).get("code", "") if isinstance(place.get("state"), dict) else ""
        loc = ", ".join(p for p in [city, st] if p) or "-"
        url = fmt(o.get("uiLink"))

        print(f"\n[{i}] {title}")
        print(f"    Agency:   {agency}")
        print(f"    NAICS:    {naics}    Set-aside: {set_aside}")
        print(f"    Location: {loc}")
        print(f"    Posted:   {posted}    Response due: {deadline}")
        print(f"    Sol #:    {sol}")
        print(f"    Link:     {url}")

    print()


if __name__ == "__main__":
    main()
