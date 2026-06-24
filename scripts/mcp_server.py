"""MCP server for technical-services SAM.gov research and document evidence."""

from __future__ import annotations

import io
import json
import os
import sqlite3
from contextlib import redirect_stdout
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from mcp.server.fastmcp import FastMCP

from document_store import (
    DocumentStoreError,
    ElasticDocumentStore,
    Settings,
    command_ingest,
    command_search,
)
from scoring import available_profiles, bulk_score, score_opportunity
from watchlist import Store as WatchlistStore, VALID_STATUSES
from digest import generate_digest
from panel.service import PanelService
from panel.store import PanelStore
import tasks_lib
import usaspending
import ecfr
import vendor_jobs

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_DIR / "data" / "contracts.db"
META_PATH = PROJECT_DIR / "data" / "last_sync.txt"
PROFILE_PATH = PROJECT_DIR / "criteria" / "TECHNICAL_SERVICES_PROFILE.md"
ELASTIC_PROFILE_PATH = PROJECT_DIR / "criteria" / "ELASTIC_LEAD_PROFILE.md"
PROMPT_PATH = PROJECT_DIR / "prompts" / "technical_services_lead_research.md"
USER_TIMEZONE = os.getenv("USER_TIMEZONE", "America/New_York")
LOCAL_TIMEZONE = ZoneInfo(USER_TIMEZONE)

mcp = FastMCP(
    "technical-contract-research",
    instructions=(
        "Research public federal small-team field-installation opportunities for the operator. "
        "Prioritize security cameras, CCTV/video monitoring, access control, "
        "structured cabling, low-voltage data cabling, and bounded fiber work. "
        "Reject closed, unrelated, oversized, or weak keyword-only matches. "
        "After each user-requested contract-lead scan, "
        "call publish_research_scan exactly once with the final curated results, "
        "including an empty list when no supported fit is found. Do not publish "
        "intermediate keyword-search results."
    ),
)


def _deadline_status(value: str | None) -> tuple[bool | None, str]:
    local_now = datetime.now(LOCAL_TIMEZONE)
    if not value:
        return None, "response deadline not provided"
    candidate = value.strip().replace("Z", "+00:00")
    try:
        deadline = datetime.fromisoformat(candidate)
    except ValueError:
        try:
            deadline_date = date.fromisoformat(candidate[:10])
        except ValueError:
            return None, f"unparseable response deadline: {value}"
        is_open = deadline_date >= local_now.date()
        return is_open, "open by date" if is_open else "response deadline passed"
    if deadline.tzinfo is None:
        is_open = deadline.date() >= local_now.date()
    else:
        is_open = deadline.astimezone(LOCAL_TIMEZONE) >= local_now
    return is_open, "open" if is_open else "response deadline passed"


def _document_store() -> ElasticDocumentStore:
    return ElasticDocumentStore(Settings.from_env())


def _captured_json(function: Any, store: ElasticDocumentStore, args: SimpleNamespace) -> dict[str, Any]:
    output = io.StringIO()
    with redirect_stdout(output):
        function(store, args)
    return json.loads(output.getvalue())


@mcp.resource("technical-contracts://profiles/service-fit")
def technical_services_profile_resource() -> str:
    """Active opportunity-fit profile for the operator's field-installation work."""
    return PROFILE_PATH.read_text(encoding="utf-8")


@mcp.prompt()
def find_technical_services_leads() -> str:
    """Research public SAM.gov field-installation opportunities for the operator."""
    return PROMPT_PATH.read_text(encoding="utf-8")


@mcp.tool()
def get_technical_services_profile() -> str:
    """Return the operator's active field-installation lead-selection profile."""
    return PROFILE_PATH.read_text(encoding="utf-8")


@mcp.tool()
def get_elastic_lead_profile() -> str:
    """Return the narrower Elastic/search/observability-only profile."""
    return ELASTIC_PROFILE_PATH.read_text(encoding="utf-8")


