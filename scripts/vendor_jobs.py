"""Opportunity-specific subcontractor-sourcing job queue.

Dashboard contract cards use this module to create a durable sourcing handoff:
the immediate deterministic outreach package is saved now, and a future Codex
chat can claim the queued context for document review and public web research.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import source_vendors

LOCAL_TZ = ZoneInfo("America/New_York")
PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_DIR / "data" / "contracts.db"
QUEUE_DIR = PROJECT_DIR / "data" / "vendor-sourcing-jobs"
REPORTS_DIR = PROJECT_DIR / "reports"


def _now() -> str:
    return datetime.now(LOCAL_TZ).isoformat(timespec="seconds")


def _job_id(notice_id: str) -> str:
    stamp = datetime.now(LOCAL_TZ).strftime("%Y%m%d-%H%M%S-%f")
    token = re.sub(r"[^A-Za-z0-9_-]+", "-", notice_id).strip("-")[:36] or "notice"
    return f"{stamp}-{token}"


def _resolve_mirror_opportunity(notice_id: str, db_path: Path = DB_PATH) -> dict[str, Any]:
    if not notice_id or not db_path.exists():
        return {}
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT notice_id, title, sol_number, department, sub_tier, posted_date,
                   type, set_aside, set_aside_code, response_deadline, naics_code,
                   pop_city, pop_state, active, link, description
              FROM opportunities
             WHERE notice_id = ?
             LIMIT 1
            """,
            (notice_id,),
        ).fetchone()
    return dict(row) if row else {}


def _merge_opportunity(opportunity: dict[str, Any], db_path: Path = DB_PATH) -> dict[str, Any]:
    provided = {key: value for key, value in opportunity.items() if value not in {None, ""}}
    mirror = _resolve_mirror_opportunity(str(provided.get("notice_id") or ""), db_path)
    return {**mirror, **provided}


def opportunity_place(opportunity: dict[str, Any]) -> str:
    if str(opportunity.get("work_location") or "").strip():
        return str(opportunity["work_location"]).strip()
    city = str(opportunity.get("pop_city") or "").strip()
    state = str(opportunity.get("pop_state") or "").strip()
    if city and state:
        return f"{city}, {state}"
    return state or "place of performance not listed"


def build_future_chat_questions(opportunity: dict[str, Any], service_label: str) -> list[str]:
    """Facts the operator or a future chat should verify before relying on the report."""
    return [
        "What is the official deadline for questions, and what email address or portal must receive them?",
        "Who are the contracting officer and contract specialist? Record their public phone numbers and emails.",
        "Have all public solicitation attachments, amendments, PWS/SOW files, and pricing schedules been reviewed?",
        f"What exact quantities, locations, frequencies, response windows, and deliverables define the {service_label} scope?",
        "Is a site visit or walkthrough scheduled or permitted before quotes are due?",
        "May Stormwind use a qualified first-tier subcontractor for the performing work, and what must Stormwind self-perform?",
        "Does FAR 52.219-14 or another limitation-on-subcontracting clause apply? Confirm from the solicitation.",
        "Which licenses, certifications, OEM authorizations, clearances, insurance limits, bonds, and badging rules apply?",
        "Which requirements must be held by the prime, which may be held by the subcontractor, and which must be held by both?",
        "What quote volumes, line-item pricing, references, technical narrative, and subcontractor disclosures are required?",
        "Are there wage determinations, service-contract labor standards, HAZMAT rules, reporting formats, or base-access lead times?",
        "What unknowns could materially change subcontractor pricing, schedule, margin, or Stormwind's eligibility to bid?",
    ]


