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
    GET  /downloads/<filename>      → download an authenticated report file
    GET  /api/vendors/profiles      → vendor-sourcing profiles + key status
    POST /api/vendors/source        → fresh vendors + generated outreach
    GET  /api/saved-searches        → list saved searches
    POST /api/saved-searches        → create/update saved search
    POST /api/saved-searches/delete → delete saved search
    GET  /api/profiles              → available scoring profiles
    GET  /manifest.webmanifest      → PWA manifest (install as a phone app)
    GET  /icon.svg, /icon-*.png     → app icons (generated, no image deps)
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sqlite3
import sys
import threading
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from scoring import LOCAL_TZ, available_profiles, bulk_score  # noqa: E402
from watchlist import Store, VALID_STATUSES, db_path_for_env, normalize_runtime_env  # noqa: E402
from digest import generate_digest, reports_dir_for_env  # noqa: E402
from dashboard_html import render_dashboard_html  # noqa: E402
import tasks_lib  # noqa: E402
import usaspending  # noqa: E402
import ecfr  # noqa: E402
import source_vendors  # noqa: E402
import vendor_jobs  # noqa: E402
import base64  # noqa: E402
import secrets  # noqa: E402

PROJECT_ROOT = SCRIPT_DIR.parent
DB_PATH = PROJECT_ROOT / "data" / "contracts.db"
META_PATH = PROJECT_ROOT / "data" / "last_sync.txt"
DOWNLOADS_DIR = PROJECT_ROOT / "reports"
SELECTED_CONTEXT_PATH = PROJECT_ROOT / "data" / "selected_contract_context.json"
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


def _read_selected_context() -> dict[str, Any] | None:
    if not SELECTED_CONTEXT_PATH.exists():
        return None
    try:
        return json.loads(SELECTED_CONTEXT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_selected_context(opportunity: dict[str, Any]) -> dict[str, Any]:
    if not opportunity.get("notice_id"):
        raise ValueError("selected opportunity must include notice_id")
    SELECTED_CONTEXT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "selected_at": datetime.now(LOCAL_TZ).isoformat(timespec="seconds"),
        "source": "dashboard",
        "opportunity": opportunity,
    }
    SELECTED_CONTEXT_PATH.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return payload


