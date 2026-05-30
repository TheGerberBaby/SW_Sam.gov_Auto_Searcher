"""eCFR REST client — FAR / CFR clause grounding.

The Electronic Code of Federal Regulations exposes a keyless REST
API. We use it to:

1. Pull the canonical text of a clause cited in a solicitation
   (e.g. FAR 52.212-2) so we can reason about its actual
   requirements instead of guessing.
2. Search regulation text by phrase across a single title or all
   titles (e.g. "service-disabled veteran" across CFR Title 13).

FAR = CFR Title **48**. SBA size standards = CFR Title **13**
(specifically Part 121). All responses are cached to
`data/ecfr_cache.json` with a 7-day TTL — regulation text doesn't
change daily.

CLI:

    python scripts/ecfr.py titles
    python scripts/ecfr.py section --title 48 --part 19 --section 19.502-2
    python scripts/ecfr.py search "service-disabled veteran" --title 13 --limit 5
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass, asdict
from datetime import date
from pathlib import Path
from typing import Any
from urllib import error, parse, request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = PROJECT_ROOT / "data" / "ecfr_cache.json"
DEFAULT_TTL_SECONDS = 7 * 24 * 3600

API_BASE = "https://www.ecfr.gov/api"
USER_AGENT = "SW-Contracting-Bots/2.2 (Stormwind Contracting research)"


class ECFRError(RuntimeError):
    """Raised when the eCFR API returns an error or unreachable response."""


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SearchHit:
    title: str | int | None
    chapter: str | None
    part: str | None
    section: str | None
    heading: str | None
    citation: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ClauseText:
    title: int
    part: str | None
    section: str | None
    citation: str
    heading: str | None
    text: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Cache + HTTP
# ---------------------------------------------------------------------------


def _load_cache() -> dict[str, Any]:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(data: dict[str, Any]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def _get(
    path: str,
    params: dict[str, Any] | None = None,
    *,
    accept_json: bool = True,
    timeout: int = 30,
    cache_ttl: int = DEFAULT_TTL_SECONDS,
) -> str | dict[str, Any]:
    qs = ("?" + parse.urlencode(params, doseq=True)) if params else ""
    url = f"{API_BASE}{path}{qs}"
    cache_key = hashlib.sha256(f"{path}{qs}{accept_json}".encode("utf-8")).hexdigest()
    cache = _load_cache()
    entry = cache.get(cache_key)
    if entry and (time.time() - entry["fetched_at"]) < cache_ttl:
        return entry["data"]

    accept = "application/json" if accept_json else "application/xml"
    req = request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": accept},
        method="GET",
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except error.HTTPError as exc:
        msg = exc.read().decode("utf-8", errors="replace")[:300] if exc.fp else str(exc)
        raise ECFRError(f"eCFR {exc.code}: {msg}") from exc
    except error.URLError as exc:
        raise ECFRError(f"eCFR network error: {exc.reason}") from exc

    data: str | dict[str, Any]
    if accept_json:
        data = json.loads(raw) if raw.strip() else {}
    else:
        data = raw

    cache[cache_key] = {"fetched_at": time.time(), "data": data}
    _save_cache(cache)
    return data


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_titles() -> list[dict[str, Any]]:
    """Return the high-level title index (numbers + names)."""
    payload = _get("/versioner/v1/titles.json")
    if isinstance(payload, dict):
        return payload.get("titles") or []
    return []


def _latest_iso_date() -> str:
    """Use today's date for /full/ endpoints — eCFR accepts ISO dates."""
    return date.today().isoformat()


def get_section(
    title: int | str,
    section: str,
    part: str | None = None,
    on_date: str | None = None,
) -> ClauseText:
    """Fetch the text of a specific section.

    `title` is the CFR title number (FAR = 48, SBA size standards = 13).
    `section` is the section identifier as cited (e.g., "19.502-2",
    "121.201", "52.212-2").
    """
    title_int = int(str(title))
    on_date = on_date or _latest_iso_date()
    params: dict[str, Any] = {"section": section}
    if part:
        params["part"] = part
    raw_xml = _get(
        f"/versioner/v1/full/{on_date}/title-{title_int}.xml",
        params=params,
        accept_json=False,
    )
    if not isinstance(raw_xml, str):
        raise ECFRError("eCFR returned a non-text payload for section fetch")
    text = _strip_xml(raw_xml)
    heading = _first_match(text, r"§\s*[\d.\-]+\s+(.+?)$")
    if not text.strip():
        raise ECFRError(f"No content returned for CFR {title_int} § {section}")
    return ClauseText(
        title=title_int,
        part=part,
        section=section,
        citation=f"{title_int} CFR § {section}",
        heading=heading,
        text=text.strip(),
    )