def build_contracting_officer_draft(opportunity: dict[str, Any], service_label: str) -> str:
    sol_number = str(opportunity.get("sol_number") or opportunity.get("notice_id") or "[solicitation]")
    title = str(opportunity.get("title") or service_label)
    return f"""\
Subject: {sol_number} - clarification questions - {title}

Good afternoon,

Stormwind Contracting is reviewing {sol_number}, {title}. Please clarify the
following:

1. What is the official deadline and submission channel for questions?
2. Is a site visit or walkthrough planned or permitted before quotes are due?
3. May the prime contractor use a qualified first-tier subcontractor for the
   performing work? If so, should the quote identify the subcontractor and
   include its credentials, references, and technical approach?
4. Please confirm whether FAR 52.219-14, Limitations on Subcontracting, or any
   other prime-performance limitation applies to this requirement.
5. Please confirm the current pricing basis: locations, quantities,
   frequencies, response times, option periods, and any emergency-call
   assumptions.
6. Which licenses, certifications, OEM authorizations, insurance limits,
   bonds, clearances, and facility-access or badging requirements apply?
7. Which of those requirements must be held by the prime, which may be held by
   the performing subcontractor, and which must be held by both?
8. Are there required quote volumes, pricing templates, references, reporting
   formats, wage determinations, HAZMAT submissions, or other attachments that
   offerors should specifically confirm?

Thank you,

Jeremy
Stormwind Contracting
"""


def build_agent_handoff_prompt(
    opportunity: dict[str, Any],
    package: dict[str, Any],
    report_filename: str,
) -> str:
    facts = {
        key: opportunity.get(key)
        for key in [
            "notice_id", "title", "sol_number", "department", "type",
            "set_aside", "response_deadline", "naics_code", "pop_city",
            "pop_state", "link",
        ]
    }
    return f"""\
Complete the queued subcontractor-sourcing report for Stormwind Contracting.

Read PROFILE.md, criteria/VENDOR_SOURCING_PROFILE.md,
criteria/SUBCONTRACTING_PRIME_PROFILE.md, docs/DOCUMENT_INDEX.md, and the
subcontractor-sourcing skill before researching.

Opportunity facts from the local SAM mirror:
{json.dumps(facts, indent=2, default=str)}

Preliminary report: reports/{report_filename}
Service label: {package["service_label"]}
Place of performance: {package["place"]}
Prime quote deadline: {package.get("due") or "not listed"}

Use official public solicitation sources and current public vendor websites.
Ingest and search public attachments when requirements are hidden in documents.
Return:
1. Five realistic performer leads with current public phone numbers, emails or
   contact pages, source URLs, and a concise reason to call each one.
2. A pursuit-specific cold-call narrative and follow-up subcontractor email.
3. The public contracting officer and contract specialist contact details.
4. A written clarification-question draft tied to the actual PWS/SOW and quote
   instructions.
5. A short unknowns checklist for future chats and the operator.
6. Clause, credential, licensing, badging, schedule, pricing, and margin risks.

Do not invent certifications, contacts, clauses, deadlines, or submission
requirements. Mark unverified facts explicitly. Update the preliminary report
with sourced findings and complete this queued job through the MCP tool when
available.
"""


def _render_markdown(job: dict[str, Any]) -> str:
    opportunity = job["opportunity"]
    package = job["package"]
    vendors = package.get("vendors") or []
    vendor_lines = []
    for index, vendor in enumerate(vendors, 1):
        vendor_lines.extend(
            [
                f"### {index}. {vendor.get('name') or '(unnamed business)'}",
                "",
                f"- Phone: {vendor.get('phone') or '-'}",
                f"- Address: {vendor.get('address') or '-'}",
                f"- Website: {vendor.get('website') or '-'}",
                "",
            ]
        )
    if not vendor_lines:
        vendor_lines = [
            "_No fresh public-business lookup ran yet. Complete the queued Codex",
            "handoff or configure `GOOGLE_PLACES_API_KEY`._",
            "",
        ]

    vendors_markdown = "\n".join(vendor_lines)
    asks = "\n".join(f"{index}. {ask}" for index, ask in enumerate(package["email_asks"], 1))
    unknowns = "\n".join(f"- {item}" for item in job["future_chat_questions"])
    return f"""\
# Subcontractor Sourcing Job: {opportunity.get("title") or "(untitled)"}

Generated: {job["created_at"]}
Status: `{job["status"]}`
Job ID: `{job["job_id"]}`

## Opportunity Snapshot

- Notice ID: `{opportunity.get("notice_id") or "-"}`
- Solicitation: `{opportunity.get("sol_number") or "-"}`
- Agency: {opportunity.get("department") or "-"}
- NAICS: `{opportunity.get("naics_code") or "-"}`
- Place of performance: {package["place"]}
- Quote deadline: {opportunity.get("response_deadline") or "-"}
- Public notice: {opportunity.get("link") or "-"}

## Immediate Performer Leads

{vendors_markdown}
## Cold-Call Narrative

```text
{package["call_script"]}
```

## Subcontractor Follow-Up Email

```text
{package["email_draft"]}
```

## Subcontractor Qualification Ask-List

{asks}

## Contracting-Officer Question Draft

```text
{job["contracting_officer_draft"]}
```

## Facts Future Chats Need To Verify

{unknowns}

## Codex Research Handoff

```text
{job["agent_handoff_prompt"]}
```
"""