def _clear_selected_context() -> dict[str, Any]:
    try:
        SELECTED_CONTEXT_PATH.unlink()
    except FileNotFoundError:
        pass
    return {"selected_at": None, "opportunity": None}


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "SWContractingDashboard/2.3"

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
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
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

    def _send_download(self, path: Path) -> None:
        body = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, body: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=86400")
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
            if parsed.path in {"/", "/index.html", "/source-subs"}:
                self._send_html(render_dashboard_html(PROJECT_ROOT))
            elif parsed.path == "/manifest.webmanifest":
                self._send_bytes(json.dumps(_pwa_manifest()).encode("utf-8"),
                                 "application/manifest+json")
            elif parsed.path == "/icon.svg":
                self._send_bytes(_ICON_SVG.encode("utf-8"), "image/svg+xml")
            elif parsed.path in {"/apple-touch-icon.png", "/icon-180.png"}:
                self._send_bytes(_icon_png(180), "image/png")
            elif parsed.path == "/icon-192.png":
                self._send_bytes(_icon_png(192), "image/png")
            elif parsed.path == "/icon-512.png":
                self._send_bytes(_icon_png(512), "image/png")
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
            elif parsed.path == "/api/context/selected":
                self._send_json(_read_selected_context() or {"selected_at": None, "opportunity": None})
            elif parsed.path == "/api/digest/items":
                run = _store().get_digest_run(int(params.get("id") or 0))
                if not run:
                    self._send_json({"error": "not found"}, status=404)
                    return
                try:
                    items = json.loads(run.get("items_json") or "[]")
                except (json.JSONDecodeError, TypeError):
                    items = []
                self._send_json({
                    "id": run["id"],
                    "profile": run.get("profile"),
                    "source": run.get("source"),
                    "run_at": run.get("run_at"),
                    "summary": run.get("summary"),
                    "has_report": bool(run.get("report_path")),
                    "items": items,
                })
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
            elif parsed.path.startswith("/downloads/"):
                requested_name = unquote(parsed.path.removeprefix("/downloads/"))
                if not requested_name or Path(requested_name).name != requested_name:
                    self._send_json({"error": "not found"}, status=404)
                    return
                report_path = (DOWNLOADS_DIR / requested_name).resolve()
                report_path.relative_to(DOWNLOADS_DIR.resolve())
                if not report_path.is_file():
                    self._send_json({"error": "not found"}, status=404)
                    return
                self._send_download(report_path)
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
            elif parsed.path == "/api/vendors/profiles":
                self._send_json({
                    "places_configured": bool(source_vendors.get_places_api_key()),
                    "profiles": [
                        {"naics": naics, "label": profile["label"]}
                        for naics, profile in source_vendors.VENDOR_PROFILES.items()
                    ],
                })
            elif parsed.path == "/api/vendors/jobs":
                jobs = vendor_jobs.list_sourcing_jobs(
                    status=params.get("status") or None,
                    limit=int(params.get("limit") or 20),
                )
                self._send_json([_vendor_job_payload(job) for job in jobs])
            elif parsed.path == "/api/vendors/job":
                self._send_json(_vendor_job_payload(vendor_jobs.get_sourcing_job(params.get("id") or "")))
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
                    min_runway_days=int(payload.get("min_runway_days") or 25),
                    write=bool(payload.get("write", True)),
                    env=DASHBOARD_ENV,
                )
                self._send_json({
                    "env": result["env"],
                    "min_runway_days": result["min_runway_days"],
                    "scanned": result["scanned"],
                    "shown": result["shown"],
                    "summary": result["summary"],
                    "lane_counts": result["lane_counts"],
                    "items": result["items"],
                    "markdown_path": result["markdown_path"],
                    "html_path": result["html_path"],
                    "generated_at": result["generated_at"],
                })
            elif parsed.path == "/api/context/select":
                opportunity = payload.get("opportunity") or payload
                self._send_json(_write_selected_context(opportunity))
            elif parsed.path == "/api/context/clear":
                self._send_json(_clear_selected_context())
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
            elif parsed.path == "/api/vendors/source":
                try:
                    result = source_vendors.generate_vendor_package(
                        naics=payload.get("naics"),
                        service=payload.get("service"),
                        place=payload.get("place") or "",
                        due=payload.get("due"),
                        operator=payload.get("operator"),
                        max_results=int(payload.get("max_results") or 5),
                        script_only=bool(payload.get("script_only")),
                        allow_script_fallback=True,
                    )
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, status=400)
                    return
                except SystemExit as exc:
                    self._send_json({"error": str(exc)}, status=502)
                    return
                self._send_json(result)
            elif parsed.path == "/api/vendors/source-opportunity":
                try:
                    job = vendor_jobs.create_sourcing_job(
                        payload.get("opportunity") or {},
                        max_results=int(payload.get("max_results") or 5),
                    )
                except ValueError as exc:
                    self._send_json({"error": str(exc)}, status=400)
                    return
                except SystemExit as exc:
                    self._send_json({"error": str(exc)}, status=502)
                    return
                self._send_json(_vendor_job_payload(job))
            else:
                self._send_json({"error": "not found"}, status=404)
        except KeyError as exc:
            self._send_json({"error": f"missing field: {exc.args[0]}"}, status=400)
        except Exception as exc:  # noqa: BLE001
            self._send_json({"error": str(exc)}, status=500)


# ---------------------------------------------------------------------------
# Ask command router
# ---------------------------------------------------------------------------


def _vendor_job_payload(job: dict[str, Any]) -> dict[str, Any]:
    """Flatten a queued sourcing job for the phone dashboard."""
    package = dict(job.get("package") or {})
    return {
        **package,
        "job_id": job.get("job_id"),
        "job_status": job.get("status"),
        "opportunity": job.get("opportunity") or {},
        "future_chat_questions": job.get("future_chat_questions") or [],
        "contracting_officer_draft": job.get("contracting_officer_draft") or "",
        "agent_handoff_prompt": job.get("agent_handoff_prompt") or "",
        "report_filename": job.get("report_filename"),
        "report_download_url": (
            f"/downloads/{job['report_filename']}" if job.get("report_filename") else None
        ),
    }


def _normalize_ask(text: str) -> str:
    """Map plain-English phrasing onto the tiny ask grammar.

    Lets a first-time user type the way they talk ("what should I work
    on next?") instead of memorizing keywords. Returns a normalized
    command string, or the original text when nothing matches.
    """
    import re

    s = " ".join(text.strip().lower().split()).rstrip("?.!")
    if not s:
        return ""
    phrase_map = {
        "next": {
            "what should i work on", "what should i work on next", "what should i do",
            "what should i do next", "what do i do next", "what now", "whats next",
            "what is next", "next steps", "next step", "what to do", "what to do next",
        },
        "watchlist": {
            "show my pursuits", "my pursuits", "show pursuits", "what am i tracking",
            "show watchlist", "show my watchlist", "my watchlist", "what am i pursuing",
            "whats on my list", "what's on my list",
        },
        "digest": {
            "run todays scan", "run today's scan", "scan now", "todays leads",
            "today's leads", "scan", "find leads today", "run the scan", "run a scan",
            "scan today", "scan for leads",
        },
        "tasks": {"show my tasks", "my tasks", "all tasks", "list tasks"},
        "help": {
            "help me", "what can you do", "what can i ask", "what can i type",
            "how does this work", "what do i type", "what can i say",
        },
    }
    for target, phrases in phrase_map.items():
        if s in phrases:
            return target
    # "find / search (for / me) <keyword> (leads / contracts / opportunities)"
    m = re.match(r"^(?:find|search|look)\s+(?:for\s+|me\s+)?(.*)$", s)
    if m:
        kw = re.sub(r"\b(leads?|contracts?|opportunit(?:y|ies)|work|jobs?)\b", "", m.group(1)).strip()
        if kw:
            return f"search {kw}"
    return text.strip()


