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

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_DIR / "data" / "contracts.db"
META_PATH = PROJECT_DIR / "data" / "last_sync.txt"
PROFILE_PATH = PROJECT_DIR / "TECHNICAL_SERVICES_PROFILE.md"
ELASTIC_PROFILE_PATH = PROJECT_DIR / "ELASTIC_LEAD_PROFILE.md"
PROMPT_PATH = PROJECT_DIR / "prompts" / "technical_services_lead_research.md"
USER_TIMEZONE = os.getenv("USER_TIMEZONE", "America/New_York")
LOCAL_TIMEZONE = ZoneInfo(USER_TIMEZONE)

mcp = FastMCP(
    "technical-contract-research",
    instructions=(
        "Research public federal technical-services opportunities for the operator. "
        "Prioritize Elastic/OpenSearch, AI search and RAG, observability/SIEM, "
        "AI/data services, and VTC/network engineering. Reject closed, unrelated, "
        "or weak keyword-only matches."
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
    """Active opportunity-fit profile for the operator's technical-services work."""
    return PROFILE_PATH.read_text(encoding="utf-8")


@mcp.prompt()
def find_technical_services_leads() -> str:
    """Research public SAM.gov technical-services opportunities for the operator."""
    return PROMPT_PATH.read_text(encoding="utf-8")


@mcp.tool()
def get_technical_services_profile() -> str:
    """Return the operator's active broad technical-services lead-selection profile."""
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


if __name__ == "__main__":
    mcp.run(transport="stdio")