def create_sourcing_job(
    opportunity: dict[str, Any],
    *,
    max_results: int = 5,
    api_key: str | None = None,
    db_path: Path = DB_PATH,
    queue_dir: Path = QUEUE_DIR,
    reports_dir: Path = REPORTS_DIR,
) -> dict[str, Any]:
    merged = _merge_opportunity(opportunity, db_path=db_path)
    notice_id = str(merged.get("notice_id") or "").strip()
    if not notice_id:
        raise ValueError("opportunity must include notice_id")
    title = str(merged.get("title") or "").strip()
    naics = str(merged.get("naics_code") or "").strip() or None
    service = None if naics in source_vendors.VENDOR_PROFILES else title or "the work"
    place = opportunity_place(merged)
    package = source_vendors.generate_vendor_package(
        naics=naics,
        service=service,
        place=place,
        due=str(merged.get("response_deadline") or "").strip() or None,
        max_results=max_results,
        api_key=api_key,
        allow_script_fallback=True,
    )
    job_id = _job_id(notice_id)
    report_filename = f"vendor-sourcing-{job_id}.md"
    job = {
        "job_id": job_id,
        "status": "queued_for_codex",
        "created_at": _now(),
        "opportunity": merged,
        "package": package,
        "future_chat_questions": build_future_chat_questions(merged, package["service_label"]),
        "contracting_officer_draft": build_contracting_officer_draft(merged, package["service_label"]),
        "report_filename": report_filename,
    }
    job["agent_handoff_prompt"] = build_agent_handoff_prompt(merged, package, report_filename)
    queue_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / report_filename
    job["report_path"] = str(report_path)
    report_path.write_text(_render_markdown(job), encoding="utf-8")
    (queue_dir / f"{job_id}.json").write_text(json.dumps(job, indent=2, default=str), encoding="utf-8")
    return job


def list_sourcing_jobs(
    *,
    status: str | None = None,
    limit: int = 20,
    queue_dir: Path = QUEUE_DIR,
) -> list[dict[str, Any]]:
    if not queue_dir.exists():
        return []
    jobs = []
    for path in sorted(queue_dir.glob("*.json"), reverse=True):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if status and job.get("status") != status:
            continue
        jobs.append(job)
        if len(jobs) >= max(1, limit):
            break
    return jobs


def get_sourcing_job(job_id: str, *, queue_dir: Path = QUEUE_DIR) -> dict[str, Any]:
    path = queue_dir / f"{Path(job_id).name}.json"
    if not path.is_file():
        raise ValueError(f"No vendor-sourcing job with id {job_id!r}")
    return json.loads(path.read_text(encoding="utf-8"))


def complete_sourcing_job(
    job_id: str,
    report_markdown: str,
    *,
    queue_dir: Path = QUEUE_DIR,
    reports_dir: Path = REPORTS_DIR,
) -> dict[str, Any]:
    if not report_markdown.strip():
        raise ValueError("report_markdown must be non-empty")
    job = get_sourcing_job(job_id, queue_dir=queue_dir)
    job["status"] = "completed"
    job["completed_at"] = _now()
    report_path = reports_dir / job["report_filename"]
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_markdown, encoding="utf-8")
    (queue_dir / f"{Path(job_id).name}.json").write_text(
        json.dumps(job, indent=2, default=str),
        encoding="utf-8",
    )
    return job
