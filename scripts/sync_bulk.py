"""Download SAM.gov daily Contract Opportunities full CSV and load into SQLite.

Runs in ~2 minutes on a 219 MB extract. Idempotent - replaces the DB each run.

Usage:
  python sync_bulk.py             # download + load (default)
  python sync_bulk.py --skip-download   # parse already-downloaded CSV
  python sync_bulk.py --keep-csv        # don't delete CSV after parsing
"""
import argparse
import csv
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

import requests
from panel.store import PanelStore

BULK_URL = "https://falextracts.s3.amazonaws.com/Contract%20Opportunities/datagov/ContractOpportunitiesFullCSV.csv"
SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR.parent / "data"
CSV_PATH = DATA_DIR / "ContractOpportunitiesFullCSV.csv"
DB_PATH = DATA_DIR / "contracts.db"
META_PATH = DATA_DIR / "last_sync.txt"

COLUMN_MAP = [
    ("NoticeId", "notice_id"),
    ("Title", "title"),
    ("Sol#", "sol_number"),
    ("Department/Ind.Agency", "department"),
    ("Sub-Tier", "sub_tier"),
    ("Office", "office"),
    ("PostedDate", "posted_date"),
    ("Type", "type"),
    ("BaseType", "base_type"),
    ("ArchiveDate", "archive_date"),
    ("SetASideCode", "set_aside_code"),
    ("SetASide", "set_aside"),
    ("ResponseDeadLine", "response_deadline"),
    ("NaicsCode", "naics_code"),
    ("ClassificationCode", "classification_code"),
    ("PopStreetAddress", "pop_street"),
    ("PopCity", "pop_city"),
    ("PopState", "pop_state"),
    ("PopZip", "pop_zip"),
    ("PopCountry", "pop_country"),
    ("Active", "active"),
    ("AwardNumber", "award_number"),
    ("AwardDate", "award_date"),
    ("Award$", "award_amount"),
    ("Awardee", "awardee"),
    ("PrimaryContactFullname", "primary_contact_name"),
    ("PrimaryContactEmail", "primary_contact_email"),
    ("OrganizationType", "organization_type"),
    ("Link", "link"),
    ("Description", "description"),
]

DB_COLUMNS = [db for _, db in COLUMN_MAP]


def download_csv():
    print(f"Downloading {BULK_URL}")
    print("Expected size: ~220 MB. This takes ~30-60s on most connections.")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CSV_PATH.with_suffix(".csv.tmp")
    started = time.time()
    bytes_dl = 0
    with requests.get(BULK_URL, stream=True, timeout=(15, 300)) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length", 0))
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                f.write(chunk)
                bytes_dl += len(chunk)
                if total:
                    pct = bytes_dl * 100 // total
                    print(f"\r  {bytes_dl // (1024*1024)} / {total // (1024*1024)} MB ({pct}%)", end="", flush=True)
    print()
    shutil.move(tmp, CSV_PATH)
    elapsed = time.time() - started
    print(f"Downloaded in {elapsed:.1f}s")


def build_db():
    if not CSV_PATH.exists():
        sys.exit(f"CSV not found at {CSV_PATH}. Run without --skip-download.")

    print(f"Parsing CSV into {DB_PATH}")
    panel_snapshot = PanelStore.snapshot_existing(DB_PATH)
    if DB_PATH.exists():
        DB_PATH.unlink()

    started = time.time()
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode = OFF")
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute("PRAGMA temp_store = MEMORY")

    cols_sql = ", ".join(f"{c} TEXT" for c in DB_COLUMNS)
    conn.execute(f"CREATE TABLE opportunities ({cols_sql}, PRIMARY KEY (notice_id))")

    placeholders = ", ".join("?" * len(DB_COLUMNS))
    insert_sql = f"INSERT OR REPLACE INTO opportunities ({', '.join(DB_COLUMNS)}) VALUES ({placeholders})"

    csv_keys = [csv_k for csv_k, _ in COLUMN_MAP]
    batch = []
    row_count = 0

    with open(CSV_PATH, "r", encoding="utf-8-sig", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        missing = [k for k in csv_keys if k not in reader.fieldnames]
        if missing:
            print(f"WARN: CSV missing expected columns: {missing}")
            print(f"Available columns: {reader.fieldnames[:50]}")

        for row in reader:
            values = tuple(row.get(k, "") or "" for k in csv_keys)
            batch.append(values)
            row_count += 1
            if len(batch) >= 5000:
                conn.executemany(insert_sql, batch)
                batch.clear()
                if row_count % 50000 == 0:
                    print(f"  {row_count:,} rows...")
        if batch:
            conn.executemany(insert_sql, batch)

    print(f"Indexing...")
    conn.execute("CREATE INDEX idx_naics ON opportunities(naics_code)")
    conn.execute("CREATE INDEX idx_state ON opportunities(pop_state)")
    conn.execute("CREATE INDEX idx_posted ON opportunities(posted_date)")
    conn.execute("CREATE INDEX idx_active ON opportunities(active)")
    conn.execute("CREATE INDEX idx_setaside ON opportunities(set_aside_code)")
    conn.execute("CREATE INDEX idx_type ON opportunities(type)")
    conn.commit()
    conn.close()
    PanelStore(DB_PATH).restore_snapshot(panel_snapshot)

    elapsed = time.time() - started
    size_mb = DB_PATH.stat().st_size / (1024 * 1024)
    print(f"Loaded {row_count:,} rows in {elapsed:.1f}s")
    print(f"DB size: {size_mb:.1f} MB at {DB_PATH}")

    with open(META_PATH, "w") as f:
        f.write(f"rows={row_count}\n")
        f.write(f"synced_at={time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"source={BULK_URL}\n")


def main():
    p = argparse.ArgumentParser(description="Sync SAM.gov bulk Contract Opportunities to local SQLite.")
    p.add_argument("--skip-download", action="store_true", help="Use existing CSV; skip download")
    p.add_argument("--keep-csv", action="store_true", help="Don't delete CSV after parsing")
    args = p.parse_args()

    if not args.skip_download:
        download_csv()

    build_db()

    if not args.keep_csv and CSV_PATH.exists():
        size_mb = CSV_PATH.stat().st_size / (1024 * 1024)
        CSV_PATH.unlink()
        print(f"Cleaned up CSV ({size_mb:.1f} MB freed). Use --keep-csv to retain.")

    print("\nSync complete. Run search_bulk.py to query.")


if __name__ == "__main__":
    main()
