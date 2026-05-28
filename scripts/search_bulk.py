"""Fast local search against the SAM.gov bulk SQLite DB.

Same flag surface as find_contracts.py but queries local data (no API call).
Returns in milliseconds.

Examples:
  python search_bulk.py "Elasticsearch" --active-only
  python search_bulk.py "observability" --naics 541512 --active-only
  python search_bulk.py "SIEM" --limit 50 --json
"""
import argparse
import json
import sqlite3
import sys
from datetime import date, datetime, timedelta

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR.parent / "data" / "contracts.db"
META_PATH = SCRIPT_DIR.parent / "data" / "last_sync.txt"


def parse_args():
    p = argparse.ArgumentParser(description="Search the local SAM.gov bulk DB.")
    p.add_argument("keyword", nargs="?", help="Free-text search in title + description")
    p.add_argument("--naics", help="NAICS code (exact or prefix, e.g. 54151 matches 541511, 541512, ...)")
    p.add_argument("--state", help="2-letter state code (place of performance)")
    p.add_argument("--set-aside", dest="set_aside", help="Set-aside code (SBA, 8A, WOSB, SDVOSBC, HZC, IEE, ...)")
    p.add_argument("--type", dest="type_filter", help="Notice type (Solicitation, Presolicitation, Sources Sought, etc.)")
    p.add_argument("--days", type=int, default=30, help="Posted within last N days (default: 30, 0 = no limit)")
    p.add_argument("--active-only", action="store_true", help="Only show currently active opportunities")
    p.add_argument("--limit", type=int, default=20, help="Max results (default: 20)")
    p.add_argument("--json", action="store_true", help="JSON output")
    return p.parse_args()


def load_meta():
    if not META_PATH.exists():
        return None
    return META_PATH.read_text(encoding="utf-8")


def main():
    if not DB_PATH.exists():
        sys.exit(f"DB not found at {DB_PATH}. Run sync_bulk.py first.")

    args = parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    where = []
    params = []

    if args.keyword:
        where.append("(title LIKE ? OR description LIKE ?)")
        params.extend([f"%{args.keyword}%", f"%{args.keyword}%"])

    if args.naics:
        where.append("naics_code LIKE ?")
        params.append(f"{args.naics}%")

    if args.state:
        where.append("UPPER(pop_state) = ?")
        params.append(args.state.upper())

    if args.set_aside:
        where.append("UPPER(set_aside_code) = ?")
        params.append(args.set_aside.upper())

    if args.type_filter:
        where.append("type LIKE ?")
        params.append(f"%{args.type_filter}%")

    if args.active_only:
        where.append("active = 'Yes'")

    if args.days > 0:
        cutoff = (date.today() - timedelta(days=args.days)).isoformat()
        where.append("posted_date >= ?")
        params.append(cutoff)

    where_sql = " AND ".join(where) if where else "1=1"

    count_sql = f"SELECT COUNT(*) FROM opportunities WHERE {where_sql}"
    total = conn.execute(count_sql, params).fetchone()[0]

    sql = f"""
        SELECT notice_id, title, sol_number, department, sub_tier, posted_date,
               type, set_aside, response_deadline, naics_code, pop_city, pop_state,
               active, link, description
        FROM opportunities
        WHERE {where_sql}
        ORDER BY posted_date DESC
        LIMIT ?
    """
    rows = conn.execute(sql, params + [args.limit]).fetchall()

    if args.json:
        out = {
            "total": total,
            "shown": len(rows),
            "filters": {
                "keyword": args.keyword,
                "naics": args.naics,
                "state": args.state,
                "set_aside": args.set_aside,
                "type": args.type_filter,
                "days": args.days,
                "active_only": args.active_only,
            },
            "opportunities": [dict(r) for r in rows],
        }
        print(json.dumps(out, indent=2, default=str))
        return

    meta = load_meta() or ""
    sync_line = next((l for l in meta.splitlines() if l.startswith("synced_at=")), "synced_at=unknown")
    print(f"\nLocal SAM.gov DB ({sync_line.split('=', 1)[1]})")
    filters = []
    if args.keyword:
        filters.append(f'kw="{args.keyword}"')
    if args.naics:
        filters.append(f"naics={args.naics}")
    if args.state:
        filters.append(f"state={args.state.upper()}")
    if args.set_aside:
        filters.append(f"set-aside={args.set_aside.upper()}")
    if args.type_filter:
        filters.append(f"type={args.type_filter}")
    if args.active_only:
        filters.append("active=Yes")
    if args.days > 0:
        filters.append(f"last {args.days}d")
    print(f"Filters: {', '.join(filters) if filters else '(none)'}")
    print(f"Total matching: {total:,}   Showing: {len(rows)}")
    print("=" * 80)

    if not rows:
        print("\nNo matches. Try widening --days, dropping a filter, or removing --active-only.\n")
        return

    for i, r in enumerate(rows, 1):
        loc = ", ".join(p for p in [r["pop_city"], r["pop_state"]] if p) or "-"
        print(f"\n[{i}] {r['title'] or '(no title)'}")
        print(f"    Agency:   {r['department'] or '-'} / {r['sub_tier'] or '-'}")
        print(f"    Type:     {r['type'] or '-'}    Active: {r['active'] or '-'}")
        print(f"    NAICS:    {r['naics_code'] or '-'}    Set-aside: {r['set_aside'] or '-'}")
        print(f"    Location: {loc}")
        print(f"    Posted:   {r['posted_date'] or '-'}    Response due: {r['response_deadline'] or '-'}")
        print(f"    Sol #:    {r['sol_number'] or '-'}")
        print(f"    Link:     {r['link'] or '-'}")

    print()


if __name__ == "__main__":
    main()