def search(
    query: str,
    title: int | str | None = None,
    limit: int = 10,
    per_page: int | None = None,
) -> list[SearchHit]:
    """Full-text search across the eCFR corpus (optionally a single title)."""
    per_page = per_page or max(1, min(limit, 50))
    params: dict[str, Any] = {"query": query, "per_page": per_page, "page": 1}
    if title is not None:
        params["hierarchy[title]"] = int(str(title))
    payload = _get("/search/v1/results", params=params, accept_json=True, cache_ttl=3600)
    if not isinstance(payload, dict):
        return []
    results = payload.get("results") or []
    hits: list[SearchHit] = []
    for row in results[:limit]:
        hier = row.get("hierarchy") or {}
        headings_human = row.get("headings") or {}
        heading_html = (
            headings_human.get("section")
            or headings_human.get("subpart")
            or headings_human.get("part")
            or ""
        )
        heading = _strip_tags(str(heading_html))
        title_val = hier.get("title")
        part = hier.get("part")
        section = hier.get("section")
        citation_bits = [f"Title {title_val}" if title_val else None,
                          f"Part {part}" if part else None,
                          f"§ {section}" if section else None]
        citation = " ".join(b for b in citation_bits if b)
        hits.append(SearchHit(
            title=title_val,
            chapter=hier.get("chapter"),
            part=part,
            section=section,
            heading=heading,
            citation=citation,
        ))
    return hits


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"[ \t]+\n")


def _strip_tags(value: str) -> str:
    return _TAG_RE.sub("", value).strip()


def _strip_xml(xml: str) -> str:
    text = _TAG_RE.sub(" ", xml)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _first_match(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text, re.MULTILINE)
    return match.group(1).strip() if match else None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli() -> None:
    parser = argparse.ArgumentParser(description="eCFR REST client — FAR/CFR clause grounding.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("titles", help="List CFR titles.")

    p_sec = sub.add_parser("section", help="Fetch the text of a specific CFR section.")
    p_sec.add_argument("--title", required=True)
    p_sec.add_argument("--section", required=True)
    p_sec.add_argument("--part")
    p_sec.add_argument("--on-date", dest="on_date")
    p_sec.add_argument("--json", action="store_true")

    p_search = sub.add_parser("search", help="Full-text search across regulation text.")
    p_search.add_argument("query")
    p_search.add_argument("--title", type=int)
    p_search.add_argument("--limit", type=int, default=10)
    p_search.add_argument("--json", action="store_true")

    args = parser.parse_args()

    if args.cmd == "titles":
        titles = list_titles()
        for t in titles:
            number = t.get("number")
            name = t.get("name")
            print(f"  Title {number:>2}  {name}")
    elif args.cmd == "section":
        clause = get_section(title=args.title, section=args.section, part=args.part, on_date=args.on_date)
        if args.json:
            print(json.dumps(clause.to_dict(), indent=2))
            return
        print(f"\n{clause.citation}")
        if clause.heading:
            print(f"  {clause.heading}")
        print()
        # Trim very long sections for readability
        body = clause.text
        if len(body) > 4000:
            body = body[:4000] + f"\n\n[... truncated; full length {len(clause.text):,} chars ...]"
        print(body)
        print()
    elif args.cmd == "search":
        hits = search(args.query, title=args.title, limit=args.limit)
        if args.json:
            print(json.dumps([h.to_dict() for h in hits], indent=2))
            return
        if not hits:
            print("(no hits)")
            return
        for i, hit in enumerate(hits, 1):
            print(f"\n[{i}] {hit.citation or '-'}")
            if hit.heading:
                print(f"    {hit.heading}")


if __name__ == "__main__":
    _cli()
