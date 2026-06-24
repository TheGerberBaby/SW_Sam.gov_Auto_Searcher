"""Local SQLite-backed watchlist and saved-search storage.

A separate `data/watchlist.db` keeps the operator's tracking state out of
`contracts.db`, which is replaced on every sync.

Tables:
  watchlist           — opportunities Jeremy is actively pursuing
  watchlist_events    — append-only timeline of status changes / notes
  saved_searches      — named, repeatable search-filter sets
  digest_runs         — persisted dashboard scans from digests and AI research

This module is import-safe (no side effects on import). Callers receive a
`Store` instance and explicitly call methods.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("America/New_York")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = PROJECT_ROOT / "data" / "watchlist.db"
VALID_ENVS = {"prod", "dev"}

VALID_STATUSES = {
    "tracking",     # newly added, monitoring
    "assessing",    # actively reviewing fit and feasibility
    "pursuing",     # writing or finalising a response
    "submitted",    # bid submitted, awaiting decision
    "won",
    "lost",
    "withdrawn",
    "expired",
}


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS watchlist (
    notice_id           TEXT PRIMARY KEY,
    title               TEXT NOT NULL,
    sol_number          TEXT,
    department          TEXT,
    naics_code          TEXT,
    set_aside           TEXT,
    response_deadline   TEXT,
    link                TEXT,
    status              TEXT NOT NULL DEFAULT 'tracking',
    score               INTEGER,
    band                TEXT,
    human_score         INTEGER,
    lanes               TEXT,            -- JSON array
    notes               TEXT,
    added_at            TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_watchlist_status ON watchlist(status);
CREATE INDEX IF NOT EXISTS idx_watchlist_deadline ON watchlist(response_deadline);

CREATE TABLE IF NOT EXISTS watchlist_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    notice_id       TEXT NOT NULL,
    event_type      TEXT NOT NULL,       -- added/status_changed/note/scored
    detail          TEXT,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (notice_id) REFERENCES watchlist(notice_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_events_notice ON watchlist_events(notice_id);

CREATE TABLE IF NOT EXISTS saved_searches (
    name            TEXT PRIMARY KEY,
    description     TEXT,
    filters         TEXT NOT NULL,       -- JSON-serialized filter dict
    profile         TEXT NOT NULL DEFAULT 'technical_services',
    min_score       INTEGER NOT NULL DEFAULT 2,
    created_at      TEXT NOT NULL,
    last_run_at     TEXT
);

CREATE TABLE IF NOT EXISTS digest_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at          TEXT NOT NULL,
    profile         TEXT NOT NULL,
    source          TEXT NOT NULL DEFAULT 'digest',
    candidates_scanned INTEGER NOT NULL,
    candidates_shown   INTEGER NOT NULL,
    report_path     TEXT,
    summary         TEXT,
    items_json      TEXT
);
"""


# ---------------------------------------------------------------------------
# Dataclasses for return values
# ---------------------------------------------------------------------------


@dataclass
class WatchlistEntry:
    notice_id: str
    title: str
    sol_number: str | None
    department: str | None
    naics_code: str | None
    set_aside: str | None
    response_deadline: str | None
    link: str | None
    status: str
    score: int | None
    band: str | None
    human_score: int | None
    lanes: list[str]
    notes: str | None
    added_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "notice_id": self.notice_id,
            "title": self.title,
            "sol_number": self.sol_number,
            "department": self.department,
            "naics_code": self.naics_code,
            "set_aside": self.set_aside,
            "response_deadline": self.response_deadline,
            "link": self.link,
            "status": self.status,
            "score": self.score,
            "band": self.band,
            "human_score": self.human_score,
            "lanes": self.lanes,
            "notes": self.notes,
            "added_at": self.added_at,
            "updated_at": self.updated_at,
        }


@dataclass
class SavedSearch:
    name: str
    description: str | None
    filters: dict[str, Any]
    profile: str
    min_score: int
    created_at: str
    last_run_at: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "filters": self.filters,
            "profile": self.profile,
            "min_score": self.min_score,
            "created_at": self.created_at,
            "last_run_at": self.last_run_at,
        }


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(LOCAL_TZ).isoformat(timespec="seconds")


def normalize_runtime_env(env: str | None = None) -> str:
    value = (env or os.environ.get("SWCB_ENV") or "prod").strip().lower()
    if value not in VALID_ENVS:
        raise ValueError(f"Invalid runtime env {value!r}. Valid: {sorted(VALID_ENVS)}")
    return value


def db_path_for_env(env: str | None = None) -> Path:
    runtime_env = normalize_runtime_env(env)
    if runtime_env == "prod":
        return DEFAULT_DB
    return PROJECT_ROOT / "data" / runtime_env / "watchlist.db"


