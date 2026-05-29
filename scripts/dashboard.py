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


def _store() -> Store:
    global _STORE
    if _STORE is None:
        _STORE = Store()
    return _STORE


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "SWContractingDashboard/2.0"

    # quieter logging
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        sys.stderr.write(f"[{self.log_date_time_string()}] {format % args}\n")

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
            else:
                self._send_json({"error": "not found"}, status=404)
        except Exception as exc:  # noqa: BLE001
            self._send_json({"error": str(exc)}, status=500)

    def do_POST(self) -> None:  # noqa: N802
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
            else:
                self._send_json({"error": "not found"}, status=404)
        except KeyError as exc:
            self._send_json({"error": f"missing field: {exc.args[0]}"}, status=400)
        except Exception as exc:  # noqa: BLE001
            self._send_json({"error": str(exc)}, status=500)


# ---------------------------------------------------------------------------
# Single-file HTML/CSS/JS dashboard
# ---------------------------------------------------------------------------


def _render_dashboard_html() -> str:
    return r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
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
  <h1>SW Contracting Dashboard <small style="opacity:.7">v2</small></h1>
  <div class="meta" id="dbMeta">loading…</div>
</header>
<nav>
  <button data-tab="search" class="active">Search & Score</button>
  <button data-tab="watchlist">Watchlist</button>
  <button data-tab="saved">Saved Searches</button>
  <button data-tab="digest">Digest</button>
</nav>
<main>

  <section id="tab-search" class="section active">
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
}
document.querySelectorAll('nav button').forEach(b => b.addEventListener('click', () => setTab(b.dataset.tab)));

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
    runSearch();
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


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    url = f"http://{host}:{port}/"
    print(f"Dashboard serving at {url}  (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping…")
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Local web dashboard.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    serve(host=args.host, port=args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
