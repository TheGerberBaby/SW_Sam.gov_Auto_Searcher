"""Local web dashboard for browsing scored opportunities and managing the watchlist.

No external dependencies — uses the standard-library `http.server` plus
inline HTML/CSS/JS. Run with:

    python scripts/dashboard.py
    # then open http://127.0.0.1:8765/

Endpoints:
    GET  /                          → dashboard HTML
    GET  /api/search?...            → JSON search + score results
    GET  /api/watchlist             → list watchlist entries
    POST /api/watchlist             → add (or upsert) a notice
    POST /api/watchlist/status      → update status
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
from watchlist import Store, VALID_STATUSES  # noqa: E402
from digest import generate_digest  # noqa: E402
import tasks_lib  # noqa: E402
import usaspending  # noqa: E402
import ecfr  # noqa: E402
import base64  # noqa: E402
import secrets  # noqa: E402

PROJECT_ROOT = SCRIPT_DIR.parent
DB_PATH = PROJECT_ROOT / "data" / "contracts.db"
META_PATH = PROJECT_ROOT / "data" / "last_sync.txt"


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
        _STORE = Store()
    return _STORE


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
            elif parsed.path == "/api/saved-searches":
                self._send_json([s.to_dict() for s in _store().list_saved_searches()])
            elif parsed.path == "/api/profiles":
                self._send_json({"profiles": available_profiles(), "statuses": sorted(VALID_STATUSES)})
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
                )
                self._send_json({
                    "scanned": result["scanned"],
                    "shown": result["shown"],
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
                "watchlist          — current opportunity watchlist",
                "digest             — run today's scored digest",
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
    return r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#1e3a8a">
<title>SW Contracting Dashboard</title>
<style>
:root {
  --bg: #f8fafc; --card: #ffffff; --ink: #0f172a; --mute: #64748b;
  --line: #e2e8f0; --primary: #2563eb; --primary-dark: #1d4ed8;
  --strong: #16a34a; --promising: #2563eb; --monitor: #a16207; --reject: #94a3b8;
  --bad: #dc2626;
}
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       margin: 0; background: var(--bg); color: var(--ink); }
header { background: linear-gradient(135deg, #1e3a8a, #2563eb); color: white; padding: 1rem 2rem;
         display: flex; align-items: center; gap: 1rem; }
header h1 { font-size: 1.2rem; margin: 0; }
header .meta { margin-left: auto; font-size: .85rem; opacity: .85; }
nav { background: white; border-bottom: 1px solid var(--line); padding: 0 2rem; display: flex; gap: 0; }
nav button { background: none; border: none; padding: .85rem 1.1rem; font-size: .95rem; cursor: pointer;
             color: var(--mute); border-bottom: 3px solid transparent; }
nav button.active { color: var(--primary); border-bottom-color: var(--primary); font-weight: 600; }
nav button:hover { color: var(--primary-dark); }
main { padding: 1.5rem 2rem; max-width: 1400px; margin: 0 auto; }
.section { display: none; }
.section.active { display: block; }
.filters { background: white; border: 1px solid var(--line); border-radius: 10px;
           padding: 1rem 1.25rem; margin-bottom: 1rem; display: grid;
           grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: .75rem; }
.filters label { display: flex; flex-direction: column; font-size: .82rem; color: var(--mute); gap: .25rem; }
.filters input, .filters select { padding: .45rem .55rem; border: 1px solid var(--line);
                                   border-radius: 6px; font-size: .92rem; color: var(--ink); }
.actions { display: flex; gap: .5rem; flex-wrap: wrap; margin-bottom: 1rem; }
button.primary { background: var(--primary); color: white; border: none; padding: .55rem 1rem;
                 border-radius: 6px; font-weight: 600; cursor: pointer; }
button.primary:hover { background: var(--primary-dark); }
button.ghost { background: white; color: var(--primary); border: 1px solid var(--line);
               padding: .55rem 1rem; border-radius: 6px; cursor: pointer; }
button.ghost:hover { border-color: var(--primary); }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 10px;
        padding: 1rem 1.2rem; margin-bottom: .75rem; }
.card .title { font-weight: 600; font-size: 1rem; line-height: 1.3; margin: .2rem 0 .35rem; }
.badge { display: inline-block; padding: .15rem .55rem; border-radius: 999px; color: white;
         font-size: .75rem; font-weight: 600; margin-right: .4rem; }
.badge.strong { background: var(--strong); }
.badge.promising { background: var(--promising); }
.badge.monitor { background: var(--monitor); }
.badge.reject { background: var(--reject); }
.badge.status { background: var(--ink); }
.lane-chip { display: inline-block; background: #eef2ff; color: #1e40af; padding: .12rem .55rem;
             border-radius: 4px; font-size: .75rem; margin-right: .3rem; }
.meta-row { font-size: .85rem; color: var(--mute); margin: .15rem 0; }
.reasons { margin-top: .5rem; font-family: ui-monospace, monospace; font-size: .78rem; }
.reasons span { display: inline-block; padding: .1rem .45rem; margin: .12rem .25rem .12rem 0;
                background: #eef2ff; color: #1e40af; border-radius: 4px; }
.reasons span.neg { background: #fef2f2; color: #991b1b; }
.card .card-actions { margin-top: .5rem; display: flex; gap: .5rem; flex-wrap: wrap; }
.card .card-actions button { font-size: .8rem; padding: .35rem .7rem; }
.empty { text-align: center; color: var(--mute); padding: 2rem; background: white;
         border-radius: 10px; border: 1px dashed var(--line); }
.summary { font-size: .9rem; color: var(--mute); margin-bottom: .75rem; }
.row-link { color: var(--primary); text-decoration: none; }
.ask-box { background: white; border: 1px solid var(--line); border-radius: 12px;
           padding: 1rem 1.25rem; margin-bottom: 1rem; box-shadow: 0 1px 3px rgba(0,0,0,.04); }
.ask-box input { width: 100%; padding: .8rem 1rem; border: 1px solid var(--line);
                 border-radius: 8px; font-size: 1rem; }
.ask-box .hint { font-size: .82rem; color: var(--mute); margin: .5rem 0 0; }
.ask-output { background: white; border: 1px solid var(--line); border-radius: 10px;
              padding: 1rem 1.2rem; font-size: .9rem; }
.ask-output pre { background: #f1f5f9; padding: .6rem .8rem; border-radius: 6px;
                  font-size: .82rem; overflow-x: auto; }
.chip-row { display: flex; flex-wrap: wrap; gap: .35rem; margin-top: .5rem; }
.chip-row .chip { background: #eef2ff; color: #1e40af; padding: .25rem .6rem;
                  border-radius: 999px; font-size: .78rem; cursor: pointer; }
.chip-row .chip:hover { background: #c7d2fe; }

/* Mobile / tablet — width breakpoints */
@media (max-width: 720px) {
  header { padding: .8rem 1rem; }
  header h1 { font-size: 1.05rem; }
  header .meta { display: none; }
  nav { padding: 0; overflow-x: auto; -webkit-overflow-scrolling: touch; }
  nav button { padding: .7rem .85rem; font-size: .88rem; white-space: nowrap; flex: 0 0 auto; }
  main { padding: 1rem; }
  .filters { grid-template-columns: 1fr 1fr; padding: .8rem; gap: .55rem; }
  .filters label { font-size: .78rem; }
  .card { padding: .8rem .9rem; }
  .card .title { font-size: .95rem; }
  table { font-size: .82rem; }
  th, td { padding: .45rem .55rem; }
  button.primary, button.ghost { padding: .55rem .85rem; font-size: .92rem; }
  .actions { gap: .35rem; }
}
@media (max-width: 480px) {
  .filters { grid-template-columns: 1fr; }
}
.row-link:hover { text-decoration: underline; }
table { width: 100%; border-collapse: collapse; background: white; border-radius: 10px;
        overflow: hidden; border: 1px solid var(--line); }
th, td { text-align: left; padding: .65rem .8rem; font-size: .88rem; border-bottom: 1px solid var(--line); }
th { background: #f1f5f9; color: var(--mute); font-weight: 600; font-size: .75rem;
     text-transform: uppercase; letter-spacing: .03em; }
tr:hover { background: #f8fafc; }
.modal-backdrop { position: fixed; inset: 0; background: rgba(15,23,42,.5); display: none;
                  align-items: center; justify-content: center; z-index: 50; }
.modal-backdrop.show { display: flex; }
.modal { background: white; border-radius: 12px; padding: 1.25rem 1.5rem; max-width: 480px; width: 90%; }
.modal h3 { margin-top: 0; }
.modal label { display: block; margin-top: .75rem; font-size: .85rem; color: var(--mute); }
.modal input, .modal select, .modal textarea { width: 100%; padding: .5rem; border: 1px solid var(--line);
                                                 border-radius: 6px; font-size: .92rem; }
.modal-actions { margin-top: 1rem; display: flex; justify-content: flex-end; gap: .5rem; }
.spinner { display: inline-block; width: 14px; height: 14px; border: 2px solid #cbd5e1;
           border-top-color: var(--primary); border-radius: 50%;
           animation: spin .8s linear infinite; vertical-align: middle; margin-right: .35rem; }
@keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>
<header>
  <h1>SW Contracting Dashboard <small style="opacity:.7">v2.2</small></h1>
  <div class="meta" id="dbMeta">loading…</div>
</header>
<nav>
  <button data-tab="ask" class="active">Ask</button>
  <button data-tab="search">Search & Score</button>
  <button data-tab="tasks">Tasks</button>
  <button data-tab="watchlist">Watchlist</button>
  <button data-tab="saved">Saved</button>
  <button data-tab="digest">Digest</button>
</nav>
<main>

  <section id="tab-ask" class="section active">
    <div class="ask-box">
      <form id="askForm" onsubmit="event.preventDefault(); runAsk();">
        <input id="askInput" placeholder='try: next · digest · elastic · incumbents 541512 · far 52.212-2'
               autocomplete="off" autofocus>
      </form>
      <p class="hint">Type a command and hit enter. Tap a suggestion to fill the box.</p>
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
    <div class="filters">
      <label>Keyword<input id="f-keyword" placeholder="e.g. Elasticsearch"></label>
      <label>NAICS<input id="f-naics" placeholder="541512"></label>
      <label>State<input id="f-state" placeholder="VA"></label>
      <label>Set-aside<input id="f-set_aside" placeholder="SBA"></label>
      <label>Type<input id="f-type" placeholder="Solicitation"></label>
      <label>Posted within (days)<input id="f-days" type="number" value="30" min="1"></label>
      <label>Min score<input id="f-min_score" type="number" value="2"></label>
      <label>Profile
        <select id="f-profile"><option value="technical_services">technical_services</option></select>
      </label>
      <label>Limit<input id="f-limit" type="number" value="50" min="5"></label>
    </div>
    <div class="actions">
      <button class="primary" onclick="runSearch()">Search & Score</button>
      <button class="ghost" onclick="resetFilters()">Reset</button>
      <button class="ghost" onclick="openSaveSearch()">Save current filters…</button>
    </div>
    <div class="summary" id="searchSummary"></div>
    <div id="searchResults"></div>
  </section>

  <section id="tab-watchlist" class="section">
    <div class="actions">
      <label style="display:flex;align-items:center;gap:.4rem;">Status filter:
        <select id="w-status"><option value="">all</option></select>
      </label>
      <button class="primary" onclick="loadWatchlist()">Refresh</button>
    </div>
    <div id="watchlistTable"></div>
  </section>

  <section id="tab-tasks" class="section">
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
    <div class="actions">
      <button class="primary" onclick="loadSavedSearches()">Refresh</button>
    </div>
    <div id="savedSearchTable"></div>
  </section>

  <section id="tab-digest" class="section">
    <div class="filters">
      <label>Profile
        <select id="d-profile"><option value="technical_services">technical_services</option></select>
      </label>
      <label>Days back<input id="d-days" type="number" value="3"></label>
      <label>Min score<input id="d-min_score" type="number" value="3"></label>
    </div>
    <div class="actions">
      <button class="primary" onclick="runDigest()">Run digest now</button>
      <button class="ghost" onclick="loadDigests()">Refresh history</button>
    </div>
    <div id="digestStatus"></div>
    <h3 style="margin-top:1.5rem;">Recent runs</h3>
    <div id="digestTable"></div>
  </section>

</main>

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
const STATE = { profiles: ['technical_services'], statuses: [] };

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

function esc(s) { return (s||'').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

function reasonHtml(reasons) {
  return reasons.map(r => `<span class="${r.points < 0 ? 'neg' : ''}">${r.points>=0?'+':''}${r.points} ${esc(r.kind)}: ${esc(r.detail)}</span>`).join('');
}

function lanesHtml(lanes) {
  return (lanes||[]).map(l => `<span class="lane-chip">${esc(l)}</span>`).join('');
}

function cardHtml(opp) {
  const band = opp.band || 'monitor';
  const due = opp.response_deadline || '-';
  return `
    <div class="card">
      <span class="badge ${band}">${band.toUpperCase()} +${opp.score}</span>
      ${lanesHtml(opp.lanes)}
      <div class="title">${esc(opp.title || '(no title)')}</div>
      <div class="meta-row"><b>Agency:</b> ${esc(opp.department || '-')} / ${esc(opp.sub_tier || '-')}</div>
      <div class="meta-row"><b>NAICS:</b> ${esc(opp.naics_code || '-')} ·
        <b>Set-aside:</b> ${esc(opp.set_aside || '-')} · <b>Type:</b> ${esc(opp.type || '-')}</div>
      <div class="meta-row"><b>Posted:</b> ${esc(opp.posted_date || '-')} · <b>Response due:</b> ${esc(due)}</div>
      <div class="meta-row"><b>Notice:</b> <code>${esc(opp.notice_id)}</code>
        ${opp.link ? `· <a class="row-link" target="_blank" href="${esc(opp.link)}">open notice</a>` : ''}</div>
      <div class="reasons">${reasonHtml(opp.reasons || [])}</div>
      <div class="card-actions">
        <button class="primary" onclick='addToWatchlist(${JSON.stringify(opp).replace(/'/g,"&#39;")})'>+ Watchlist</button>
        ${opp.link ? `<a class="ghost" target="_blank" href="${esc(opp.link)}" style="text-decoration:none;padding:.35rem .7rem;border:1px solid var(--line);border-radius:6px;color:var(--primary)">Open notice</a>` : ''}
      </div>
    </div>`;
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
    sumEl.textContent = `${data.results.length} scored result(s) · profile=${data.profile}`;
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
  } catch (e) { showToast('Error: ' + e.message); }
}

function showToast(msg) {
  const t = document.createElement('div');
  t.textContent = msg;
  t.style.cssText = 'position:fixed;bottom:20px;right:20px;background:var(--ink);color:white;padding:.7rem 1rem;border-radius:8px;z-index:100;box-shadow:0 4px 10px rgba(0,0,0,.2);';
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
      <td><span class="badge status">${esc(e.status)}</span></td>
      <td>${esc(e.title || '-')}<br><small style="color:var(--mute)">${esc(e.notice_id)}${e.link ? ` · <a class="row-link" target="_blank" href="${esc(e.link)}">notice</a>` : ''}</small></td>
      <td>${e.score ?? '-'} ${e.band ? `<span class="badge ${e.band}" style="margin-left:.25rem">${e.band}</span>` : ''}</td>
      <td>${esc(e.response_deadline || '-')}</td>
      <td>${esc(e.naics_code || '-')}<br><small style="color:var(--mute)">${esc(e.set_aside || '')}</small></td>
      <td>
        <select onchange='changeStatus("${esc(e.notice_id)}", this.value)'>
          ${STATE.statuses.map(s => `<option ${s===e.status?'selected':''} value="${s}">${s}</option>`).join('')}
        </select>
        <button class="ghost" onclick='addNote("${esc(e.notice_id)}")' style="margin-left:.25rem;padding:.3rem .55rem;font-size:.78rem;">+ note</button>
        <button class="ghost" onclick='removeEntry("${esc(e.notice_id)}")' style="margin-left:.25rem;padding:.3rem .55rem;font-size:.78rem;color:var(--bad)">remove</button>
      </td>
    </tr>`).join('');
  target.innerHTML = `<table>
    <thead><tr><th>Status</th><th>Title</th><th>Score</th><th>Due</th><th>NAICS / Set-aside</th><th></th></tr></thead>
    <tbody>${rows}</tbody></table>`;
}

async function changeStatus(noticeId, status) {
  await api('/api/watchlist/status', { method: 'POST', body: { notice_id: noticeId, status }});
  showToast('Status updated');
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

async function loadSavedSearches() {
  const data = await api('/api/saved-searches');
  const target = document.getElementById('savedSearchTable');
  if (!data.length) { target.innerHTML = '<div class="empty">No saved searches yet.</div>'; return; }
  const rows = data.map(s => `
    <tr>
      <td><b>${esc(s.name)}</b><br><small style="color:var(--mute)">${esc(s.description || '')}</small></td>
      <td><code>${esc(JSON.stringify(s.filters))}</code></td>
      <td>${esc(s.profile)}<br><small style="color:var(--mute)">min=${s.min_score}</small></td>
      <td>${esc(s.last_run_at || 'never')}</td>
      <td>
        <button class="primary" style="font-size:.8rem" onclick='runSaved(${JSON.stringify(s)})'>Run</button>
        <button class="ghost" style="font-size:.8rem;color:var(--bad)" onclick='deleteSaved("${esc(s.name)}")'>Delete</button>
      </td>
    </tr>`).join('');
  target.innerHTML = `<table>
    <thead><tr><th>Name</th><th>Filters</th><th>Profile</th><th>Last run</th><th></th></tr></thead>
    <tbody>${rows}</tbody></table>`;
}
function runSaved(s) {
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
  status.innerHTML = '<span class="spinner"></span>generating digest…';
  try {
    const data = await api('/api/digest/run', { method: 'POST', body: {
      profile: document.getElementById('d-profile').value,
      days: parseInt(document.getElementById('d-days').value, 10),
      min_score: parseInt(document.getElementById('d-min_score').value, 10),
    }});
    status.innerHTML = `<div class="card">
      <div class="title">Digest generated</div>
      <div class="meta-row">Scanned: <b>${data.scanned}</b> · Shown: <b>${data.shown}</b></div>
      <div class="meta-row">HTML: <code>${esc(data.html_path)}</code></div>
      <div class="meta-row">Markdown: <code>${esc(data.markdown_path)}</code></div>
    </div>`;
    loadDigests();
  } catch (e) {
    status.innerHTML = `<span style="color:var(--bad)">${esc(e.message)}</span>`;
  }
}

async function loadDigests() {
  const data = await api('/api/digests');
  const target = document.getElementById('digestTable');
  if (!data.length) { target.innerHTML = '<div class="empty">No digests run yet.</div>'; return; }
  const rows = data.map(d => `
    <tr>
      <td>${esc(d.run_at)}</td>
      <td>${esc(d.profile)}</td>
      <td>${d.candidates_shown} / ${d.candidates_scanned}</td>
      <td><code style="font-size:.78rem">${esc(d.report_path || '')}</code></td>
    </tr>`).join('');
  target.innerHTML = `<table>
    <thead><tr><th>Run at</th><th>Profile</th><th>Shown / Scanned</th><th>Report path</th></tr></thead>
    <tbody>${rows}</tbody></table>`;
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
    return head + `<div class="meta-row">scanned: <b>${r.scanned}</b> · shown: <b>${r.shown}</b></div>
      <div class="meta-row">HTML: <code>${esc(r.html_path)}</code></div></div>`;
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
    <span class="badge status">${esc(e.status)}</span>
    ${e.band ? `<span class="badge ${e.band}">${esc(e.band)}</span>` : ''}
    <b>${esc(e.title || '-')}</b>
    <div class="meta-row">due ${esc(e.response_deadline || '-')} · ${esc(e.notice_id || '')}</div>
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
    sum.textContent = (mode === 'unblocked' ? 'next-actionable: ' : (mode || 'all') + ': ') + data.length;
    if (!data.length) { list.innerHTML = '<div class="empty">(no tasks)</div>'; return; }
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
}

// Note: dashboard exposes valid task statuses via a fallback hardcoded list,
// since they're not in /api/profiles. Keep aligned with tasks_lib.VALID_STATUSES.
STATE.taskStatuses = ['planned','in-progress','blocked','pending','done','dropped','unknown'];

async function init() {
  try {
    const meta = await api('/api/profiles');
    STATE.profiles = meta.profiles;
    STATE.statuses = meta.statuses;
    ['f-profile','d-profile'].forEach(id => {
      const sel = document.getElementById(id);
      sel.innerHTML = STATE.profiles.map(p => `<option value="${p}">${p}</option>`).join('');
    });
    document.getElementById('w-status').innerHTML =
      '<option value="">all</option>' + STATE.statuses.map(s => `<option value="${s}">${s}</option>`).join('');
    document.getElementById('dbMeta').textContent = 'profiles: ' + STATE.profiles.join(', ');
  } catch (e) {
    document.getElementById('dbMeta').textContent = 'init error: ' + e.message;
  }
}
init();
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def serve(
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
    username: str = "stormwind",
    password: str | None = None,
) -> None:
    _set_auth(username, password)
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    display_host = host if host not in {"0.0.0.0", "::"} else _detect_lan_ip()
    url = f"http://{display_host}:{port}/"
    auth_note = "auth=ON" if password else "auth=OFF (loopback only)"
    print(f"Dashboard serving at {url}  ({auth_note}) — Ctrl+C to stop")
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
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--username", default="stormwind")
    parser.add_argument("--password", default=None,
                        help="HTTP Basic password. Required when host is non-loopback.")
    parser.add_argument("--password-env", dest="password_env", default="SWCB_DASHBOARD_PASSWORD",
                        help="Env var to read the password from if --password is not given.")
    args = parser.parse_args()

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
        host=args.host, port=args.port,
        open_browser=not args.no_browser,
        username=args.username, password=password,
    )


if __name__ == "__main__":
    main()