@mcp.tool()
def search_opportunities(
    keyword: str = "",
    naics: str = "",
    state: str = "",
    set_aside: str = "",
    notice_type: str = "",
    days: int = 30,
    active_only: bool = True,
    open_deadline_only: bool = True,
    limit: int = 10,
) -> dict[str, Any]:
    """Search the local SAM.gov mirror for candidate opportunities.

    This is candidate discovery, not live validation. By default, expired
    response deadlines are excluded even when SAM marks a notice active.
    """
    if not DB_PATH.exists():
        raise ValueError("Local opportunity database is missing; run scripts/sync_bulk.py first.")
    days = max(0, min(days, 3650))
    limit = max(1, min(limit, 50))
    where: list[str] = []
    params: list[str] = []
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
    if active_only:
        where.append("active = 'Yes'")
    if days > 0:
        where.append("posted_date >= ?")
        params.append((datetime.now(LOCAL_TIMEZONE).date() - timedelta(days=days)).isoformat())
    where_sql = " AND ".join(where) if where else "1=1"
    fetch_limit = min(max(limit * 20, 100), 1000)
    sql = f"""
        SELECT notice_id, title, sol_number, department, sub_tier, posted_date,
               type, set_aside, response_deadline, naics_code, pop_city, pop_state,
               active, link, description
        FROM opportunities
        WHERE {where_sql}
        ORDER BY posted_date DESC
        LIMIT ?
    """
    with sqlite3.connect(DB_PATH) as connection:
        connection.row_factory = sqlite3.Row
        records = connection.execute(sql, params + [fetch_limit]).fetchall()
    candidates: list[dict[str, Any]] = []
    expired_filtered = 0
    for record in records:
        opportunity = dict(record)
        deadline_open, deadline_note = _deadline_status(opportunity.get("response_deadline"))
        opportunity["deadline_open"] = deadline_open
        opportunity["deadline_note"] = deadline_note
        if open_deadline_only and deadline_open is not True:
            expired_filtered += 1
            continue
        candidates.append(opportunity)
        if len(candidates) >= limit:
            break
    synced_at = META_PATH.read_text(encoding="utf-8").strip() if META_PATH.exists() else "unknown"
    return {
        "as_of": datetime.now(LOCAL_TIMEZONE).isoformat(),
        "timezone": USER_TIMEZONE,
        "database_sync": synced_at,
        "filters": {
            "keyword": keyword,
            "naics": naics,
            "state": state,
            "set_aside": set_aside,
            "notice_type": notice_type,
            "days": days,
            "active_only": active_only,
            "open_deadline_only": open_deadline_only,
        },
        "shown": len(candidates),
        "expired_or_unknown_deadline_filtered": expired_filtered,
        "opportunities": candidates,
        "verification_required": (
            "Verify status, deadline, and documents against current official public sources "
            "before recommending an opportunity."
        ),
    }


@mcp.tool()
def document_index_status() -> dict[str, Any]:
    """Show local Elasticsearch document-index status."""
    return _document_store().health()


@mcp.tool()
def ingest_public_document(
    url: str,
    notice_id: str = "",
    solicitation_number: str = "",
    title: str = "",
    document_id: str = "",
    document_type: str = "solicitation_attachment",
) -> dict[str, Any]:
    """Download and ingest a public HTTPS solicitation document into Elasticsearch."""
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https":
        raise ValueError("Only public HTTPS document URLs are accepted by this MCP tool.")
    store = _document_store()
    store.ensure_index()
    args = SimpleNamespace(
        sources=[url],
        document_id=document_id or None,
        notice_id=notice_id,
        solicitation_number=solicitation_number,
        title=title or None,
        document_type=document_type,
        metadata=[f"public_source_url={url}"],
        public=True,
        embedding_provider=None,
        json=True,
    )
    try:
        return _captured_json(command_ingest, store, args)
    except DocumentStoreError as exc:
        raise ValueError(str(exc)) from exc


@mcp.tool()
def search_documents(
    query: str,
    notice_id: str = "",
    document_type: str = "",
    limit: int = 5,
) -> dict[str, Any]:
    """Search indexed public documents for technical-fit and execution evidence."""
    store = _document_store()
    args = SimpleNamespace(
        query=query,
        mode="lexical",
        notice_id=notice_id or None,
        document_type=document_type or None,
        limit=max(1, min(limit, 20)),
        embedding_provider=None,
        json=True,
    )
    try:
        return _captured_json(command_search, store, args)
    except DocumentStoreError as exc:
        raise ValueError(str(exc)) from exc


