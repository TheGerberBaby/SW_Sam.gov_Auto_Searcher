"""Local web dashboard for browsing scored opportunities and managing the watchlist.

No external dependencies — uses the standard-library `http.server` plus
inline HTML/CSS/JS. Run with:

    python scripts/dashboard.py
    # then open http://127.0.0.1:8765/
    python scripts/dashboard.py --env dev
    # then open http://127.0.0.1:8766/

Endpoints:
    GET  /                          → dashboard HTML
    GET  /api/search?...            → JSON search + score results
    GET  /api/watchlist             → list watchlist entries
    POST /api/watchlist             → add (or upsert) a notice
    POST /api/watchlist/status      → update status
    POST /api/watchlist/human-score → record operator fit score
    POST /api/watchlist/note        → append a note
    POST /api/watchlist/remove      → remove entry
    GET  /api/digests               → recent digest runs
    POST /api/digest/run            → trigger a digest, return JSON summary
    GET  /api/saved-searches        → list saved searches
    POST /api/saved-searches        → create/update saved search
    POST /api/saved-searches/delete → delete saved search
    GET  /api/profiles              → available scoring profiles
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import threading
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from scoring import LOCAL_TZ, available_profiles, bulk_score  # noqa: E402
from watchlist import Store, VALID_STATUSES, db_path_for_env, normalize_runtime_env  # noqa: E402
from digest import generate_digest, reports_dir_for_env  # noqa: E402
import tasks_lib  # noqa: E402
import usaspending  # noqa: E402
import ecfr  # noqa: E402
import base64  # noqa: E402
import secrets  # noqa: E402

PROJECT_ROOT = SCRIPT_DIR.parent
DB_PATH = PROJECT_ROOT / "data" / "contracts.db"
META_PATH = PROJECT_ROOT / "data" / "last_sync.txt"
DASHBOARD_ENV = "prod"


# ---------------------------------------------------------------------------
# Search / scoring helpers
# ---------------------------------------------------------------------------


def _search_and_score(
    keyword: str | None = None,
    naics: str | None = None,
    state: str | None = None,
    set_aside: str | None = None,
    notice_type: str | None = None,
    days: int = 30,
    min_score: int = 0,
    profile: str = "technical_services",
    limit: int = 50,
) -> dict[str, Any]:
    if not DB_PATH.exists():
        return {"error": f"DB not found at {DB_PATH}. Run scripts/sync_bulk.py first.", "results": []}
    where = ["active = 'Yes'"]
    params: list[Any] = []
    if keyword:
        where.append("(title LIKE ? OR description LIKE ?)")
        params.extend([f"%{keyword}%", f"%{keyword}%"])
    if naics:
        where.append("naics_code LIKE ?")
        params.append(f"{naics}%")
    if state:
        where.append("UPPER(pop_state) = ?")
        params.append(state.upper())
    if set_aside:
        where.append("UPPER(set_aside_code) = ?")
        params.append(set_aside.upper())
    if notice_type:
        where.append("type LIKE ?")
        params.append(f"%{notice_type}%")
    if days > 0:
        cutoff = (datetime.now(LOCAL_TZ).date() - timedelta(days=days)).isoformat()
        where.append("posted_date >= ?")
        params.append(cutoff)
    sql = f"""
        SELECT notice_id, title, sol_number, department, sub_tier, posted_date,
               type, set_aside, set_aside_code, response_deadline, naics_code,
               pop_city, pop_state, active, link, description
          FROM opportunities
         WHERE {' AND '.join(where)}
         ORDER BY posted_date DESC
         LIMIT ?
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute(sql, params + [max(limit * 5, 100)]).fetchall()]

    scored = bulk_score(rows, profile=profile)
    by_id = {r["notice_id"]: r for r in rows}
    combined = []
    for result in scored:
        opp = by_id.get(result.notice_id, {})
        if result.score < min_score:
            continue
        combined.append({
            **opp,
            "score": result.score,
            "band": result.band,
            "lanes": result.lanes,
            "reasons": [r.to_dict() for r in result.reasons],
        })
    combined.sort(key=lambda c: c["score"], reverse=True)
    combined = combined[:limit]

    synced_at = META_PATH.read_text(encoding="utf-8") if META_PATH.exists() else "unknown"
    return {
        "as_of": datetime.now(LOCAL_TZ).isoformat(),
        "db_sync": synced_at,
        "profile": profile,
        "filters": {
            "keyword": keyword, "naics": naics, "state": state,
            "set_aside": set_aside, "type": notice_type, "days": days,
            "min_score": min_score, "limit": limit,
        },
        "results": combined,
    }


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------


_STORE: Store | None = None
_AUTH_TOKEN: str | None = None  # base64("user:password"); None disables auth


def _store() -> Store:
    global _STORE
    if _STORE is None:
        _STORE = Store(env=DASHBOARD_ENV)
    return _STORE


def _set_runtime_env(env: str | None) -> None:
    global DASHBOARD_ENV, _STORE
    DASHBOARD_ENV = normalize_runtime_env(env)
    os.environ["SWCB_ENV"] = DASHBOARD_ENV
    _STORE = None


def _default_port_for_env(env: str) -> int:
    return 8765 if env == "prod" else 8766


def _set_auth(username: str, password: str | None) -> None:
    """If password is non-empty, require HTTP Basic auth on every request."""
    global _AUTH_TOKEN
    if password:
        _AUTH_TOKEN = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    else:
        _AUTH_TOKEN = None


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "SWContractingDashboard/2.2"

    # quieter logging
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        sys.stderr.write(f"[{self.log_date_time_string()}] {format % args}\n")

    def _check_auth(self) -> bool:
        """Return True if auth passes (or is disabled). On failure, send 401."""
        if _AUTH_TOKEN is None:
            return True
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            self._challenge()
            return False
        # Constant-time compare to avoid timing leaks
        if secrets.compare_digest(header[6:], _AUTH_TOKEN):
            return True
        self._challenge()
        return False

    def _challenge(self) -> None:
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="SW Contracting Dashboard"')
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Authentication required.\n")

    # -------- helpers --------

    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text: str, content_type: str = "text/plain; charset=utf-8") -> None:
        body = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    # -------- routing --------

    def do_GET(self) -> None:  # noqa: N802
        if not self._check_auth():
            return
        parsed = urlparse(self.path)
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        try:
            if parsed.path == "/" or parsed.path == "/index.html":
                self._send_html(_render_dashboard_html())
            elif parsed.path == "/api/search":
                self._send_json(_search_and_score(
                    keyword=params.get("keyword") or None,
                    naics=params.get("naics") or None,
                    state=params.get("state") or None,
                    set_aside=params.get("set_aside") or None,
                    notice_type=params.get("type") or None,
                    days=int(params.get("days") or 30),
                    min_score=int(params.get("min_score") or 0),
                    profile=params.get("profile") or "technical_services",
                    limit=int(params.get("limit") or 50),
                ))
            elif parsed.path == "/api/watchlist":
                entries = _store().list_watchlist(
                    status=params.get("status") or None,
                    limit=int(params.get("limit") or 200),
                )
                self._send_json([e.to_dict() for e in entries])
            elif parsed.path == "/api/digests":
                self._send_json(_store().list_digest_runs(limit=int(params.get("limit") or 20)))
            elif parsed.path == "/api/digest/report":
                run_id = int(params.get("id") or 0)
                run = next((r for r in _store().list_digest_runs(limit=200) if int(r["id"]) == run_id), None)
                if not run or not run.get("report_path"):
                    self._send_json({"error": "not found"}, status=404)
                    return
                report_path = Path(run["report_path"]).resolve()
                report_path.relative_to(reports_dir_for_env(DASHBOARD_ENV).resolve())
                if not report_path.exists():
                    self._send_json({"error": "report file missing"}, status=404)
                    return
                self._send_text(report_path.read_text(encoding="utf-8"), "text/html; charset=utf-8")
            elif parsed.path == "/api/saved-searches":
                self._send_json([s.to_dict() for s in _store().list_saved_searches()])
            elif parsed.path == "/api/profiles":
                self._send_json({
                    "profiles": available_profiles(),
                    "statuses": sorted(VALID_STATUSES),
                    "env": DASHBOARD_ENV,
                    "watchlist_db": str(db_path_for_env(DASHBOARD_ENV)),
                    "reports_dir": str(reports_dir_for_env(DASHBOARD_ENV)),
                })
            elif parsed.path == "/api/tasks":
                tasks = tasks_lib.list_tasks(
                    status=params.get("status") or None,
                    tag=params.get("tag") or None,
                    type_filter=params.get("type") or None,
                )
                self._send_json([t.to_dict() for t in tasks])
            elif parsed.path == "/api/tasks/unblocked":
                tasks = tasks_lib.next_unblocked(limit=int(params.get("limit") or 10))
                self._send_json([t.to_dict() for t in tasks])
            elif parsed.path == "/api/incumbents":
                awards = usaspending.find_incumbents(
                    naics=params.get("naics") or None,
                    agency=params.get("agency") or None,
                    keyword=params.get("keyword") or None,
                    pop_state=params.get("state") or None,
                    years_back=int(params.get("years_back") or 3),
                    limit=int(params.get("limit") or 20),
                )
                self._send_json([a.to_dict() for a in awards])
            elif parsed.path == "/api/ecfr/search":
                hits = ecfr.search(
                    query=params.get("query") or "",
                    title=int(params["title"]) if params.get("title") else None,
                    limit=int(params.get("limit") or 10),
                )
                self._send_json([h.to_dict() for h in hits])
            elif parsed.path == "/api/ecfr/section":
                clause = ecfr.get_section(
                    title=int(params.get("title") or 48),
                    section=params.get("section") or "",
                    part=params.get("part") or None,
                )
                self._send_json(clause.to_dict())
            else:
                self._send_json({"error": "not found"}, status=404)
        except Exception as exc:  # noqa: BLE001
            self._send_json({"error": str(exc)}, status=500)

    def do_POST(self) -> None:  # noqa: N802
        if not self._check_auth():
            return
        parsed = urlparse(self.path)
        try:
            payload = self._read_json_body()
            if parsed.path == "/api/watchlist":
                opp = payload.get("opportunity") or {}
                entry = _store().add_to_watchlist(
                    opp,
                    status=payload.get("status") or "tracking",
                    notes=payload.get("notes"),
                    score=payload.get("score"),
                    band=payload.get("band"),
                    lanes=payload.get("lanes"),
                )
                self._send_json(entry.to_dict())
            elif parsed.path == "/api/watchlist/status":
                entry = _store().update_status(
                    payload["notice_id"],
                    payload["status"],
                    note=payload.get("note"),
                )
                self._send_json(entry.to_dict() if entry else {"error": "not found"},
                                status=200 if entry else 404)
            elif parsed.path == "/api/watchlist/human-score":
                score_raw = payload.get("human_score")
                human_score = None if score_raw in {"", None} else int(score_raw)
                entry = _store().set_human_score(
                    payload["notice_id"],
                    human_score,
                    note=payload.get("note"),
                )
                self._send_json(entry.to_dict() if entry else {"error": "not found"},
                                status=200 if entry else 404)
            elif parsed.path == "/api/watchlist/note":
                _store().add_note(payload["notice_id"], payload.get("text") or "")
                self._send_json({"ok": True})
            elif parsed.path == "/api/watchlist/remove":
                removed = _store().remove_from_watchlist(payload["notice_id"])
                self._send_json({"removed": removed})
            elif parsed.path == "/api/digest/run":
                result = generate_digest(
                    profile=payload.get("profile") or "technical_services",
                    days=int(payload.get("days") or 3),
                    min_score=int(payload.get("min_score") or 2),
                    write=bool(payload.get("write", True)),
                    env=DASHBOARD_ENV,
                )
                self._send_json({
                    "env": result["env"],
                    "scanned": result["scanned"],
                    "shown": result["shown"],
                    "summary": result["summary"],
                    "lane_counts": result["lane_counts"],
                    "items": result["items"],
                    "markdown_path": result["markdown_path"],
                    "html_path": result["html_path"],
                    "generated_at": result["generated_at"],
                })
            elif parsed.path == "/api/saved-searches":
                saved = _store().save_search(
                    payload["name"],
                    payload.get("filters") or {},
                    description=payload.get("description"),
                    profile=payload.get("profile") or "technical_services",
                    min_score=int(payload.get("min_score") or 2),
                )
                self._send_json(saved.to_dict())
            elif parsed.path == "/api/saved-searches/delete":
                removed = _store().delete_saved_search(payload["name"])
                self._send_json({"removed": removed})
            elif parsed.path == "/api/open-artifact":
                rel_path = payload.get("path") or ""
                target = (PROJECT_ROOT / rel_path).resolve()
                target.relative_to(PROJECT_ROOT)
                if not target.exists():
                    self._send_json({"error": "not found"}, status=404)
                    return
                if hasattr(os, "startfile"):
                    os.startfile(str(target))  # type: ignore[attr-defined]
                else:
                    webbrowser.open(target.as_uri())
                self._send_json({"ok": True, "path": str(target)})
            elif parsed.path == "/api/tasks/status":
                task = tasks_lib.set_status(
                    payload["task_id"], payload["status"], note=payload.get("note"),
                )
                self._send_json(task.to_dict())
            elif parsed.path == "/api/ask":
                result = _handle_ask(payload.get("text") or "")
                self._send_json(result)
            else:
                self._send_json({"error": "not found"}, status=404)
        except KeyError as exc:
            self._send_json({"error": f"missing field: {exc.args[0]}"}, status=400)
        except Exception as exc:  # noqa: BLE001
            self._send_json({"error": str(exc)}, status=500)