class Store:
    """Wrapper around the watchlist SQLite database."""

    def __init__(self, db_path: Path | str | None = None, env: str | None = None) -> None:
        self.env = normalize_runtime_env(env) if db_path is None else None
        self.db_path = Path(db_path) if db_path else db_path_for_env(self.env)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            self._migrate(conn)
            conn.executescript(SCHEMA)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        """Apply small additive migrations for existing local databases."""
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'watchlist'"
        ).fetchall()
        if not tables:
            return
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(watchlist)").fetchall()}
        if "human_score" not in cols:
            conn.execute("ALTER TABLE watchlist ADD COLUMN human_score INTEGER")
        digest_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'digest_runs'"
        ).fetchall()
        if digest_table:
            dcols = {row["name"] for row in conn.execute("PRAGMA table_info(digest_runs)").fetchall()}
            if "items_json" not in dcols:
                conn.execute("ALTER TABLE digest_runs ADD COLUMN items_json TEXT")
            if "source" not in dcols:
                conn.execute("ALTER TABLE digest_runs ADD COLUMN source TEXT NOT NULL DEFAULT 'digest'")

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # -------- watchlist --------

    def add_to_watchlist(
        self,
        opportunity: dict[str, Any],
        status: str = "tracking",
        notes: str | None = None,
        score: int | None = None,
        band: str | None = None,
        lanes: list[str] | None = None,
    ) -> WatchlistEntry:
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid status {status!r}. Valid: {sorted(VALID_STATUSES)}")
        notice_id = opportunity.get("notice_id")
        if not notice_id:
            raise ValueError("opportunity must include notice_id")
        now = _now()
        lanes_json = json.dumps(lanes or [])
        with self._conn() as conn:
            existing = conn.execute(
                "SELECT notice_id FROM watchlist WHERE notice_id = ?",
                (notice_id,),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE watchlist
                       SET status = ?, notes = COALESCE(?, notes),
                           score = COALESCE(?, score),
                           band = COALESCE(?, band),
                           lanes = ?, updated_at = ?
                     WHERE notice_id = ?
                    """,
                    (status, notes, score, band, lanes_json, now, notice_id),
                )
                conn.execute(
                    "INSERT INTO watchlist_events (notice_id, event_type, detail, created_at) VALUES (?, ?, ?, ?)",
                    (notice_id, "status_changed", f"-> {status}", now),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO watchlist
                        (notice_id, title, sol_number, department, naics_code,
                         set_aside, response_deadline, link, status, score, band,
                         lanes, notes, added_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        notice_id,
                        opportunity.get("title") or "",
                        opportunity.get("sol_number"),
                        opportunity.get("department"),
                        opportunity.get("naics_code"),
                        opportunity.get("set_aside"),
                        opportunity.get("response_deadline"),
                        opportunity.get("link"),
                        status,
                        score,
                        band,
                        lanes_json,
                        notes,
                        now,
                        now,
                    ),
                )
                conn.execute(
                    "INSERT INTO watchlist_events (notice_id, event_type, detail, created_at) VALUES (?, ?, ?, ?)",
                    (notice_id, "added", f"status={status}", now),
                )
            row = conn.execute(
                "SELECT * FROM watchlist WHERE notice_id = ?", (notice_id,)
            ).fetchone()
        return _row_to_entry(row)

    def remove_from_watchlist(self, notice_id: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM watchlist WHERE notice_id = ?", (notice_id,))
            return cur.rowcount > 0

    def update_status(self, notice_id: str, status: str, note: str | None = None) -> WatchlistEntry | None:
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid status {status!r}")
        now = _now()
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE watchlist SET status = ?, updated_at = ? WHERE notice_id = ?",
                (status, now, notice_id),
            )
            if cur.rowcount == 0:
                return None
            conn.execute(
                "INSERT INTO watchlist_events (notice_id, event_type, detail, created_at) VALUES (?, ?, ?, ?)",
                (notice_id, "status_changed", note or f"-> {status}", now),
            )
            row = conn.execute("SELECT * FROM watchlist WHERE notice_id = ?", (notice_id,)).fetchone()
        return _row_to_entry(row)

    def add_note(self, notice_id: str, note: str) -> None:
        if not note.strip():
            return
        now = _now()
        with self._conn() as conn:
            conn.execute(
                "UPDATE watchlist SET notes = COALESCE(notes || char(10), '') || ?, updated_at = ? WHERE notice_id = ?",
                (f"[{now}] {note}", now, notice_id),
            )
            conn.execute(
                "INSERT INTO watchlist_events (notice_id, event_type, detail, created_at) VALUES (?, ?, ?, ?)",
                (notice_id, "note", note, now),
            )

    def set_human_score(self, notice_id: str, human_score: int | None, note: str | None = None) -> WatchlistEntry | None:
        if human_score is not None and not 1 <= human_score <= 5:
            raise ValueError("human_score must be between 1 and 5")
        now = _now()
        detail = f"human_score={human_score}" if human_score is not None else "human_score cleared"
        if note:
            detail += f"; {note}"
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE watchlist SET human_score = ?, updated_at = ? WHERE notice_id = ?",
                (human_score, now, notice_id),
            )
            if cur.rowcount == 0:
                return None
            conn.execute(
                "INSERT INTO watchlist_events (notice_id, event_type, detail, created_at) VALUES (?, ?, ?, ?)",
                (notice_id, "human_scored", detail, now),
            )
            row = conn.execute("SELECT * FROM watchlist WHERE notice_id = ?", (notice_id,)).fetchone()
        return _row_to_entry(row)

    def list_watchlist(
        self,
        status: str | None = None,
        limit: int = 100,
    ) -> list[WatchlistEntry]:
        sql = "SELECT * FROM watchlist"
        params: list[Any] = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY response_deadline IS NULL, response_deadline ASC, added_at DESC LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_entry(row) for row in rows]

    def get_entry(self, notice_id: str) -> WatchlistEntry | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM watchlist WHERE notice_id = ?", (notice_id,)).fetchone()
        return _row_to_entry(row) if row else None

    def events(self, notice_id: str) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, event_type, detail, created_at FROM watchlist_events WHERE notice_id = ? ORDER BY id DESC",
                (notice_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    # -------- saved searches --------

    def save_search(
        self,
        name: str,
        filters: dict[str, Any],
        description: str | None = None,
        profile: str = "technical_services",
        min_score: int = 2,
    ) -> SavedSearch:
        if not name.strip():
            raise ValueError("search name must be non-empty")
        now = _now()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO saved_searches (name, description, filters, profile, min_score, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    description = excluded.description,
                    filters = excluded.filters,
                    profile = excluded.profile,
                    min_score = excluded.min_score
                """,
                (name, description, json.dumps(filters), profile, min_score, now),
            )
            row = conn.execute("SELECT * FROM saved_searches WHERE name = ?", (name,)).fetchone()
        return _row_to_saved_search(row)

    def get_saved_search(self, name: str) -> SavedSearch | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM saved_searches WHERE name = ?", (name,)).fetchone()
        return _row_to_saved_search(row) if row else None

    def list_saved_searches(self) -> list[SavedSearch]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM saved_searches ORDER BY name").fetchall()
        return [_row_to_saved_search(row) for row in rows]

    def delete_saved_search(self, name: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM saved_searches WHERE name = ?", (name,))
            return cur.rowcount > 0

    def mark_search_run(self, name: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE saved_searches SET last_run_at = ? WHERE name = ?",
                (_now(), name),
            )

    # -------- digest runs --------

    def record_digest_run(
        self,
        profile: str,
        candidates_scanned: int,
        candidates_shown: int,
        report_path: str | None = None,
        summary: str | None = None,
        items_json: str | None = None,
        source: str = "digest",
    ) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO digest_runs
                    (run_at, profile, source, candidates_scanned, candidates_shown, report_path, summary, items_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (_now(), profile, source, candidates_scanned, candidates_shown, report_path, summary, items_json),
            )
            return cur.lastrowid

    def publish_research_scan(
        self,
        summary: str,
        items: list[dict[str, Any]],
        profile: str = "technical_services",
        candidates_scanned: int = 0,
    ) -> int:
        """Persist one curated AI research result set for the Workbench."""
        if not summary.strip():
            raise ValueError("summary must be non-empty")
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("each research-scan item must be an object")
            if not str(item.get("notice_id") or "").strip():
                raise ValueError("each research-scan item must include notice_id")
            if not str(item.get("title") or "").strip():
                raise ValueError("each research-scan item must include title")
        return self.record_digest_run(
            profile=profile,
            source="ai_research",
            candidates_scanned=max(candidates_scanned, len(items)),
            candidates_shown=len(items),
            summary=summary,
            items_json=json.dumps(items),
        )

    def list_digest_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, run_at, profile, source, candidates_scanned, candidates_shown, "
                "report_path, summary FROM digest_runs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def get_digest_run(self, run_id: int) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM digest_runs WHERE id = ?", (run_id,)
            ).fetchone()
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# Row helpers
# ---------------------------------------------------------------------------