@mcp.tool()
async def evaluate_opportunity(notice_id: str) -> dict[str, Any]:
    """Run the independent Phase-1 panel for one notice and persist its verdict.

    The argument accepts a SAM notice ID. A solicitation number is also
    accepted as a convenience fallback when it resolves in the local mirror.
    """
    try:
        return await PanelService().evaluate(notice_id)
    except Exception as exc:
        raise ValueError(str(exc)) from exc


@mcp.tool()
def get_panel_verdict(notice_id: str) -> dict[str, Any]:
    """Return the latest stored panel verdict for one notice."""
    result = PanelStore().latest_for_notice(notice_id)
    if result is None:
        raise ValueError(f"No stored panel verdict found for {notice_id!r}")
    return result.to_dict()


# ---------------------------------------------------------------------------
# v2 tools: scoring, watchlist, saved searches, daily digest
# ---------------------------------------------------------------------------


def _watchlist_store() -> WatchlistStore:
    return WatchlistStore()


def _mirror_opportunity(notice_id: str) -> dict[str, Any]:
    if not DB_PATH.exists():
        return {}
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT notice_id, title, sol_number, department, sub_tier, posted_date,
                   type, set_aside, set_aside_code, response_deadline, naics_code,
                   pop_city, pop_state, active, link, description
              FROM opportunities
             WHERE notice_id = ?
            """,
            (notice_id,),
        ).fetchone()
    return dict(row) if row else {}


def _note_text(value: Any) -> str:
    if isinstance(value, list):
        return "; ".join(str(item) for item in value if str(item).strip())
    return str(value or "").strip()


def _research_delivery_read(item: dict[str, Any]) -> dict[str, str] | None:
    disposition = str(item.get("disposition") or "").strip().lower()
    if not disposition:
        return None
    detail = (
        _note_text(item.get("blockers"))
        or _note_text(item.get("concern"))
        or _note_text(item.get("supported_fit"))
        or "See the AI research notes."
    )
    if disposition == "assess now":
        return {"label": "Assess now", "detail": detail, "level": "solo"}
    if disposition == "monitor/partner":
        return {"label": "Monitor / partner", "detail": detail, "level": "team"}
    if disposition == "reject":
        return {"label": "Reject", "detail": detail, "level": "monitor"}
    return {"label": disposition, "detail": detail, "level": "monitor"}


def _normalize_research_item(item: dict[str, Any], profile: str) -> dict[str, Any]:
    notice_id = str(item.get("notice_id") or "").strip()
    if not notice_id:
        raise ValueError("each research-scan item must include notice_id")
    mirror = _mirror_opportunity(notice_id)
    scored: dict[str, Any] = {}
    if mirror:
        scored = score_opportunity(mirror, profile=profile).to_dict()
    normalized = {**mirror, **scored, **item, "notice_id": notice_id}
    title = str(normalized.get("title") or "").strip()
    if not title:
        raise ValueError(f"research-scan item {notice_id!r} needs a title because it is not in the local mirror")
    normalized["title"] = title
    normalized.setdefault("band", "monitor")
    normalized.setdefault("lanes", [])
    deadline_open, deadline_note = _deadline_status(normalized.get("response_deadline"))
    normalized["deadline_open"] = deadline_open
    normalized["deadline_note"] = deadline_note
    delivery_read = _research_delivery_read(normalized)
    if delivery_read:
        normalized["delivery_read"] = delivery_read
    return normalized


@mcp.tool()
def list_scoring_profiles() -> dict[str, Any]:
    """List the available scoring-profile names."""
    return {"profiles": available_profiles(), "valid_statuses": sorted(VALID_STATUSES)}


@mcp.tool()
def score_opportunities(
    keyword: str = "",
    naics: str = "",
    state: str = "",
    set_aside: str = "",
    notice_type: str = "",
    days: int = 30,
    min_score: int = 2,
    profile: str = "technical_services",
    limit: int = 20,
) -> dict[str, Any]:
    """Search the local SAM mirror and return opportunities ranked by score.

    Scoring is keyword + structural-rule based on the operator's profile and
    is meant for triage. Every point of score is attributed to a reason.
    """
    if profile not in available_profiles():
        raise ValueError(f"Unknown profile {profile!r}. Available: {available_profiles()}")
    if not DB_PATH.exists():
        raise ValueError("Local opportunity database is missing; run scripts/sync_bulk.py first.")
    days = max(0, min(days, 3650))
    limit = max(1, min(limit, 100))

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
        where.append("posted_date >= ?")
        params.append((datetime.now(LOCAL_TIMEZONE).date() - timedelta(days=days)).isoformat())
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
    out = []
    for result in scored:
        if result.score < min_score:
            continue
        opp = by_id.get(result.notice_id, {})
        out.append({
            "notice_id": result.notice_id,
            "title": result.title,
            "score": result.score,
            "band": result.band,
            "lanes": result.lanes,
            "reasons": [r.to_dict() for r in result.reasons],
            "department": opp.get("department"),
            "naics_code": opp.get("naics_code"),
            "set_aside": opp.get("set_aside"),
            "posted_date": opp.get("posted_date"),
            "response_deadline": opp.get("response_deadline"),
            "link": opp.get("link"),
        })
    out.sort(key=lambda x: x["score"], reverse=True)
    return {
        "as_of": datetime.now(LOCAL_TIMEZONE).isoformat(),
        "profile": profile,
        "shown": len(out[:limit]),
        "results": out[:limit],
    }


@mcp.tool()
def score_one_opportunity(
    notice_id: str,
    profile: str = "technical_services",
) -> dict[str, Any]:
    """Score a single notice already in the local mirror."""
    if profile not in available_profiles():
        raise ValueError(f"Unknown profile {profile!r}")
    if not DB_PATH.exists():
        raise ValueError("Local opportunity database is missing.")
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM opportunities WHERE notice_id = ?", (notice_id,)
        ).fetchone()
    if not row:
        raise ValueError(f"notice {notice_id} not in local mirror")
    result = score_opportunity(dict(row), profile=profile)
    return result.to_dict()


@mcp.tool()
def generate_daily_digest(
    profile: str = "technical_services",
    days: int = 3,
    min_score: int = 3,
    write: bool = True,
) -> dict[str, Any]:
    """Generate a daily digest report. Returns scan counts and (optional) file paths."""
    if profile not in available_profiles():
        raise ValueError(f"Unknown profile {profile!r}")
    result = generate_digest(profile=profile, days=days, min_score=min_score, write=write)
    return {
        "generated_at": result["generated_at"],
        "profile": result["profile"],
        "scanned": result["scanned"],
        "shown": result["shown"],
        "markdown_path": result["markdown_path"],
        "html_path": result["html_path"],
        "results": result["results"],
    }


@mcp.tool()
def publish_research_scan(
    summary: str,
    items: list[dict[str, Any]],
    candidates_scanned: int = 0,
    profile: str = "technical_services",
) -> dict[str, Any]:
    """Publish one final curated AI lead scan into the production Workbench.

    Call this exactly once after a user-requested contract-lead search. Publish
    only the final recommended or monitor/partner items, not intermediate
    discovery results. Pass an empty item list when no supported fit is found.

    Each item must include `notice_id`. Local SAM metadata and deterministic
    scoring are added automatically when the notice exists in the mirror.
    Useful optional research fields are `disposition`, `supported_fit`,
    `concern`, `blockers`, and `evidence`.
    """
    if profile not in available_profiles():
        raise ValueError(f"Unknown profile {profile!r}")
    if not isinstance(items, list):
        raise ValueError("items must be a list")
    normalized_items = [_normalize_research_item(item, profile) for item in items]
    run_id = _watchlist_store().publish_research_scan(
        summary=summary,
        items=normalized_items,
        profile=profile,
        candidates_scanned=max(0, candidates_scanned),
    )
    return {
        "ok": True,
        "scan_id": run_id,
        "source": "ai_research",
        "profile": profile,
        "candidates_scanned": max(candidates_scanned, len(normalized_items)),
        "candidates_shown": len(normalized_items),
        "summary": summary,
        "items": normalized_items,
    }


@mcp.tool()
def add_to_watchlist(
    notice_id: str,
    title: str = "",
    status: str = "tracking",
    notes: str = "",
    score: int = 0,
    band: str = "",
) -> dict[str, Any]:
    """Add a SAM notice to the local watchlist."""
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status {status!r}. Valid: {sorted(VALID_STATUSES)}")

    opportunity: dict[str, Any] = {"notice_id": notice_id, "title": title}
    if DB_PATH.exists() and not title:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT notice_id, title, sol_number, department, naics_code, set_aside, response_deadline, link FROM opportunities WHERE notice_id = ?",
                (notice_id,),
            ).fetchone()
        if row:
            opportunity = dict(row)

    entry = _watchlist_store().add_to_watchlist(
        opportunity,
        status=status,
        notes=notes or None,
        score=score or None,
        band=band or None,
    )
    return entry.to_dict()


@mcp.tool()
def list_watchlist(status: str = "", limit: int = 100) -> dict[str, Any]:
    """List entries in the local watchlist."""
    entries = _watchlist_store().list_watchlist(status=status or None, limit=limit)
    return {"count": len(entries), "entries": [e.to_dict() for e in entries]}


@mcp.tool()
def update_watchlist_status(notice_id: str, status: str, note: str = "") -> dict[str, Any]:
    """Update the status of a watchlist entry."""
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status {status!r}")
    entry = _watchlist_store().update_status(notice_id, status, note=note or None)
    if not entry:
        raise ValueError(f"No watchlist entry with notice_id {notice_id}")
    return entry.to_dict()


@mcp.tool()
def add_watchlist_note(notice_id: str, text: str) -> dict[str, Any]:
    """Append a dated note to a watchlist entry."""
    _watchlist_store().add_note(notice_id, text)
    return {"ok": True}


@mcp.tool()
def list_vendor_sourcing_jobs(status: str = "queued_for_codex", limit: int = 20) -> dict[str, Any]:
    """List opportunity-specific subcontractor-sourcing jobs created by Workbench cards."""
    jobs = vendor_jobs.list_sourcing_jobs(status=status or None, limit=limit)
    return {"count": len(jobs), "jobs": jobs}


@mcp.tool()
def get_vendor_sourcing_job(job_id: str) -> dict[str, Any]:
    """Return one queued subcontractor-sourcing job and its Codex research handoff."""
    return vendor_jobs.get_sourcing_job(job_id)


@mcp.tool()
def complete_vendor_sourcing_job(job_id: str, report_markdown: str) -> dict[str, Any]:
    """Mark a sourcing job complete after Codex adds sourced public-web and document findings."""
    return vendor_jobs.complete_sourcing_job(job_id, report_markdown)


@mcp.tool()
def save_search(
    name: str,
    keyword: str = "",
    naics: str = "",
    state: str = "",
    set_aside: str = "",
    notice_type: str = "",
    days: int = 30,
    profile: str = "technical_services",
    min_score: int = 2,
    description: str = "",
) -> dict[str, Any]:
    """Save a named search-filter set for later replay."""
    filters = {
        k: v for k, v in {
            "keyword": keyword, "naics": naics, "state": state,
            "set_aside": set_aside, "notice_type": notice_type, "days": days,
        }.items() if v
    }
    saved = _watchlist_store().save_search(
        name=name, filters=filters,
        description=description or None,
        profile=profile, min_score=min_score,
    )
    return saved.to_dict()


@mcp.tool()
def list_saved_searches() -> dict[str, Any]:
    """List all saved searches."""
    searches = _watchlist_store().list_saved_searches()
    return {"count": len(searches), "searches": [s.to_dict() for s in searches]}


@mcp.tool()
def run_saved_search(name: str, limit: int = 20) -> dict[str, Any]:
    """Replay a saved search through the scoring engine."""
    saved = _watchlist_store().get_saved_search(name)
    if not saved:
        raise ValueError(f"No saved search named {name!r}")
    _watchlist_store().mark_search_run(name)
    filters = saved.filters
    return score_opportunities(
        keyword=filters.get("keyword", ""),
        naics=filters.get("naics", ""),
        state=filters.get("state", ""),
        set_aside=filters.get("set_aside", ""),
        notice_type=filters.get("notice_type", ""),
        days=int(filters.get("days", 30)),
        min_score=saved.min_score,
        profile=saved.profile,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# v2.2 tools: USAspending, eCFR, tasks spine
# ---------------------------------------------------------------------------


@mcp.tool()
def find_incumbents(
    naics: str = "",
    agency: str = "",
    keyword: str = "",
    pop_state: str = "",
    years_back: int = 3,
    limit: int = 20,
) -> dict[str, Any]:
    """USAspending: recent procurement award recipients matching the filters.

    These are likely incumbents for a similar future opportunity.
    """
    try:
        awards = usaspending.find_incumbents(
            naics=naics or None,
            agency=agency or None,
            keyword=keyword or None,
            pop_state=pop_state or None,
            years_back=years_back,
            limit=limit,
        )
    except usaspending.USAspendingError as exc:
        raise ValueError(str(exc)) from exc
    return {
        "count": len(awards),
        "awards": [a.to_dict() for a in awards],
        "caveat": "USAspending has documented completeness gaps — treat as directional.",
    }


@mcp.tool()
def award_history(
    recipient_name: str = "",
    recipient_uei: str = "",
    naics: str = "",
    agency: str = "",
    years_back: int = 5,
    limit: int = 30,
) -> dict[str, Any]:
    """USAspending: award history for a specific recipient (optionally filtered)."""
    if not (recipient_name or recipient_uei):
        raise ValueError("specify recipient_name or recipient_uei")
    try:
        awards = usaspending.award_history(
            recipient_name=recipient_name or None,
            recipient_uei=recipient_uei or None,
            naics=naics or None,
            agency=agency or None,
            years_back=years_back,
            limit=limit,
        )
    except usaspending.USAspendingError as exc:
        raise ValueError(str(exc)) from exc
    return {"count": len(awards), "awards": [a.to_dict() for a in awards]}


@mcp.tool()
def top_recipients_by_naics(
    naics: str,
    years_back: int = 3,
    limit: int = 10,
) -> dict[str, Any]:
    """USAspending: top recipients (by dollars) for a NAICS code over the window."""
    try:
        recipients = usaspending.top_recipients_by_naics(
            naics=naics, years_back=years_back, limit=limit,
        )
    except usaspending.USAspendingError as exc:
        raise ValueError(str(exc)) from exc
    return {"count": len(recipients), "recipients": [r.to_dict() for r in recipients]}


@mcp.tool()
def get_cfr_section(title: int, section: str, part: str = "") -> dict[str, Any]:
    """eCFR: fetch text of a CFR section. FAR = title 48; SBA size standards = title 13."""
    try:
        clause = ecfr.get_section(title=title, section=section, part=part or None)
    except ecfr.ECFRError as exc:
        raise ValueError(str(exc)) from exc
    return clause.to_dict()


@mcp.tool()
def search_ecfr(query: str, title: int = 0, limit: int = 10) -> dict[str, Any]:
    """eCFR: full-text search across CFR (optionally a single title)."""
    try:
        hits = ecfr.search(query=query, title=title or None, limit=limit)
    except ecfr.ECFRError as exc:
        raise ValueError(str(exc)) from exc
    return {"count": len(hits), "hits": [h.to_dict() for h in hits]}


@mcp.tool()
def list_tasks(status: str = "", tag: str = "", type_filter: str = "") -> dict[str, Any]:
    """Tasks spine: list business workstreams from `tasks/*.md`."""
    tasks = tasks_lib.list_tasks(
        status=status or None,
        tag=tag or None,
        type_filter=type_filter or None,
    )
    return {"count": len(tasks), "tasks": [t.to_dict() for t in tasks]}


@mcp.tool()
def next_unblocked(limit: int = 10) -> dict[str, Any]:
    """Tasks spine: next-actionable workstreams per the never-hard-block rule."""
    tasks = tasks_lib.next_unblocked(limit=limit)
    return {"count": len(tasks), "tasks": [t.to_dict() for t in tasks]}


@mcp.tool()
def set_task_status(task_id: str, status: str, note: str = "") -> dict[str, Any]:
    """Tasks spine: update a task's status and append an audit note."""
    if status not in tasks_lib.VALID_STATUSES:
        raise ValueError(f"Invalid status {status!r}; valid: {sorted(tasks_lib.VALID_STATUSES)}")
    task = tasks_lib.set_status(task_id, status, note=note or None)
    return task.to_dict()


@mcp.tool()
def validate_tasks() -> dict[str, Any]:
    """Tasks spine: validate frontmatter across `tasks/*.md`."""
    issues = tasks_lib.validate_all()
    return {
        "count": len(issues),
        "issues": [i.to_dict() for i in issues],
        "ok": all(i.severity != "error" for i in issues),
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