def _handle_ask(text: str) -> dict[str, Any]:
    """Route a free-text command to the right capability.

    This is intentionally pattern-matched, not LLM-driven — it works
    offline, costs nothing, and behaves predictably. The grammar is
    very small; phrases that don't match return a help response.
    """
    raw = _normalize_ask(text)
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
        result = generate_digest(profile="technical_services", days=3, min_score=3, min_runway_days=25, write=True)
        return {
            "kind": "digest/run",
            "summary": f"Digest: {result['shown']} of {result['scanned']} scored ≥ 3 with 25+ day runway",
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

    # — Incumbents by NAICS (e.g. "incumbents 561621") —
    if head in {"incumbents", "incumbent"}:
        naics = rest if rest else "561621"
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
    "camera", "cctv", "video surveillance", "video monitoring",
    "access control", "cabling", "cat6", "fiber", "low voltage", "vtc",
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
                "camera             — score search for 'camera' across last 60d",
                "score cabling      — score search for 'cabling'",
                "incumbents 561621  — USAspending top recipients for NAICS 561621",
                "far 52.212-2       — fetch FAR 52.212-2 text",
                "cfr 13 121.201     — fetch 13 CFR 121.201 (SBA size standards)",
            ],
        },
    }


# ---------------------------------------------------------------------------
# PWA assets — lets the dashboard install as a home-screen app on a phone
# ---------------------------------------------------------------------------


_ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
<stop offset="0" stop-color="#22d3ee"/><stop offset=".52" stop-color="#818cf8"/>
<stop offset="1" stop-color="#e879f9"/></linearGradient></defs>
<rect width="512" height="512" rx="112" fill="url(#g)"/>
<path d="M13.5 2 5 13.5h4.6L9 22l9.5-12.5h-5z" fill="#06080f"
 transform="translate(64,64) scale(16)"/>
</svg>"""

_ICON_PNG_CACHE: dict[int, bytes] = {}


def _icon_png(size: int) -> bytes:
    """Brand-gradient square icon, rendered with stdlib only (no Pillow)."""
    cached = _ICON_PNG_CACHE.get(size)
    if cached is not None:
        return cached
    import struct
    import zlib
    stops = [(0x22, 0xD3, 0xEE), (0x81, 0x8C, 0xF8), (0xE8, 0x79, 0xF9)]
    raw = bytearray()
    for y in range(size):
        raw.append(0)  # PNG row filter: none
        for x in range(size):
            t = (x + y) / (2 * (size - 1))
            seg, ft = (0, t / 0.52) if t <= 0.52 else (1, (t - 0.52) / 0.48)
            a, b = stops[seg], stops[seg + 1]
            raw += bytes(round(a[i] + (b[i] - a[i]) * ft) for i in range(3))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
           + chunk(b"IEND", b""))
    _ICON_PNG_CACHE[size] = png
    return png


def _pwa_manifest() -> dict[str, Any]:
    return {
        "name": "Stormwind Command",
        "short_name": "Stormwind",
        "description": "Federal technical-services workbench: scans, leads, pursuits, subs.",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#06080f",
        "theme_color": "#06080f",
        "icons": [
            {"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any"},
            {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
            {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
        ],
    }


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
    parser.add_argument("--allow-unauthenticated-lan", action="store_true",
                        help="Allow a non-loopback bind without HTTP Basic auth. Intended for "
                             "trusted home LANs / VPN (WireGuard) setups where the network is "
                             "the access control. Never use on a network you don't control.")
    args = parser.parse_args()
    runtime_env = normalize_runtime_env(args.env)
    port = args.port if args.port is not None else _default_port_for_env(runtime_env)

    password = args.password
    if not password:
        password = os.environ.get(args.password_env)

    if args.allow_unauthenticated_lan and args.host in {"0.0.0.0", "::"}:
        print(
            "WARNING: serving on ALL interfaces with NO password. Anyone on this "
            "machine's networks (LAN, VPN) can use the dashboard. Make sure the "
            "router does not forward this port to the internet.",
            file=sys.stderr,
        )

    if args.host not in {"127.0.0.1", "localhost"} and not password and not args.allow_unauthenticated_lan:
        print(
            f"ERROR: when --host is non-loopback ({args.host}), a password is required. "
            f"Set --password, export {args.password_env}, or explicitly pass "
            "--allow-unauthenticated-lan.",
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