# ---------------------------------------------------------------------------
# Ask command router
# ---------------------------------------------------------------------------


def _handle_ask(text: str) -> dict[str, Any]:
    """Route a free-text command to the right capability.

    This is intentionally pattern-matched, not LLM-driven — it works
    offline, costs nothing, and behaves predictably. The grammar is
    very small; phrases that don't match return a help response.
    """
    raw = text.strip()
    if not raw:
        return _ask_help("(empty input)")
    lower = raw.lower()
    tokens = lower.split()
    head = tokens[0] if tokens else ""
    rest = " ".join(tokens[1:]).strip()

    # — Roadmap / tasks shortcuts —
    if lower in {"next", "what next", "what's next", "todo", "today"} or head in {"next", "unblocked"}:
        tasks = tasks_lib.next_unblocked(limit=10)
        return {
            "kind": "tasks/unblocked",
            "summary": f"{len(tasks)} next-actionable workstream(s)",
            "results": [t.to_dict() for t in tasks],
        }
    if head == "tasks":
        status = rest if rest in tasks_lib.VALID_STATUSES else None
        tasks = tasks_lib.list_tasks(status=status)
        return {
            "kind": "tasks/list",
            "summary": f"{len(tasks)} task(s)" + (f" (status={status})" if status else ""),
            "results": [t.to_dict() for t in tasks],
        }

    # — Watchlist —
    if head in {"watchlist", "watching", "pursuing"}:
        status = "pursuing" if head == "pursuing" else (rest if rest in VALID_STATUSES else None)
        entries = _store().list_watchlist(status=status, limit=100)
        return {
            "kind": "watchlist/list",
            "summary": f"{len(entries)} watchlist entr{'y' if len(entries) == 1 else 'ies'}",
            "results": [e.to_dict() for e in entries],
        }

    # — Digest —
    if head == "digest":
        result = generate_digest(profile="technical_services", days=3, min_score=3, write=True)
        return {
            "kind": "digest/run",
            "summary": f"Digest: {result['shown']} of {result['scanned']} scored ≥ 3",
            "results": result,
        }

    # — eCFR FAR clause lookups (e.g. "far 52.212-2", "cfr 13 121.201") —
    if head == "far":
        return _ask_ecfr_section(48, rest)
    if head == "cfr":
        bits = rest.split()
        if len(bits) >= 2 and bits[0].isdigit():
            title_num = int(bits[0])
            return _ask_ecfr_section(title_num, " ".join(bits[1:]))

    # — Incumbents by NAICS (e.g. "incumbents 541512") —
    if head in {"incumbents", "incumbent"}:
        naics = rest if rest else "541512"
        awards = usaspending.find_incumbents(naics=naics, limit=15)
        return {
            "kind": "usaspending/incumbents",
            "summary": f"Top USAspending recipients for NAICS {naics}",
            "results": [a.to_dict() for a in awards],
        }

    # — Score / search (e.g. "elastic", "score vtc", "search Kibana") —
    if head in {"score", "search"} or head in _KNOWN_LANE_KEYWORDS:
        keyword = raw if head not in {"score", "search"} else rest
        if not keyword:
            return _ask_help("usage: score <keyword>")
        result = _search_and_score(keyword=keyword, days=60, min_score=2, limit=20)
        return {
            "kind": "score",
            "summary": f"{len(result['results'])} scored result(s) for {keyword!r}",
            "results": result["results"],
        }

    if head in {"help", "?", "/help"}:
        return _ask_help()
    return _ask_help(f"unknown command: {head!r}")


_KNOWN_LANE_KEYWORDS = {
    "elastic", "elasticsearch", "opensearch", "kibana", "logstash",
    "rag", "observability", "siem", "vtc",
}


def _ask_ecfr_section(title: int, section: str) -> dict[str, Any]:
    section = section.strip()
    if not section:
        return _ask_help(f"usage: {'far' if title == 48 else 'cfr'} <section>")
    try:
        clause = ecfr.get_section(title=title, section=section)
        return {
            "kind": "ecfr/section",
            "summary": clause.citation,
            "results": clause.to_dict(),
        }
    except ecfr.ECFRError as exc:
        return {"kind": "error", "summary": str(exc), "results": None}


def _ask_help(prefix: str = "") -> dict[str, Any]:
    return {
        "kind": "help",
        "summary": prefix or "command palette",
        "results": {
            "examples": [
                "next               — next-actionable workstreams",
                "tasks              — all tasks (or `tasks blocked`, `tasks pending`)",
                "watchlist          — current pursuits",
                "digest             — run today's lead scan",
                "elastic            — score search for 'elastic' across last 60d",
                "score Kibana       — score search for 'Kibana'",
                "incumbents 541512  — USAspending top recipients for NAICS 541512",
                "far 52.212-2       — fetch FAR 52.212-2 text",
                "cfr 13 121.201     — fetch 13 CFR 121.201 (SBA size standards)",
            ],
        },
    }


# ---------------------------------------------------------------------------
# Single-file HTML/CSS/JS dashboard
# ---------------------------------------------------------------------------


def _render_dashboard_html() -> str:
    html_doc = r"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#1e3a8a">