def _row_to_entry(row: sqlite3.Row | None) -> WatchlistEntry:
    if row is None:
        raise ValueError("no row")
    lanes = json.loads(row["lanes"] or "[]")
    return WatchlistEntry(
        notice_id=row["notice_id"],
        title=row["title"],
        sol_number=row["sol_number"],
        department=row["department"],
        naics_code=row["naics_code"],
        set_aside=row["set_aside"],
        response_deadline=row["response_deadline"],
        link=row["link"],
        status=row["status"],
        score=row["score"],
        band=row["band"],
        human_score=row["human_score"],
        lanes=lanes,
        notes=row["notes"],
        added_at=row["added_at"],
        updated_at=row["updated_at"],
    )


def _row_to_saved_search(row: sqlite3.Row) -> SavedSearch:
    return SavedSearch(
        name=row["name"],
        description=row["description"],
        filters=json.loads(row["filters"]),
        profile=row["profile"],
        min_score=row["min_score"],
        created_at=row["created_at"],
        last_run_at=row["last_run_at"],
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Manage the local watchlist and saved searches.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add", help="Add a notice to the watchlist")
    p_add.add_argument("notice_id")
    p_add.add_argument("--title", required=True)
    p_add.add_argument("--status", default="tracking", choices=sorted(VALID_STATUSES))
    p_add.add_argument("--notes")
    p_add.add_argument("--score", type=int)

    p_list = sub.add_parser("list", help="List watchlist entries")
    p_list.add_argument("--status")
    p_list.add_argument("--limit", type=int, default=50)

    p_status = sub.add_parser("status", help="Update status on a watchlist entry")
    p_status.add_argument("notice_id")
    p_status.add_argument("new_status", choices=sorted(VALID_STATUSES))
    p_status.add_argument("--note")

    p_note = sub.add_parser("note", help="Append a note to a watchlist entry")
    p_note.add_argument("notice_id")
    p_note.add_argument("text")

    p_rm = sub.add_parser("remove", help="Remove a watchlist entry")
    p_rm.add_argument("notice_id")

    p_save = sub.add_parser("save-search", help="Save a search filter set")
    p_save.add_argument("name")
    p_save.add_argument("--keyword")
    p_save.add_argument("--naics")
    p_save.add_argument("--state")
    p_save.add_argument("--set-aside", dest="set_aside")
    p_save.add_argument("--notice-type", dest="notice_type")
    p_save.add_argument("--days", type=int)
    p_save.add_argument("--description")
    p_save.add_argument("--profile", default="technical_services")
    p_save.add_argument("--min-score", dest="min_score", type=int, default=2)

    sub.add_parser("list-searches", help="List saved searches")

    p_rmsearch = sub.add_parser("delete-search", help="Delete a saved search")
    p_rmsearch.add_argument("name")

    args = parser.parse_args()
    store = Store()

    if args.cmd == "add":
        entry = store.add_to_watchlist(
            {"notice_id": args.notice_id, "title": args.title},
            status=args.status,
            notes=args.notes,
            score=args.score,
        )
        print(f"Added {entry.notice_id}: {entry.title} [{entry.status}]")
    elif args.cmd == "list":
        entries = store.list_watchlist(status=args.status, limit=args.limit)
        if not entries:
            print("(no entries)")
            return
        for entry in entries:
            print(f"[{entry.status:<10}] {entry.notice_id}  due={entry.response_deadline or '-'}  {entry.title[:80]}")
    elif args.cmd == "status":
        entry = store.update_status(args.notice_id, args.new_status, note=args.note)
        if not entry:
            raise SystemExit(f"No watchlist entry with notice_id {args.notice_id}")
        print(f"{entry.notice_id} -> {entry.status}")
    elif args.cmd == "note":
        store.add_note(args.notice_id, args.text)
        print("note added")
    elif args.cmd == "remove":
        removed = store.remove_from_watchlist(args.notice_id)
        print("removed" if removed else "not found")
    elif args.cmd == "save-search":
        filters = {
            "keyword": args.keyword,
            "naics": args.naics,
            "state": args.state,
            "set_aside": args.set_aside,
            "notice_type": args.notice_type,
            "days": args.days,
        }
        filters = {k: v for k, v in filters.items() if v is not None}
        saved = store.save_search(
            args.name,
            filters,
            description=args.description,
            profile=args.profile,
            min_score=args.min_score,
        )
        print(f"Saved search {saved.name!r}: {saved.filters} (profile={saved.profile}, min_score={saved.min_score})")
    elif args.cmd == "list-searches":
        searches = store.list_saved_searches()
        if not searches:
            print("(no saved searches)")
            return
        for saved in searches:
            print(f"{saved.name:<24} profile={saved.profile:<20} min_score={saved.min_score}  {saved.filters}")
    elif args.cmd == "delete-search":
        removed = store.delete_saved_search(args.name)
        print("deleted" if removed else "not found")


if __name__ == "__main__":
    _cli()