<title>Stormwind Contract Workbench</title>
<style>
:root {
  --bg: #f6f7fb;
  --bg-2: #eef2f7;
  --surface: #ffffff;
  --surface-2: #f7f9fc;
  --ink: #111827;
  --ink-2: #263143;
  --mute: #6b7587;
  --line: #e1e6ef;
  --line-strong: #cbd4e1;
  --chrome: #101827;
  --chrome-2: #162033;
  --chrome-line: rgba(255,255,255,.12);
  --primary: #2457c5;
  --primary-dark: #1c459d;
  --primary-soft: #e9efff;
  --accent: #12805c;
  --accent-soft: #e7f5ef;
  --warn: #a36500;
  --warn-soft: #fff5df;
  --bad: #c33b3b;
  --bad-soft: #fff1f1;
  --strong: #17805d;
  --promising: #2457c5;
  --monitor: #a36500;
  --reject: #7d8796;
  --shadow-sm: 0 1px 2px rgba(17, 24, 39, .06);
  --shadow-md: 0 16px 42px rgba(17, 24, 39, .12);
  --radius: 8px;
}
html[data-theme="dark"] {
  --bg: #121417;
  --bg-2: #191d23;
  --surface: #1b2027;
  --surface-2: #232a33;
  --ink: #f1f5f9;
  --ink-2: #dce4ef;
  --mute: #a7b1c0;
  --line: #303946;
  --line-strong: #435062;
  --chrome: #0d1117;
  --chrome-2: #171c23;
  --chrome-line: rgba(255,255,255,.12);
  --primary: #7aa7ff;
  --primary-dark: #a8c3ff;
  --primary-soft: #23314d;
  --accent: #42c890;
  --accent-soft: #173729;
  --warn: #f0b35f;
  --warn-soft: #3a2a14;
  --bad: #ff8b8b;
  --bad-soft: #3b1f24;
  --shadow-sm: 0 1px 2px rgba(0,0,0,.28);
  --shadow-md: 0 16px 42px rgba(0,0,0,.38);
}
* { box-sizing: border-box; }
html { min-height: 100%; background: var(--bg); }
body {
  min-height: 100%;
  margin: 0;
  background:
    linear-gradient(180deg, var(--bg-2) 0, var(--bg) 240px, var(--surface-2) 100%);
  color: var(--ink);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  letter-spacing: 0;
}
button, input, select, textarea { font: inherit; letter-spacing: 0; }
button, .chip, select { touch-action: manipulation; }
.app-shell { min-height: 100vh; }
header {
  width: calc(100% - 3rem);
  max-width: 1480px;
  margin: 1rem auto 0;
  padding: 1rem;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 1rem;
  color: white;
  background:
    linear-gradient(135deg, rgba(255,255,255,.08), rgba(255,255,255,0) 34%),
    linear-gradient(135deg, var(--chrome), var(--chrome-2));
  border: 1px solid var(--chrome-line);
  border-radius: 12px;
  box-shadow: var(--shadow-md);
}
.brand { display: flex; align-items: center; min-width: 0; gap: .85rem; }
.brand-mark {
  width: 44px;
  height: 44px;
  border-radius: 8px;
  display: grid;
  place-items: center;
  color: var(--chrome);
  font-weight: 800;
  background: linear-gradient(135deg, #f9fafb, #cce9dc);
  box-shadow: inset 0 0 0 1px rgba(255,255,255,.65);
}
header h1 { margin: 0; font-size: 1.1rem; line-height: 1.2; font-weight: 760; }
.subtitle { color: rgba(255,255,255,.68); font-size: .84rem; margin-top: .2rem; }
.header-side {
  display: grid;
  justify-items: end;
  gap: .55rem;
}
header .meta {
  color: rgba(255,255,255,.72);
  font-size: .82rem;
  padding: .4rem .68rem;
  background: rgba(255,255,255,.08);
  border: 1px solid var(--chrome-line);
  border-radius: 999px;
  white-space: nowrap;
}
.ai-layer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: .35rem;
}
.ai-label {
  color: rgba(255,255,255,.56);
  font-size: .68rem;
  font-weight: 800;
  text-transform: uppercase;
}
.ai-chip {
  min-height: 27px;
  display: inline-flex;
  align-items: center;
  gap: .36rem;
  padding: .24rem .58rem;
  color: rgba(255,255,255,.9);
  background: rgba(255,255,255,.08);
  border: 1px solid var(--chrome-line);
  border-radius: 999px;
  font-size: .76rem;
  font-weight: 750;
}
.ai-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: #43d39e;
  box-shadow: 0 0 0 3px rgba(67,211,158,.14);
}
.theme-toggle {
  min-height: 31px;
  padding: .28rem .68rem;
  color: rgba(255,255,255,.9);
  background: rgba(255,255,255,.08);
  border: 1px solid var(--chrome-line);
  border-radius: 999px;
  font-size: .78rem;
  font-weight: 750;
  cursor: pointer;
}
.theme-toggle:hover { background: rgba(255,255,255,.14); }
nav {
  width: calc(100% - 3rem);
  max-width: 1480px;
  margin: 0 auto;
  padding: .75rem 0 1rem;
  display: flex;
  gap: .35rem;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  scrollbar-width: none;
}
nav::-webkit-scrollbar { display: none; }
nav button {
  min-height: 38px;
  padding: .48rem .85rem;
  border: 1px solid transparent;
  border-radius: 999px;
  background: transparent;
  color: #637083;
  cursor: pointer;
  font-size: .9rem;
  white-space: nowrap;
}
nav button.active {
  color: var(--ink);
  background: var(--surface);
  border-color: var(--line);
  box-shadow: 0 8px 20px rgba(17,24,39,.08);
  font-weight: 650;
}
nav button:hover { color: var(--ink); background: rgba(255,255,255,.68); }
main {
  width: calc(100% - 3rem);
  max-width: 1480px;
  margin: 0 auto;
  padding: 0 0 2rem;
}
.section { display: none; }
.section.active { display: block; }
.overview {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: .8rem;
  margin-bottom: 1rem;
}
.page-intro {
  background: rgba(255,255,255,.96);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
  padding: 1rem;
  margin-bottom: .85rem;
}
.page-intro h2 {
  margin: 0 0 .35rem;
  font-size: 1.05rem;
  line-height: 1.25;
}
.page-intro p {
  margin: 0;
  color: var(--mute);
  font-size: .9rem;
  line-height: 1.45;
}
.guide-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: .75rem;
  margin-bottom: 1rem;
}
.guide-card {
  background: rgba(255,255,255,.94);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
  padding: .9rem;
}
.guide-card b { display: block; color: var(--ink); margin-bottom: .25rem; }
.guide-card span { display: block; color: var(--mute); font-size: .84rem; line-height: 1.42; }
.stat-card {
  min-height: 78px;
  background: rgba(255,255,255,.92);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
  padding: .78rem .88rem;
  text-align: left;
  color: inherit;
}
.stat-link {
  border: 1px solid var(--line);
  cursor: pointer;
}
.stat-link:hover {
  border-color: var(--primary);
  transform: translateY(-1px);
  box-shadow: 0 12px 28px rgba(17,24,39,.1);
}
.artifact-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: .75rem;
}
.artifact-card {
  background: rgba(255,255,255,.94);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
  padding: .9rem;
}
.scan-panel {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 1rem;
  align-items: end;
}
.scan-options {
  display: grid;
  grid-template-columns: repeat(2, minmax(180px, 1fr));
  gap: .75rem;
}
.scan-options label {
  display: flex;
  flex-direction: column;
  gap: .32rem;
  font-size: .78rem;
  font-weight: 700;
  text-transform: uppercase;
}
.fit-pill {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: .14rem .5rem;
  border-radius: 999px;
  font-size: .72rem;
  font-weight: 800;
  background: var(--warn-soft);
  color: var(--warn);
  border: 1px solid rgba(163,101,0,.25);
}
.fit-pill.solo, .fit-pill.light_help { background: var(--accent-soft); color: var(--accent); border-color: rgba(18,128,92,.24); }
.fit-pill.team { background: var(--bad-soft); color: var(--bad); border-color: rgba(195,59,59,.24); }
.past-scan-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: .75rem;
}
.past-scan {
  min-height: 120px;
  cursor: pointer;
}
.past-scan:hover { border-color: var(--primary); }
html[data-theme="dark"] .artifact-card,
html[data-theme="dark"] .guide-card,
html[data-theme="dark"] .page-intro,
html[data-theme="dark"] .stat-card,
html[data-theme="dark"] .card,
html[data-theme="dark"] .filters,
html[data-theme="dark"] .ask-box,
html[data-theme="dark"] .ask-output,
html[data-theme="dark"] .table-wrap,
html[data-theme="dark"] table {
  background: rgba(27,32,39,.96);
}
.stat-label { color: var(--mute); font-size: .7rem; font-weight: 800; text-transform: uppercase; }
.stat-value { margin-top: .28rem; font-size: 1.28rem; line-height: 1; font-weight: 800; color: var(--ink); }
.stat-note { margin-top: .28rem; color: var(--mute); font-size: .8rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.filters {
  background: rgba(255,255,255,.94);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
  padding: 1rem;
  margin-bottom: .85rem;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: .8rem;
}
label { color: var(--mute); }
.filters label {
  display: flex;
  flex-direction: column;
  gap: .32rem;
  font-size: .78rem;
  font-weight: 700;
  text-transform: uppercase;
}
input, select, textarea {
  width: 100%;
  min-height: 38px;
  padding: .52rem .62rem;
  border: 1px solid var(--line-strong);
  border-radius: 7px;
  color: var(--ink);
  background: var(--surface);
  outline: none;
}
input::placeholder { color: #97a6ba; opacity: 1; }
input:focus, select:focus, textarea:focus {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px rgba(39,93,204,.14);
}
button:focus-visible, .chip:focus-visible, a:focus-visible {
  outline: 3px solid rgba(39,93,204,.24);
  outline-offset: 2px;
}
.actions {
  display: flex;
  gap: .5rem;
  flex-wrap: wrap;
  align-items: center;
  margin-bottom: .9rem;
}
button.primary, button.ghost, a.ghost {
  min-height: 38px;
  border-radius: 7px;
  padding: .52rem .85rem;
  font-weight: 700;
  cursor: pointer;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
button.primary {
  background: var(--ink);
  color: white;
  border: 1px solid var(--ink);
  box-shadow: var(--shadow-sm);
}
html[data-theme="dark"] button.primary {
  background: var(--primary);
  color: #0d1117;
  border-color: var(--primary);
}
button.primary:hover { background: var(--primary-dark); border-color: var(--primary-dark); }
button.ghost, a.ghost {
  background: rgba(255,255,255,.86);
  color: var(--ink-2);
  border: 1px solid var(--line-strong);
}
button.ghost:hover, a.ghost:hover { border-color: var(--primary); color: var(--primary); }
.summary {
  min-height: 22px;
  color: var(--mute);
  font-size: .88rem;
  margin: .35rem 0 .75rem;
}
.card {
  position: relative;
  background: rgba(255,255,255,.96);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
  padding: 1rem;
  margin-bottom: .75rem;
}
.card:hover { border-color: var(--line-strong); box-shadow: 0 12px 28px rgba(17,24,39,.08); }
.card .title {
  color: var(--ink);
  font-size: 1rem;
  line-height: 1.35;
  font-weight: 760;
  margin: .55rem 0 .65rem;
}
.card-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: .75rem;
}
.score-stack { display: flex; flex-wrap: wrap; align-items: center; gap: .32rem; }
.due-pill {
  white-space: nowrap;
  color: var(--mute);
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: .22rem .58rem;
  font-size: .76rem;
  font-weight: 700;
}
.badge {
  display: inline-flex;
  align-items: center;
  min-height: 23px;
  padding: .16rem .55rem;
  border-radius: 999px;
  color: white;
  font-size: .72rem;
  font-weight: 800;
}
.badge.strong { background: var(--strong); }
.badge.promising { background: var(--promising); }
.badge.monitor { background: var(--monitor); }
.badge.reject { background: var(--reject); }
.badge.status { background: var(--ink-2); }
.lane-chip {
  display: inline-flex;
  align-items: center;
  min-height: 23px;
  background: var(--primary-soft);
  color: var(--primary-dark);
  border: 1px solid #cbdcff;
  padding: .12rem .5rem;
  border-radius: 999px;
  font-size: .72rem;
  font-weight: 700;
}
.detail-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: .55rem;
  margin: .5rem 0;
}
.detail {
  min-width: 0;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: 7px;
  padding: .5rem .6rem;
}
.detail span {
  display: block;
  color: var(--mute);
  font-size: .68rem;
  font-weight: 800;
  text-transform: uppercase;
}
.detail b {
  display: block;
  margin-top: .18rem;
  color: var(--ink-2);
  font-size: .82rem;
  font-weight: 650;
  overflow-wrap: anywhere;
}
.meta-row { color: var(--mute); font-size: .86rem; margin: .2rem 0; overflow-wrap: anywhere; }
code {
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: 5px;
  padding: .08rem .28rem;
  color: var(--ink-2);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: .85em;
}
.reasons {
  margin-top: .65rem;
  display: flex;
  flex-wrap: wrap;
  gap: .28rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: .74rem;
}
.reasons span {
  display: inline-flex;
  max-width: 100%;
  padding: .18rem .45rem;
  background: var(--accent-soft);
  color: #17624b;
  border: 1px solid #c6e6d8;
  border-radius: 6px;
  overflow-wrap: anywhere;
}
.reasons span.neg { background: var(--bad-soft); color: #9f2626; border-color: #ffd2d2; }
.card .card-actions { margin-top: .75rem; display: flex; gap: .45rem; flex-wrap: wrap; }
.card .card-actions button, .card .card-actions a { font-size: .82rem; min-height: 34px; padding: .36rem .68rem; }
.empty {
  color: var(--mute);
  text-align: center;
  padding: 2rem 1rem;
  background: rgba(255,255,255,.72);
  border: 1px dashed var(--line-strong);
  border-radius: var(--radius);
}
.row-link { color: var(--primary); text-decoration: none; font-weight: 650; }
.row-link:hover { text-decoration: underline; }
.ask-box {
  background: rgba(255,255,255,.96);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  box-shadow: 0 12px 32px rgba(17,24,39,.09);
  padding: 1rem;
  margin-bottom: 1rem;
}
.ask-box form { margin: 0; }
.ask-box input {
  min-height: 52px;
  padding: .85rem 1rem;
  border-radius: 8px;
  font-size: 1rem;
  font-weight: 650;
}
.ask-box .hint { color: var(--mute); font-size: .8rem; margin: .7rem 0 0; }
.ask-output {
  background: rgba(255,255,255,.9);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
  padding: 1rem;
  font-size: .9rem;
}
.ask-output pre {
  background: #101827;
  color: #e8eef6;
  border-radius: 7px;
  padding: .75rem .85rem;
  font-size: .82rem;
  overflow-x: auto;
}
.chip-row { display: flex; flex-wrap: wrap; gap: .4rem; margin-top: .75rem; }
.chip-row .chip {
  display: inline-flex;
  align-items: center;
  min-height: 30px;
  background: var(--surface-2);
  color: var(--ink-2);
  border: 1px solid var(--line);
  padding: .28rem .65rem;
  border-radius: 999px;
  font-size: .8rem;
  font-weight: 700;
  cursor: pointer;
}
.chip-row .chip:hover { border-color: var(--primary); color: var(--primary); background: var(--primary-soft); }
.table-wrap {
  width: 100%;
  overflow-x: auto;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: var(--surface);
  box-shadow: var(--shadow-sm);
}
table { width: 100%; min-width: 760px; border-collapse: collapse; background: white; }
th, td { text-align: left; padding: .76rem .85rem; font-size: .88rem; border-bottom: 1px solid var(--line); vertical-align: top; }
th {
  background: var(--surface-2);
  color: var(--mute);
  font-size: .72rem;
  font-weight: 800;
  text-transform: uppercase;
}
tbody tr:last-child td { border-bottom: 0; }
tr:hover { background: #fbfdff; }
html[data-theme="dark"] tr:hover { background: #232a33; }
.modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15,23,42,.52);
  display: none;
  align-items: center;
  justify-content: center;
  z-index: 50;
  padding: 1rem;
}
.modal-backdrop.show { display: flex; }
.modal {
  background: white;
  border-radius: var(--radius);
  box-shadow: 0 30px 80px rgba(11,18,32,.28);
  padding: 1.25rem;
  max-width: 520px;
  width: 100%;
}
.modal h3 { margin: 0 0 .75rem; }
.modal label { display: block; margin-top: .75rem; font-size: .82rem; font-weight: 700; text-transform: uppercase; }
.modal-actions { margin-top: 1rem; display: flex; justify-content: flex-end; gap: .5rem; flex-wrap: wrap; }
.spinner {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid #cbd5e1;
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin .8s linear infinite;
  vertical-align: middle;
  margin-right: .35rem;
}
.toast {
  position: fixed;
  bottom: 20px;
  right: 20px;
  max-width: min(420px, calc(100vw - 32px));
  background: var(--ink);
  color: white;
  padding: .72rem .9rem;
  border-radius: 8px;
  z-index: 100;
  box-shadow: var(--shadow-md);
}
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 980px) {
  .overview { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .guide-grid, .artifact-grid { grid-template-columns: 1fr; }
  .detail-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 720px) {
  header { width: auto; margin: .7rem .75rem 0; padding: .9rem; grid-template-columns: 1fr; }
  .header-side { justify-items: start; }
  header .meta { max-width: 100%; overflow: hidden; text-overflow: ellipsis; }
  .ai-layer { justify-content: flex-start; }
  nav { width: auto; padding: .65rem .75rem .8rem; }
  main { width: auto; padding: 0 .75rem 1.5rem; }
  .overview { gap: .55rem; }
  .stat-card { min-height: 76px; padding: .72rem; }
  .stat-value { font-size: 1.14rem; }
  .filters { grid-template-columns: 1fr 1fr; padding: .8rem; gap: .6rem; }
  .scan-panel, .scan-options { grid-template-columns: 1fr; }
  .card { padding: .85rem; }
  .card-top { flex-direction: column; }
  .due-pill { white-space: normal; }
  button.primary, button.ghost, a.ghost { width: auto; }
}
@media (max-width: 520px) {
  .brand-mark { width: 38px; height: 38px; }
  .overview, .filters, .detail-grid { grid-template-columns: 1fr; }
  nav button { min-height: 36px; padding: .42rem .72rem; }
  .ai-label { flex-basis: 100%; }
}
</style>
</head>
<body>
<div class="app-shell">
<header>
  <div class="brand">
    <div class="brand-mark">SW</div>
    <div>
      <h1>Stormwind Contract Workbench <small style="color:rgba(255,255,255,.52);font-weight:650">v2.2</small></h1>
      <div class="subtitle">ChatGPT and Claude extension layer for federal technical-services work</div>
    </div>
  </div>
  <div class="header-side">
    <div class="meta" id="dbMeta">loading...</div>
    <div class="ai-layer" aria-label="AI client integrations">
      <span class="ai-label">AI clients</span>
      <span class="ai-chip"><span class="ai-dot"></span>ChatGPT / Codex</span>
      <span class="ai-chip"><span class="ai-dot"></span>Claude</span>
      <span class="ai-chip"><span class="ai-dot"></span>MCP</span>
      <span class="ai-chip" id="envBadge"><span class="ai-dot"></span>PROD</span>
      <button class="theme-toggle" id="themeToggle" type="button" onclick="toggleTheme()">Dark mode</button>
    </div>
  </div>
</header>
<nav>
  <button data-tab="ask" class="active">Start Here</button>
  <button data-tab="digest">Today's Leads</button>
  <button data-tab="search">Find Leads</button>
  <button data-tab="watchlist">Pursuits</button>
  <button data-tab="saved">Prompt Library</button>
  <button data-tab="profile">Profile & Rules</button>
  <button data-tab="tasks">Business Setup</button>
</nav>
<main>
  <section class="overview" id="overview">
    <button class="stat-card stat-link" onclick="setTab('profile')" type="button">
      <div class="stat-label">Profiles</div>
      <div class="stat-value" id="statProfiles">--</div>
      <div class="stat-note" id="statProfileNote">click for profile and scoring rules</div>
    </button>
    <button class="stat-card stat-link" onclick="setTab('watchlist')" type="button">
      <div class="stat-label">Pursuits</div>
      <div class="stat-value" id="statWatchlist">--</div>
      <div class="stat-note">click for tracked contracts</div>
    </button>
    <button class="stat-card stat-link" onclick="setTab('tasks'); loadTasks('unblocked')" type="button">
      <div class="stat-label">Next Tasks</div>
      <div class="stat-value" id="statTasks">--</div>
      <div class="stat-note">click for the business tracker</div>
    </button>
    <button class="stat-card stat-link" onclick="startLeadScan()" type="button">
      <div class="stat-label">Today's Leads</div>
      <div class="stat-value">Scan</div>
      <div class="stat-note">run a profile-based lead search</div>
    </button>
  </section>

  <section id="tab-ask" class="section active">
    <div class="page-intro">
      <h2>How Jeremy uses this</h2>
      <p>This workbench is meant to run beside Codex, Claude Code, or another local AI. You tell the AI to use this project directory, it reads the Stormwind profile and rules, searches for realistic contract leads, and writes results back here so you can track them.</p>
    </div>
    <div class="guide-grid">
      <div class="guide-card">
        <b>1. Point the AI at the repo</b>
        <span>Tell Codex or Claude to read this directory, start with PROFILE.md and tasks/, and use the technical-contract research tools.</span>
        <div class="card-actions"><button class="ghost" onclick="copyStarterPrompt()">Copy starter prompt</button></div>
      </div>
      <div class="guide-card">
        <b>2. Keep the profile honest</b>
        <span>Your profile controls fit, exclusions, set-aside assumptions, size hints, and what the AI should avoid inventing.</span>
        <div class="card-actions"><button class="ghost" onclick="setTab('profile')">Open Profile & Rules</button></div>
      </div>
      <div class="guide-card">
        <b>3. Scan and track real leads</b>
        <span>Run the profile-based scan, save realistic contracts to Pursuits, then tell the AI what changed so it can update the tracker.</span>
        <div class="card-actions"><button class="primary" onclick="startLeadScan()">Scan Today's Leads</button><button class="ghost" onclick="setTab('watchlist')">Open Pursuits</button></div>
      </div>
    </div>
    <div class="ask-box">
      <form id="askForm" onsubmit="event.preventDefault(); runAsk();">
        <input id="askInput" placeholder='try: digest · vtc · help desk · watchlist · next · incumbents 541512'
               autocomplete="off" autofocus>
      </form>
      <div class="chip-row" id="askChips">
        <span class="chip" data-cmd="next">next</span>
        <span class="chip" data-cmd="tasks">tasks</span>
        <span class="chip" data-cmd="watchlist">watchlist</span>
        <span class="chip" data-cmd="digest">digest</span>
        <span class="chip" data-cmd="elastic">elastic</span>
        <span class="chip" data-cmd="vtc">vtc</span>
        <span class="chip" data-cmd="incumbents 541512">incumbents 541512</span>
        <span class="chip" data-cmd="far 52.212-2">far 52.212-2</span>
        <span class="chip" data-cmd="cfr 13 121.201">cfr 13 121.201</span>
        <span class="chip" data-cmd="help">help</span>
      </div>
    </div>
    <div id="askOutput"></div>
  </section>

  <section id="tab-search" class="section">
    <div class="page-intro">
      <h2>Find leads</h2>
      <p>Search the local SAM mirror by keyword, agency hints, place of performance, set-aside, or notice type. The score is machine triage, not a bid decision. You can also tell Codex or Claude to run this search and push realistic hits into Pursuits.</p>
    </div>
    <div class="filters">
      <label>What kind of work?<input id="f-keyword" placeholder="help desk, VTC, ACAS, Python, SharePoint"></label>
      <label>NAICS<input id="f-naics" placeholder="541512"></label>
      <label>Place of performance state<input id="f-state" placeholder="VA, MD, DC"></label>
      <label>Set-aside<input id="f-set_aside" placeholder="SBA"></label>
      <label>Type<input id="f-type" placeholder="Solicitation"></label>
      <label>Posted in last X days<input id="f-days" type="number" value="30" min="1"></label>
      <label>Minimum machine score<input id="f-min_score" type="number" value="2"></label>
      <label>Profile
        <select id="f-profile"><option value="technical_services">technical_services</option></select>
      </label>
      <label>Limit<input id="f-limit" type="number" value="50" min="5"></label>
    </div>
    <div class="actions">
      <button class="primary" onclick="runSearch()">Find matching leads</button>
      <button class="ghost" onclick="resetFilters()">Reset</button>
      <button class="ghost" onclick="openSaveSearch()">Save as reusable search…</button>
    </div>
    <div class="summary" id="searchSummary"></div>
    <div id="searchResults"></div>
  </section>

  <section id="tab-profile" class="section">
    <div class="page-intro">
      <h2>Profile & rules</h2>
      <p>These are the artifacts the AI should read before contract research. They define who Stormwind is, what work fits, what to exclude, and what business tasks are still open.</p>
    </div>
    <div class="artifact-grid">
      <div class="artifact-card">
        <div class="title">Business profile</div>
        <div class="meta-row">Stormwind identity, location focus, NAICS, set-aside posture, and operating assumptions.</div>
        <div class="meta-row"><code>PROFILE.md</code></div>
        <div class="card-actions"><button class="primary" onclick="openArtifact('PROFILE.md')">Open</button><button class="ghost" onclick="copyPath('PROFILE.md')">Copy path</button></div>
      </div>
      <div class="artifact-card">
        <div class="title">Technical-services fit rules</div>
        <div class="meta-row">Capability lanes, discovery vocabulary, exclusions, scoring, and required evidence checks.</div>
        <div class="meta-row"><code>criteria/TECHNICAL_SERVICES_PROFILE.md</code></div>
        <div class="card-actions"><button class="primary" onclick="openArtifact('criteria/TECHNICAL_SERVICES_PROFILE.md')">Open</button><button class="ghost" onclick="copyPath('criteria/TECHNICAL_SERVICES_PROFILE.md')">Copy path</button></div>
      </div>
      <div class="artifact-card">
        <div class="title">Document index guide</div>
        <div class="meta-row">How solicitation attachments, SOWs, PWS files, and evidence searches are stored.</div>
        <div class="meta-row"><code>docs/DOCUMENT_INDEX.md</code></div>
        <div class="card-actions"><button class="primary" onclick="openArtifact('docs/DOCUMENT_INDEX.md')">Open</button><button class="ghost" onclick="copyPath('docs/DOCUMENT_INDEX.md')">Copy path</button></div>
      </div>
      <div class="artifact-card">
        <div class="title">Business task tracker</div>
        <div class="meta-row">Formation, SAM registration, VetCert, state registration, eVA, and first bid workstreams.</div>
        <div class="meta-row"><code>tasks/</code></div>
        <div class="card-actions"><button class="primary" onclick="setTab('tasks'); loadTasks('unblocked')">Open Tracker</button><button class="ghost" onclick="openArtifact('tasks')">Open Folder</button></div>
      </div>
    </div>
  </section>

  <section id="tab-watchlist" class="section">
    <div class="page-intro">
      <h2>Pursuits</h2>
      <p>This is the working list. Keep rough ideas in tracking, move serious ones to assessing or pursuing, and use My fit to teach the system what actually looks realistic to you. Tell the AI when a lead changes stage and it can update this tracker.</p>
    </div>
    <div class="actions">
      <label style="display:flex;align-items:center;gap:.4rem;">Status filter:
        <select id="w-status"><option value="">all</option></select>
      </label>
      <button class="primary" onclick="loadWatchlist()">Refresh</button>
    </div>
    <div id="watchlistTable"></div>
  </section>

  <section id="tab-tasks" class="section">
    <div class="page-intro">
      <h2>Business setup</h2>
      <p>These are Stormwind operating tasks, separate from individual contract leads. Use “Unblocked” when you want the next admin step that is not waiting on something else.</p>
    </div>
    <div class="actions">
      <button class="primary" onclick="loadTasks('unblocked')">Unblocked (what's next)</button>
      <button class="ghost" onclick="loadTasks('all')">All</button>
      <button class="ghost" onclick="loadTasks('blocked')">Blocked</button>
      <button class="ghost" onclick="loadTasks('unknown')">Unknown</button>
    </div>
    <div id="tasksSummary" class="summary"></div>
    <div id="tasksList"></div>
  </section>

  <section id="tab-saved" class="section">
    <div class="page-intro">
      <h2>Prompt library</h2>
      <p>Drop in plain text or markdown prompt files for repeatable research workflows. Older saved filter searches still appear here, but the main idea is reusable instructions you can run from Start Here.</p>
    </div>
    <div class="card" id="promptDropZone" style="border-style:dashed">
      <div class="title">Drop prompt files here</div>
      <div class="meta-row">Accepts .txt and .md files. Each file becomes a reusable prompt card stored locally in the workbench database.</div>
      <div class="card-actions">
        <button class="primary" onclick="document.getElementById('promptFileInput').click()">Choose files</button>
        <input id="promptFileInput" type="file" accept=".txt,.md,text/plain,text/markdown" multiple style="display:none">
      </div>
    </div>
    <div class="actions">
      <button class="primary" onclick="loadSavedSearches()">Refresh library</button>
    </div>
    <div id="savedSearchTable"></div>
  </section>

  <section id="tab-digest" class="section">
    <div class="page-intro">
      <h2>Today's leads</h2>
      <p>This is the quick lead scan. It uses the Stormwind profile, shows the score, work location, and a first-pass read on whether it looks solo-friendly, light-help, team-only, or just worth monitoring.</p>
    </div>
    <select id="d-profile" style="display:none"><option value="technical_services">technical_services</option></select>
    <div class="card scan-panel">
      <div>
        <div class="title">Run a simple scan</div>
        <div class="meta-row">Default is a practical recent scan. Use wider range when you want more maybes, tighter fit when you only want the strongest matches.</div>
        <div class="scan-options" style="margin-top:.85rem">
          <label>Scan range
            <select id="d-days">
              <option value="30" selected>Practical pool</option>
              <option value="14">Wider recent pool</option>
              <option value="7">Fresh only</option>
              <option value="3">Very fresh only</option>
            </select>
          </label>
          <label>Fit threshold
            <select id="d-min_score">
              <option value="2" selected>Show maybes</option>
              <option value="3">Good fit and up</option>
              <option value="5">Strong only</option>
            </select>
          </label>
        </div>
      </div>
      <div class="card-actions" style="justify-content:flex-end;margin:0">
        <button class="primary" onclick="runDigest()">Scan now</button>
      </div>
    </div>
    <div class="actions">
      <button class="ghost" onclick="loadDigests()">Refresh past scans</button>
    </div>
    <div id="digestStatus"></div>
    <h3 style="margin-top:1.5rem;">Past scans</h3>
    <div id="digestTable"></div>
  </section>

</main>
</div>

<div class="modal-backdrop" id="modal">
  <div class="modal">
    <h3 id="modalTitle"></h3>
    <div id="modalBody"></div>
    <div class="modal-actions">
      <button class="ghost" onclick="closeModal()">Cancel</button>
      <button class="primary" id="modalConfirm">Confirm</button>
    </div>
  </div>
</div>

<script>
const PROJECT_ROOT = __PROJECT_ROOT_JSON__;
const STATE = { profiles: ['technical_services'], statuses: [], env: 'prod' };
const STATUS_LABELS = {
  tracking: 'Tracking',
  assessing: 'Assessing fit',
  pursuing: 'Writing response',
  submitted: 'Submitted',
  won: 'Won',
  lost: 'Lost',
  withdrawn: 'Withdrawn',
  expired: 'Expired'
};
const PROFILE_LABELS = {
  technical_services: 'Technical services',
  elastic_only: 'Elastic / search only'
};

function applyTheme(theme) {
  const normalized = theme === 'dark' ? 'dark' : 'light';
  document.documentElement.dataset.theme = normalized;
  localStorage.setItem('swcb-theme', normalized);
  const toggle = document.getElementById('themeToggle');
  if (toggle) toggle.textContent = normalized === 'dark' ? 'Light mode' : 'Dark mode';
}

function toggleTheme() {
  applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
}

applyTheme(localStorage.getItem('swcb-theme') || 'dark');

function startLeadScan() {
  setTab('digest');
  setTimeout(() => runDigest(), 50);
}

async function copyText(text, label='Copied') {
  await navigator.clipboard.writeText(text);
  showToast(label);
}

function copyStarterPrompt() {
  const text = `Use the technical-contract-research MCP tools and the Stormwind Contracting profile in ${PROJECT_ROOT}. Start by reading PROFILE.md, criteria/TECHNICAL_SERVICES_PROFILE.md, docs/DOCUMENT_INDEX.md, and tasks/. Search for realistic first-contract technical-services opportunities, reject weak keyword-only matches, verify public notice details, and update the local dashboard/watchlist with realistic leads and notes.`;
  copyText(text, 'Starter prompt copied');
}

function copyPath(relPath) {
  const cleanRoot = PROJECT_ROOT.replace(/[\\\/]$/, '');
  copyText(cleanRoot + '\\\\' + relPath.replace(/\//g, '\\\\'), 'Path copied');
}

async function openArtifact(path) {
  try {
    await api('/api/open-artifact', { method: 'POST', body: { path }});
    showToast('Opened ' + path);
  } catch (e) {
    showToast('Could not open: ' + e.message);
  }
}

async function api(url, opts={}) {
  const res = await fetch(url, {
    method: opts.method || 'GET',
    headers: {'Content-Type': 'application/json'},
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}

function setTab(name) {
  document.querySelectorAll('nav button').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
  document.querySelectorAll('.section').forEach(s => s.classList.toggle('active', s.id === 'tab-' + name));
  if (name === 'watchlist') loadWatchlist();
  if (name === 'saved') loadSavedSearches();
  if (name === 'digest') loadDigests();
  if (name === 'tasks') loadTasks('unblocked');
  if (name === 'ask') document.getElementById('askInput').focus();
}
document.querySelectorAll('nav button').forEach(b => b.addEventListener('click', () => setTab(b.dataset.tab)));
document.querySelectorAll('.chip[data-cmd]').forEach(c => c.addEventListener('click', () => {
  const cmd = c.dataset.cmd;
  document.getElementById('askInput').value = cmd;
  runAsk();
}));

const promptFileInput = document.getElementById('promptFileInput');
if (promptFileInput) {
  promptFileInput.addEventListener('change', event => savePromptFiles(event.target.files));
}
const promptDropZone = document.getElementById('promptDropZone');
if (promptDropZone) {
  ['dragenter', 'dragover'].forEach(name => promptDropZone.addEventListener(name, event => {
    event.preventDefault();
    promptDropZone.style.borderColor = 'var(--primary)';
    promptDropZone.style.background = 'var(--primary-soft)';
  }));
  ['dragleave', 'drop'].forEach(name => promptDropZone.addEventListener(name, event => {
    event.preventDefault();
    promptDropZone.style.borderColor = '';
    promptDropZone.style.background = '';
  }));
  promptDropZone.addEventListener('drop', event => savePromptFiles(event.dataTransfer.files));
}

function esc(s) { return (s||'').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

function reasonHtml(reasons) {
  return reasons.map(r => `<span class="${r.points < 0 ? 'neg' : ''}">${r.points>=0?'+':''}${r.points} ${esc(r.kind)}: ${esc(r.detail)}</span>`).join('');
}

function lanesHtml(lanes) {
  return (lanes||[]).map(l => `<span class="lane-chip">${esc(l)}</span>`).join('');
}

function workLocation(opp) {
  if (opp.work_location) return opp.work_location;
  if (opp.pop_city && opp.pop_state) return `${opp.pop_city}, ${opp.pop_state}`;
  if (opp.pop_state) return opp.pop_state;
  const text = `${opp.title || ''} ${opp.description || ''}`.toLowerCase();
  if (text.includes('remote') || text.includes('virtual')) return 'Remote/virtual mentioned';
  return 'Not listed';
}

function deliveryRead(opp) {
  if (opp.delivery_read) return opp.delivery_read;
  const text = `${opp.title || ''} ${opp.description || ''} ${opp.type || ''}`.toLowerCase();
  const riskPattern = new RegExp('top secret|ts/sci|secret clearance|facility clearance|24/7|nationwide|staff augmentation|enterprise-wide|managed services');
  if (riskPattern.test(text)) {
    return { label: 'Likely teaming', detail: 'Metadata has scale, clearance, or staffing flags. Verify scope.', level: 'team' };
  }
  if (/sources sought|rfi|special notice/.test(text)) {
    return { label: 'Monitor / shape', detail: 'Market research notice; useful for positioning, not a bid yet.', level: 'monitor' };
  }
  if ((opp.score || 0) >= 5) return { label: 'Plausibly solo', detail: 'High metadata fit; still verify SOW/PWS.', level: 'solo' };
  if ((opp.score || 0) >= 3) return { label: 'Solo or light help', detail: 'Worth checking documents for size, clearance, and schedule.', level: 'light_help' };
  return { label: 'Maybe / verify', detail: 'Weak metadata fit; inspect documents before spending time.', level: 'monitor' };
}

function profileLabel(profile) {
  return PROFILE_LABELS[profile] || profile || '-';
}

function statusLabel(status) {
  return STATUS_LABELS[status] || status || '-';
}

function humanScoreControl(noticeId, current='') {
  return `<label style="display:inline-flex;align-items:center;gap:.35rem;margin:0;text-transform:none;font-size:.8rem;font-weight:700;color:var(--mute)">
    My fit
    <select onchange='setHumanScore("${esc(noticeId)}", this.value)' style="min-height:34px;padding:.3rem .45rem">
      <option value="">not rated</option>
      ${[1,2,3,4,5].map(n => `<option value="${n}" ${String(current || '')===String(n)?'selected':''}>${n}</option>`).join('')}
    </select>
  </label>`;
}

function cardHtml(opp) {
  const band = opp.band || 'monitor';
  const due = opp.response_deadline || '-';
  const delivery = deliveryRead(opp);
  return `
    <article class="card opportunity-card">
      <div class="card-top">
        <div class="score-stack">
          <span class="badge ${band}">SCORE ${opp.score ?? '-'}</span>
          ${lanesHtml(opp.lanes)}
          <span class="fit-pill ${esc(delivery.level || '')}">${esc(delivery.label || '')}</span>
        </div>
        <div class="due-pill">Due ${esc(due)}</div>
      </div>
      <div class="title">${esc(opp.title || '(no title)')}</div>
      <div class="detail-grid">
        <div class="detail"><span>Agency</span><b>${esc(opp.department || '-')}</b></div>
        <div class="detail"><span>Work location</span><b>${esc(workLocation(opp))}</b></div>
        <div class="detail"><span>Plausibility</span><b>${esc(delivery.label || '-')}</b></div>
        <div class="detail"><span>Set-aside</span><b>${esc(opp.set_aside || '-')}</b></div>
      </div>
      <div class="meta-row"><b>Why that read:</b> ${esc(delivery.detail || '-')}</div>
      <div class="meta-row"><b>Type:</b> ${esc(opp.type || '-')} · <b>Posted:</b> ${esc(opp.posted_date || '-')} · <b>NAICS:</b> ${esc(opp.naics_code || '-')}</div>
      <div class="meta-row"><b>Notice:</b> <code>${esc(opp.notice_id)}</code>
        ${opp.link ? ` · <a class="row-link" target="_blank" href="${esc(opp.link)}">open notice</a>` : ''}</div>
      <div class="reasons">${reasonHtml(opp.reasons || [])}</div>
      <div class="card-actions">
        <button class="primary" onclick='addToWatchlist(${JSON.stringify(opp).replace(/'/g,"&#39;")})'>+ Watchlist</button>
        ${opp.link ? `<a class="ghost" target="_blank" href="${esc(opp.link)}">Open notice</a>` : ''}
      </div>
    </article>`;
}

async function runSearch() {
  const params = new URLSearchParams();
  ['keyword','naics','state','set_aside','type','days','min_score','profile','limit'].forEach(f => {
    const el = document.getElementById('f-' + f);
    if (el && el.value !== '') params.set(f, el.value);
  });
  const sumEl = document.getElementById('searchSummary');
  sumEl.innerHTML = '<span class="spinner"></span>searching…';
  try {
    const data = await api('/api/search?' + params.toString());
    if (data.error) { sumEl.innerHTML = `<span style="color:var(--bad)">${esc(data.error)}</span>`; return; }
    sumEl.textContent = data.results.length
      ? `${data.results.length} leads matched · profile: ${profileLabel(data.profile)}`
      : `No leads matched those filters. Try a broader keyword, lower score, or longer posting window.`;
    document.getElementById('searchResults').innerHTML =
      data.results.length ? data.results.map(cardHtml).join('') : `<div class="empty">No matches.</div>`;
  } catch (e) {
    sumEl.innerHTML = `<span style="color:var(--bad)">${esc(e.message)}</span>`;
  }
}

function resetFilters() {
  ['keyword','naics','state','set_aside','type'].forEach(f => document.getElementById('f-' + f).value = '');
  document.getElementById('f-days').value = 30;
  document.getElementById('f-min_score').value = 2;
  document.getElementById('f-limit').value = 50;
}

async function addToWatchlist(opp) {
  try {
    await api('/api/watchlist', { method: 'POST', body: {
      opportunity: { notice_id: opp.notice_id, title: opp.title, sol_number: opp.sol_number,
                      department: opp.department, naics_code: opp.naics_code,
                      set_aside: opp.set_aside, response_deadline: opp.response_deadline,
                      link: opp.link },
      status: 'tracking', score: opp.score, band: opp.band, lanes: opp.lanes,
    }});
    showToast('Added to watchlist');
    refreshOverview();
  } catch (e) { showToast('Error: ' + e.message); }
}

function showToast(msg) {
  const t = document.createElement('div');
  t.textContent = msg;
  t.className = 'toast';
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 2500);
}

async function loadWatchlist() {
  const status = document.getElementById('w-status').value;
  const url = '/api/watchlist' + (status ? '?status=' + encodeURIComponent(status) : '');
  const data = await api(url);
  const target = document.getElementById('watchlistTable');
  if (!data.length) { target.innerHTML = '<div class="empty">No watchlist entries yet. Add some from Search.</div>'; return; }
  const rows = data.map(e => `
    <tr>
      <td><span class="badge status">${esc(statusLabel(e.status))}</span></td>
      <td>${esc(e.title || '-')}<br><small style="color:var(--mute)">${esc(e.notice_id)}${e.link ? ` · <a class="row-link" target="_blank" href="${esc(e.link)}">notice</a>` : ''}</small></td>
      <td>
        Machine: ${e.score ?? '-'} ${e.band ? `<span class="badge ${e.band}" style="margin-left:.25rem">${e.band}</span>` : ''}<br>
        ${humanScoreControl(e.notice_id, e.human_score)}
      </td>
      <td>${esc(e.response_deadline || '-')}</td>
      <td>${esc(e.naics_code || '-')}<br><small style="color:var(--mute)">${esc(e.set_aside || '')}</small></td>
      <td>
        <select onchange='changeStatus("${esc(e.notice_id)}", this.value)'>
          ${STATE.statuses.map(s => `<option ${s===e.status?'selected':''} value="${s}">${statusLabel(s)}</option>`).join('')}
        </select>
        <button class="ghost" onclick='addNote("${esc(e.notice_id)}")' style="margin-left:.25rem;padding:.3rem .55rem;font-size:.78rem;">+ note</button>
        <button class="ghost" onclick='removeEntry("${esc(e.notice_id)}")' style="margin-left:.25rem;padding:.3rem .55rem;font-size:.78rem;color:var(--bad)">remove</button>
      </td>
    </tr>`).join('');
  target.innerHTML = `<table>
    <thead><tr><th>Stage</th><th>Lead</th><th>Fit</th><th>Due</th><th>NAICS / Set-aside</th><th>Actions</th></tr></thead>
    <tbody>${rows}</tbody></table>`;
  target.innerHTML = `<div class="table-wrap">${target.innerHTML}</div>`;
}

async function changeStatus(noticeId, status) {
  await api('/api/watchlist/status', { method: 'POST', body: { notice_id: noticeId, status }});
  showToast('Status updated');
  loadWatchlist();
  refreshOverview();
}
async function setHumanScore(noticeId, humanScore) {
  await api('/api/watchlist/human-score', { method: 'POST', body: { notice_id: noticeId, human_score: humanScore }});
  showToast(humanScore ? 'Human score saved' : 'Human score cleared');
  loadWatchlist();
}
async function addNote(noticeId) {
  const text = prompt('Note for ' + noticeId + ':');
  if (!text) return;
  await api('/api/watchlist/note', { method: 'POST', body: { notice_id: noticeId, text }});
  showToast('Note saved');
}
async function removeEntry(noticeId) {
  if (!confirm('Remove this entry?')) return;
  await api('/api/watchlist/remove', { method: 'POST', body: { notice_id: noticeId }});
  showToast('Removed');
  loadWatchlist();
  refreshOverview();
}

function openSaveSearch() {
  const filters = {};
  ['keyword','naics','state','set_aside','type','days'].forEach(f => {
    const el = document.getElementById('f-' + f);
    if (el && el.value !== '') filters[f === 'type' ? 'notice_type' : f] = el.value;
  });
  const profile = document.getElementById('f-profile').value;
  const minScore = document.getElementById('f-min_score').value;
  document.getElementById('modalTitle').textContent = 'Save current filters';
  document.getElementById('modalBody').innerHTML = `
    <label>Name<input id="save-name" placeholder="elastic-weekly"></label>
    <label>Description<input id="save-desc"></label>
    <p style="font-size:.85rem;color:var(--mute);margin-top:.75rem">Filters: <code>${esc(JSON.stringify(filters))}</code><br>profile=${esc(profile)} · min_score=${esc(minScore)}</p>`;
  document.getElementById('modal').classList.add('show');
  document.getElementById('modalConfirm').onclick = async () => {
    const name = document.getElementById('save-name').value.trim();
    if (!name) { showToast('Name required'); return; }
    await api('/api/saved-searches', { method: 'POST', body: {
      name, description: document.getElementById('save-desc').value,
      filters, profile, min_score: parseInt(minScore || '0', 10),
    }});
    closeModal();
    showToast('Saved');
  };
}
function closeModal() { document.getElementById('modal').classList.remove('show'); }

function promptNameFromFile(fileName) {
  return fileName.replace(/\.(txt|md|markdown)$/i, '').replace(/[_-]+/g, ' ').trim() || fileName;
}

async function savePromptFile(file) {
  const text = await file.text();
  const promptText = text.trim();
  if (!promptText) {
    showToast(file.name + ' is empty');
    return;
  }
  const name = promptNameFromFile(file.name);
  await api('/api/saved-searches', { method: 'POST', body: {
    name,
    description: promptText.slice(0, 180),
    filters: { prompt_text: promptText, source_file: file.name },
    profile: 'technical_services',
    min_score: 0,
  }});
  showToast('Saved prompt: ' + name);
}

async function savePromptFiles(files) {
  const accepted = Array.from(files || []).filter(file =>
    /\.(txt|md|markdown)$/i.test(file.name) || file.type.startsWith('text/')
  );
  if (!accepted.length) {
    showToast('Drop .txt or .md prompt files');
    return;
  }
  for (const file of accepted) {
    await savePromptFile(file);
  }
  loadSavedSearches();
  refreshOverview();
}

async function loadSavedSearches() {
  const data = await api('/api/saved-searches');
  const target = document.getElementById('savedSearchTable');
  if (!data.length) { target.innerHTML = '<div class="empty">No prompt files or saved searches yet. Drop a .txt or .md prompt above.</div>'; return; }
  const rows = data.map(s => `
    <tr>
      <td><b>${esc(s.name)}</b><br><small style="color:var(--mute)">${esc(s.description || '')}</small></td>
      <td>${savedSearchSummary(s)}</td>
      <td>${s.filters && s.filters.prompt_text ? 'Prompt file' : 'Structured search'}<br><small style="color:var(--mute)">${esc(profileLabel(s.profile))}</small></td>
      <td>${esc(s.last_run_at || 'never')}</td>
      <td>
        <button class="primary" style="font-size:.8rem" onclick='runSaved(${JSON.stringify(s)})'>${s.filters && s.filters.prompt_text ? 'Use prompt' : 'Run search'}</button>
        <button class="ghost" style="font-size:.8rem;color:var(--bad)" onclick='deleteSaved("${esc(s.name)}")'>Delete</button>
      </td>
    </tr>`).join('');
  target.innerHTML = `<table>
    <thead><tr><th>Name</th><th>Contents</th><th>Kind</th><th>Last used</th><th>Actions</th></tr></thead>
    <tbody>${rows}</tbody></table>`;
  target.innerHTML = `<div class="table-wrap">${target.innerHTML}</div>`;
}
function savedSearchSummary(s) {
  const filters = s.filters || {};
  if (filters.prompt_text) {
    const preview = String(filters.prompt_text).replace(/\s+/g, ' ').slice(0, 240);
    return `<div>${esc(preview)}${String(filters.prompt_text).length > 240 ? '...' : ''}</div>
      <small style="color:var(--mute)">${filters.source_file ? 'from ' + esc(filters.source_file) : 'prompt text'}</small>`;
  }
  return `<code>${esc(JSON.stringify(filters))}</code><br><small style="color:var(--mute)">minimum machine score ${esc(String(s.min_score))}</small>`;
}
function runSaved(s) {
  if (s.filters && s.filters.prompt_text) {
    setTab('ask');
    document.getElementById('askInput').value = s.filters.prompt_text;
    document.getElementById('askInput').focus();
    return;
  }
  setTab('search');
  ['keyword','naics','state','set_aside'].forEach(f => {
    document.getElementById('f-' + f).value = s.filters[f] || '';
  });
  document.getElementById('f-type').value = s.filters.notice_type || s.filters.type || '';
  if (s.filters.days != null) document.getElementById('f-days').value = s.filters.days;
  document.getElementById('f-profile').value = s.profile;
  document.getElementById('f-min_score').value = s.min_score;
  runSearch();
}
async function deleteSaved(name) {
  if (!confirm('Delete saved search ' + name + '?')) return;
  await api('/api/saved-searches/delete', { method: 'POST', body: { name }});
  showToast('Deleted');
  loadSavedSearches();
}

async function runDigest() {
  const status = document.getElementById('digestStatus');
  status.innerHTML = '<span class="spinner"></span>running the profile-based scan…';
  try {
    const data = await api('/api/digest/run', { method: 'POST', body: {
      profile: document.getElementById('d-profile').value,
      days: parseInt(document.getElementById('d-days').value, 10),
      min_score: parseInt(document.getElementById('d-min_score').value, 10),
    }});
    const laneSummary = Object.entries(data.lane_counts || {})
      .map(([lane, count]) => `<span class="lane-chip">${esc(lane)}: ${count}</span>`).join('');
    status.innerHTML = `<div class="card">
      <div class="title">Lead scan complete</div>
      <div class="meta-row">${esc(data.summary || '')}</div>
      <div class="meta-row">Checked <b>${data.scanned}</b> notices in this scan range and found <b>${data.shown}</b> leads that cleared the fit threshold.</div>
      <div class="score-stack" style="margin-top:.6rem">${laneSummary || '<span class="lane-chip">No lane matches</span>'}</div>
    </div>
    <div style="margin-top:1rem">${(data.items || []).length ? data.items.slice(0, 25).map(cardHtml).join('') : '<div class="empty">No leads met this fit threshold. Try “Show maybes” or “Wider net.”</div>'}</div>`;
    loadDigests();
    refreshOverview();
  } catch (e) {
    status.innerHTML = `<span style="color:var(--bad)">${esc(e.message)}</span>`;
  }
}

async function loadDigests() {
  const data = await api('/api/digests');
  const target = document.getElementById('digestTable');
  if (!data.length) { target.innerHTML = '<div class="empty">No past scans yet. Run Scan now and it will show up here.</div>'; return; }
  target.innerHTML = `<div class="past-scan-grid">${data.map(d => `
    <article class="card past-scan" onclick="openPastScan(${d.id})">
      <div class="card-top">
        <span class="badge promising">${d.candidates_shown} leads</span>
        <span class="due-pill">${esc(shortDateTime(d.run_at))}</span>
      </div>
      <div class="title">${esc(profileLabel(d.profile))}</div>
      <div class="meta-row">${esc(d.summary || `${d.candidates_shown} leads found from ${d.candidates_scanned} notices checked`)}</div>
      <div class="card-actions"><button class="ghost" onclick="event.stopPropagation(); openPastScan(${d.id})">Open scan</button></div>
    </article>`).join('')}</div>`;
}

function shortDateTime(value) {
  if (!value) return '-';
  return String(value).replace('T', ' ').slice(0, 16);
}

function openPastScan(id) {
  window.open('/api/digest/report?id=' + encodeURIComponent(id), '_blank', 'noopener');
}

// ----- Ask command palette -----
async function runAsk() {
  const txt = document.getElementById('askInput').value;
  if (!txt.trim()) return;
  const out = document.getElementById('askOutput');
  out.innerHTML = '<div class="ask-output"><span class="spinner"></span>running…</div>';
  try {
    const data = await api('/api/ask', { method: 'POST', body: { text: txt }});
    out.innerHTML = renderAsk(data);
  } catch (e) {
    out.innerHTML = `<div class="ask-output" style="color:var(--bad)">${esc(e.message)}</div>`;
  }
}

function renderAsk(data) {
  if (!data) return '<div class="ask-output">(no response)</div>';
  let head = `<div class="ask-output"><b>${esc(data.summary || data.kind || '')}</b>`;
  const k = data.kind || '';
  const r = data.results;
  if (k === 'tasks/unblocked' || k === 'tasks/list') {
    if (!r || !r.length) return head + '<div class="hint">(no tasks)</div></div>';
    return head + '<div style="margin-top:.6rem">' + r.map(taskRow).join('') + '</div></div>';
  }
  if (k === 'watchlist/list') {
    if (!r || !r.length) return head + '<div class="hint">(empty)</div></div>';
    return head + '<div style="margin-top:.6rem">' + r.map(watchRow).join('') + '</div></div>';
  }
  if (k === 'score') {
    if (!r || !r.length) return head + '<div class="hint">(no matches)</div></div>';
    return head + '<div style="margin-top:.6rem">' + r.slice(0,8).map(cardHtml).join('') + '</div></div>';
  }
  if (k === 'usaspending/incumbents') {
    return head + '<div style="margin-top:.6rem">' + (r || []).slice(0, 12).map(awardRow).join('') + '</div></div>';
  }
  if (k === 'ecfr/section') {
    return head + `<div style="margin-top:.6rem">
      <div class="meta-row"><b>${esc(r.citation || '')}</b>${r.heading ? ' — ' + esc(r.heading) : ''}</div>
      <pre>${esc((r.text || '').slice(0, 4000))}</pre>
    </div></div>`;
  }
  if (k === 'digest/run') {
    return head + `<div class="meta-row"><b>${r.shown}</b> leads found from <b>${r.scanned}</b> recent notices checked.</div></div>`;
  }
  if (k === 'help') {
    return head + '<ul style="margin-top:.5rem;padding-left:1.25rem;font-size:.88rem;line-height:1.6">'
      + (r.examples || []).map(x => `<li><code>${esc(x)}</code></li>`).join('') + '</ul></div>';
  }
  return head + `<pre style="margin-top:.6rem">${esc(JSON.stringify(r, null, 2))}</pre></div>`;
}

function taskRow(t) {
  return `<div class="card" style="padding:.7rem .85rem">
    <span class="badge status">${esc(t.status)}</span>
    <span style="font-weight:600">${esc(t.id)}</span> — ${esc(t.title)}
    ${t.dependencies && t.dependencies.length ? `<div class="meta-row">deps: ${t.dependencies.map(esc).join(', ')}</div>` : ''}
  </div>`;
}
function watchRow(e) {
  return `<div class="card" style="padding:.7rem .85rem">
    <span class="badge status">${esc(statusLabel(e.status))}</span>
    ${e.band ? `<span class="badge ${e.band}">${esc(e.band)}</span>` : ''}
    <b>${esc(e.title || '-')}</b>
    <div class="meta-row">due ${esc(e.response_deadline || '-')} · ${esc(e.notice_id || '')}${e.human_score ? ' · my fit ' + esc(String(e.human_score)) + '/5' : ''}</div>
  </div>`;
}
function awardRow(a) {
  const amt = a.amount ? '$' + Number(a.amount).toLocaleString(undefined, {maximumFractionDigits: 0}) : '-';
  return `<div class="card" style="padding:.7rem .85rem">
    <b>${esc(amt)}</b> — ${esc(a.recipient_name || '-')}
    <div class="meta-row">${esc(a.agency || '-')} / ${esc(a.sub_agency || '-')}</div>
    <div class="meta-row">NAICS ${esc(a.naics || '-')} · ${esc(a.start_date || '-')} → ${esc(a.end_date || '-')}</div>
    ${a.description ? `<div class="meta-row">${esc(String(a.description).slice(0, 200))}</div>` : ''}
  </div>`;
}

// ----- Tasks tab -----
async function loadTasks(mode) {
  const sum = document.getElementById('tasksSummary');
  const list = document.getElementById('tasksList');
  sum.innerHTML = '<span class="spinner"></span>loading…';
  let url = '/api/tasks';
  if (mode === 'unblocked') url = '/api/tasks/unblocked';
  else if (mode && mode !== 'all') url = '/api/tasks?status=' + encodeURIComponent(mode);
  try {
    const data = await api(url);
    sum.textContent = (mode === 'unblocked' ? 'Next steps ready now: ' : (mode || 'all') + ': ') + data.length;
    if (!data.length) { list.innerHTML = '<div class="empty">No tasks in this view.</div>'; return; }
    list.innerHTML = data.map(t => `
      <div class="card">
        <span class="badge status">${esc(t.status)}</span>
        <span class="badge ${t.priority === 'high' ? 'strong' : (t.priority === 'medium' ? 'promising' : 'monitor')}">${esc(t.priority)}</span>
        <div class="title">${esc(t.id)} — ${esc(t.title)}</div>
        <div class="meta-row"><b>type:</b> ${esc(t.type)} · <b>effort:</b> ${esc(t.effort)} · <b>deps:</b> ${(t.dependencies || []).map(esc).join(', ') || '-'}</div>
        <div class="meta-row"><b>tags:</b> ${(t.tags || []).map(esc).join(', ') || '-'} · <b>updated:</b> ${esc(t.updated || '-')}</div>
        <div class="card-actions">
          ${STATE.taskStatuses.map(s => s === t.status ? '' :
            `<button class="ghost" onclick='setTaskStatus("${esc(t.id)}","${s}")' style="font-size:.78rem">→ ${s}</button>`
          ).join('')}
        </div>
      </div>`).join('');
  } catch (e) {
    sum.innerHTML = `<span style="color:var(--bad)">${esc(e.message)}</span>`;
  }
}
async function setTaskStatus(id, status) {
  const note = prompt('Optional note for ' + id + ' → ' + status + ' (Cancel to skip):');
  if (note === null) return; // user cancelled
  await api('/api/tasks/status', { method: 'POST', body: { task_id: id, status, note }});
  showToast(id + ' → ' + status);
  loadTasks('all');
  refreshOverview();
}

// Note: dashboard exposes valid task statuses via a fallback hardcoded list,
// since they're not in /api/profiles. Keep aligned with tasks_lib.VALID_STATUSES.
STATE.taskStatuses = ['planned','in-progress','blocked','pending','done','dropped','unknown'];

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

async function refreshOverview() {
  try {
    const [watchlist, tasks] = await Promise.all([
      api('/api/watchlist'),
      api('/api/tasks/unblocked'),
    ]);
    setText('statWatchlist', watchlist.length);
    setText('statTasks', tasks.length);
    const askOut = document.getElementById('askOutput');
    if (askOut && !askOut.innerHTML.trim()) {
      askOut.innerHTML = renderAsk({
        kind: 'tasks/unblocked',
        summary: 'Next actionable workstreams',
        results: tasks,
      });
    }
  } catch (e) {
    setText('statWatchlist', '--');
    setText('statTasks', '--');
  }
}

async function init() {
  try {
    const meta = await api('/api/profiles');
    STATE.profiles = meta.profiles;
    STATE.statuses = meta.statuses;
    STATE.env = meta.env || 'prod';
    ['f-profile','d-profile'].forEach(id => {
      const sel = document.getElementById(id);
      sel.innerHTML = STATE.profiles.map(p => `<option value="${p}">${profileLabel(p)}</option>`).join('');
      if (STATE.profiles.includes('technical_services')) sel.value = 'technical_services';
    });
    document.getElementById('w-status').innerHTML =
      '<option value="">all stages</option>' + STATE.statuses.map(s => `<option value="${s}">${statusLabel(s)}</option>`).join('');
    const envName = STATE.env === 'dev' ? 'DEV' : 'PROD';
    document.getElementById('dbMeta').textContent = `${envName} · local SAM mirror`;
    const envBadge = document.getElementById('envBadge');
    if (envBadge) envBadge.innerHTML = `<span class="ai-dot"></span>${envName}`;
    setText('statProfiles', STATE.profiles.length);
    setText('statProfileNote', STATE.profiles.map(profileLabel).join(', '));
    refreshOverview();
  } catch (e) {
    document.getElementById('dbMeta').textContent = 'init error: ' + e.message;
  }
}
init();
</script>
</body>
</html>"""
    return html_doc.replace("__PROJECT_ROOT_JSON__", json.dumps(str(PROJECT_ROOT)))


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def serve(
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
    username: str = "stormwind",
    password: str | None = None,
    env: str = "prod",
) -> None:
    _set_runtime_env(env)
    _set_auth(username, password)
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    display_host = host if host not in {"0.0.0.0", "::"} else _detect_lan_ip()
    url = f"http://{display_host}:{port}/"
    auth_note = "auth=ON" if password else "auth=OFF (loopback only)"
    print(f"Dashboard serving at {url}  env={DASHBOARD_ENV}  ({auth_note}) — Ctrl+C to stop")
    if host in {"0.0.0.0", "::"} and not password:
        print(
            "WARNING: binding to all interfaces with NO password. "
            "Use --password or --password-env if other devices can reach this machine.",
            file=sys.stderr,
        )
    if open_browser:
        local_url = f"http://127.0.0.1:{port}/"
        threading.Timer(0.6, lambda: webbrowser.open(local_url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping…")
    finally:
        server.server_close()


def _detect_lan_ip() -> str:
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def main() -> None:
    import os
    parser = argparse.ArgumentParser(description="Local / LAN web dashboard.")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Bind address. Use 0.0.0.0 to expose on the LAN.")
    parser.add_argument("--env", choices=["prod", "dev"], default=os.environ.get("SWCB_ENV") or "prod",
                        help="Runtime state to use. prod uses data/watchlist.db; dev uses data/dev/watchlist.db.")
    parser.add_argument("--port", type=int, default=None,
                        help="Port to bind. Defaults to 8765 for prod, 8766 for dev.")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--username", default="stormwind")
    parser.add_argument("--password", default=None,
                        help="HTTP Basic password. Required when host is non-loopback.")
    parser.add_argument("--password-env", dest="password_env", default="SWCB_DASHBOARD_PASSWORD",
                        help="Env var to read the password from if --password is not given.")
    args = parser.parse_args()
    runtime_env = normalize_runtime_env(args.env)
    port = args.port if args.port is not None else _default_port_for_env(runtime_env)

    password = args.password
    if not password:
        password = os.environ.get(args.password_env)

    if args.host not in {"127.0.0.1", "localhost"} and not password:
        print(
            f"ERROR: when --host is non-loopback ({args.host}), a password is required. "
            f"Set --password or export {args.password_env}.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    serve(
        host=args.host, port=port,
        open_browser=not args.no_browser,
        username=args.username, password=password,
        env=runtime_env,
    )


if __name__ == "__main__":
    main()
