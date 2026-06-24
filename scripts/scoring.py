"""Deterministic lead-scoring engine for SAM.gov opportunities.

Scores a single opportunity (a dict matching the columns produced by
`sync_bulk.py`) against the operator's technical-services rubric defined in
`criteria/TECHNICAL_SERVICES_PROFILE.md` and `criteria/ELASTIC_LEAD_PROFILE.md`.

The scorer is keyword + structural-rule based on purpose: it must be
explainable, fast, and never silently invent a fit. Every point of score is
attributed to a `ScoreReason`.

Public surface:

    score_opportunity(opportunity, profile="technical_services") -> ScoreResult
    bulk_score(opportunities, profile=...) -> list[ScoreResult]
    available_profiles() -> list[str]
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import Any, Iterable
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# Keyword and rule tables
# ---------------------------------------------------------------------------

# Tier-1 terms for the active profile: an explicit small-team field-install
# capability. Matching one of these in title or description is the strongest
# signal we get from public metadata alone.
FIELD_INSTALL_TIER1_TERMS = [
    "security camera",
    "security cameras",
    "cctv",
    "video surveillance",
    "video monitoring",
    "camera installation",
    "access control",
    "physical access control",
    "card reader",
    "badge reader",
    "structured cabling",
    "data cabling",
    "network cabling",
    "cat6",
    "cat 6",
    "cat6a",
    "cat 6a",
]

FIELD_INSTALL_TIER2_TERMS = [
    "video management system",
    "network video recorder",
    "common access card",
    "pin reader",
    "door controller",
    "request to exit",
    "rex sensor",
    "maglock",
    "intrusion detection",
    "alarm system",
    "intercom",
    "patch panel",
    "cable testing",
    "low voltage",
    "low-voltage",
    "fiber optic",
    "fiber-optic",
    "inside plant",
    "outside plant",
    "otdr",
    "video teleconference",
    "video teleconferencing",
    "video conference",
    "video conferencing",
    "unified communications",
    "av over ip",
    "av-over-ip",
    "vtc",
    "wi-fi",
    "wifi",
]

# Terms retained for deliberate use of the narrower legacy specialist profile.
ELASTIC_TIER1_TERMS = [
    "elasticsearch",
    "elastic stack",
    "kibana",
    "logstash",
    "elastic agent",
    "elastic security",
    "opensearch",
    "vector search",
    "vector database",
    "semantic search",
    "hybrid search",
    "retrieval augmented generation",
    "retrieval-augmented generation",
    "rag",
    "embeddings",
    "llm",
    "llms",
    "large language model",
    "generative ai",
    "knowledge retrieval",
    "knowledge base",
    "document intelligence",
    "ai assistant",
    "ai search",
    "enterprise search",
]

# Tier-2 terms: technical implementation areas Jeremy can engage on, even
# when no specific product is named.
ELASTIC_TIER2_TERMS = [
    "observability",
    "log analytics",
    "log management",
    "log ingestion",
    "telemetry",
    "siem",
    "security analytics",
    "detection engineering",
    "apm",
    "application performance monitoring",
    "data pipeline",
    "data integration",
    "data engineering",
    "devsecops",
    "platform engineering",
    "cloud migration",
    "video teleconference",
    "video teleconferencing",
    "video conference",
    "video conferencing",
    "unified communications",
    "collaboration system",
    "network modernization",
    "network engineering",
    "av over ip",
    "av-over-ip",
    "vtc",
]

# Tier-3 terms: a bounded engineering deliverable verb. By themselves these
# don't prove fit, but they distinguish a services pursuit from a commodity
# buy.
DELIVERABLE_TERMS = [
    "installation",
    "install",
    "replacement",
    "upgrade",
    "termination",
    "testing",
    "commissioning",
    "repair",
    "maintenance",
    "warranty",
    "as-built",
    "assessment",
    "design",
    "implementation",
    "configuration",
    "migration",
    "dashboard",
    "integration",
    "training",
    "tuning",
    "pilot",
    "modernization",
    "engineering services",
    "technical support services",
    "professional services",
    "advisory services",
]

# Field-install keywords often appear in unrelated equipment, training, and
# cybersecurity notices. Require an execution signal before the active
# profile treats a metadata hit as a real installation lead.
FIELD_EXECUTION_TERMS = [
    "installation",
    "install",
    "installed",
    "upgrade",
    "replacement",
    "replace",
    "repair",
    "maintenance",
    "wiring",
    "cabling",
    "pull",
    "terminate",
    "termination",
    "commissioning",
]

FIELD_TITLE_TERMS = [
    "security camera",
    "security cameras",
    "cctv",
    "video surveillance",
    "video monitoring",
    "camera installation",
    "access control",
    "card reader",
    "badge reader",
    "structured cabling",
    "data cabling",
    "network cabling",
    "low voltage",
    "low-voltage",
    "cat6",
    "cat 6",
    "fiber optic",
    "fiber-optic",
    "intrusion detection",
    "alarm system",
]

PROHIBITED_NOTICE_SIGNALS = [
    "sole source",
    "notice of intent",
]

# Hard exclusions: domain words that almost always indicate a non-fit even
# when they coincide with one of our keywords (e.g., a janitorial RFQ that
# happens to mention "performance"). Matching one of these drops the lead.
HARD_EXCLUSIONS = [
    "general construction",
    "roofing",
    "hvac",
    "plumbing",
    "janitorial",
    "landscaping",
    "snow removal",
    "concrete",
    "asphalt",
    "paving",
    "demolition",
    "drywall",
    "carpentry",
    "renovation",
    "remediation",
    "abatement",
    "facility repair",
    "lawn care",
    "grounds maintenance",
    "pest control",
    "food service",
    "guard services",
    "security guard",
    "medical supplies",
    "laboratory supplies",
    "uniforms",
    "ammunition",
    "fuel delivery",
]

# Product/commodity signals: when these dominate the language, the
# requirement is a buy rather than a service engagement.
RESELL_SIGNALS = [
    "brand name only",
    "brand-name only",
    "no substitute",
    "oem only",
    "manufacturer warranty",
    "license renewal",
    "subscription renewal",
    "software renewal",
    "annual maintenance",
    "purchase of",
    "procurement of",
    "supply of",
    "delivery of equipment",
]

# Acronym false-positive guards: when one of these surfaces without a
# supporting technical term, the original keyword hit was almost certainly
# a coincidence.
FALSE_POSITIVE_GUARDS = {
    "siem": [
        "siemens",  # SIEM hit on Siemens parts catalogs
    ],
    "rag": [
        "ragwool",
        "coverall",
        "coveralls",
        "rags",
        "wiping rag",
    ],
}

# NAICS codes that meaningfully increase confidence in a candidate.
PROFILE_NAICS_BOOSTS = {
    "technical_services": {
        "561621": 2,
        "238210": 1,
        "541512": 0,
        "334290": 0,
    },
    "elastic_only": {
        "541511": 1,
        "541512": 1,
        "541513": 1,
        "541519": 1,
        "518210": 1,
        "517810": 1,
        "541715": 1,
        "541330": 0,
        "334220": 0,
    },
}

# Notice types we want to bid; everything else still surfaces but doesn't earn
# the deliverable point.
BIDDABLE_TYPES = {
    "solicitation",
    "combined synopsis/solicitation",
    "presolicitation",
}

# Information-only notice types — useful intel, not biddable.
INFO_TYPES = {
    "sources sought",
    "special notice",
    "rfi",
    "request for information",
}


# ---------------------------------------------------------------------------
# Reason / result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ScoreReason:
    kind: str            # e.g. "tier1_keyword", "set_aside", "exclusion"
    detail: str          # human-readable token: "elasticsearch (title)"
    points: int          # signed score contribution

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScoreResult:
    notice_id: str
    title: str
    score: int
    band: str            # "strong" / "promising" / "monitor" / "reject"
    lanes: list[str] = field(default_factory=list)
    reasons: list[ScoreReason] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "notice_id": self.notice_id,
            "title": self.title,
            "score": self.score,
            "band": self.band,
            "lanes": self.lanes,
            "reasons": [reason.to_dict() for reason in self.reasons],
        }


# ---------------------------------------------------------------------------
# Profile registry
# ---------------------------------------------------------------------------


PROFILES = {
    "technical_services": {
        "tier1_terms": FIELD_INSTALL_TIER1_TERMS,
        "tier2_terms": FIELD_INSTALL_TIER2_TERMS,
        "tier1_points": 4,
        "tier2_points": 3,
        "deliverable_points": 2,
        "set_aside_points": 1,
        "runway_points": 1,
        "exclusion_points": -5,
        "resell_points": -3,
        "weak_keyword_points": -3,
        "info_type_points": -1,
    },
    "elastic_only": {
        "tier1_terms": ELASTIC_TIER1_TERMS,
        "tier2_terms": ELASTIC_TIER2_TERMS,
        "tier1_points": 3,
        "tier2_points": 2,
        "deliverable_points": 1,
        "set_aside_points": 1,
        "runway_points": 1,
        "exclusion_points": -5,
        "resell_points": -3,
        "weak_keyword_points": -2,
        "info_type_points": -1,
    },
}


def available_profiles() -> list[str]:
    return sorted(PROFILES.keys())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.lower())


# Cache compiled patterns by needle so we don't recompile per opportunity.
_PATTERN_CACHE: dict[str, re.Pattern[str]] = {}


def _pattern_for(needle: str) -> re.Pattern[str]:
    if needle not in _PATTERN_CACHE:
        escaped = re.escape(needle.strip())
        _PATTERN_CACHE[needle] = re.compile(rf"(?<!\w){escaped}(?!\w)")
    return _PATTERN_CACHE[needle]


def _hits(haystack: str, needles: Iterable[str]) -> list[str]:
    found: list[str] = []
    for needle in needles:
        term = needle.strip()
        if not term:
            continue
        if _pattern_for(term).search(haystack):
            found.append(term)
    return found


def _parse_deadline(value: str | None) -> date | None:
    if not value:
        return None
    candidate = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(candidate).date()
    except ValueError:
        try:
            return date.fromisoformat(candidate[:10])
        except ValueError:
            return None


def _band_for(score: int) -> str:
    if score >= 5:
        return "strong"
    if score >= 2:
        return "promising"
    if score >= 0:
        return "monitor"
    return "reject"


def _detect_lanes(title_lower: str, desc_lower: str, profile: str) -> list[str]:
    lanes: list[str] = []
    haystack = f"{title_lower} {desc_lower}"
    field_install_lanes = {
        "electronic_security": [
            "security camera", "security cameras", "cctv", "video surveillance",
            "video monitoring", "camera installation", "access control",
            "physical access control", "pacs", "card reader", "badge reader",
            "door controller", "request to exit", "rex sensor", "maglock",
            "intrusion detection", "alarm system",
        ],
        "cabling_fiber": [
            "structured cabling", "data cabling", "network cabling", "low voltage",
            "low-voltage", "cat6", "cat 6", "cat6a", "cat 6a", "fiber optic",
            "fiber-optic", "patch panel", "termination", "cable testing",
            "inside plant", "outside plant", "otdr",
        ],
        "network_vtc": [
            "vtc", "video teleconference", "video conference",
            "unified communications", "av over ip", "av-over-ip", "wi-fi", "wifi",
        ],
    }
    elastic_lanes = {
        "elastic_search": ["elasticsearch", "elastic stack", "kibana", "logstash",
                            "elastic agent", "opensearch", "enterprise search"],
        "ai_retrieval": ["vector search", "semantic search", "hybrid search", "rag",
                          "retrieval augmented generation", "embeddings", "llm", "llms",
                          "generative ai", "ai assistant", "ai search", "large language model"],
        "observability_siem": ["observability", "log analytics", "log management",
                                "log ingestion", "telemetry", "siem", "security analytics",
                                "detection engineering", "apm"],
        "data_platform": ["data integration", "data pipeline", "data engineering",
                           "devsecops", "platform engineering", "cloud migration"],
        "network_vtc": ["vtc", "video teleconference", "video conference",
                         "unified communications", "collaboration system",
                         "network modernization", "network engineering",
                         "av over ip", "av-over-ip"],
    }
    lane_terms = field_install_lanes if profile == "technical_services" else elastic_lanes
    for lane, terms in lane_terms.items():
        if _hits(haystack, terms):
            lanes.append(lane)
    return lanes


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def score_opportunity(
    opportunity: dict[str, Any],
    profile: str = "technical_services",
    today: date | None = None,
) -> ScoreResult:
    """Score a single opportunity record.

    `opportunity` should contain at least: notice_id, title, description.
    Optional fields used: naics_code, set_aside_code, set_aside, type,
    response_deadline, active.
    """
    if profile not in PROFILES:
        raise ValueError(
            f"Unknown profile: {profile!r}. Available: {available_profiles()}"
        )
    weights = PROFILES[profile]
    today = today or datetime.now(LOCAL_TZ).date()

    title_l = _normalize(opportunity.get("title"))
    desc_l = _normalize(opportunity.get("description"))
    haystack = f"{title_l}\n{desc_l}"

    reasons: list[ScoreReason] = []
    score = 0

    # ---- Hard exclusions ----
    excl_hits = _hits(haystack, HARD_EXCLUSIONS)
    if excl_hits:
        # An exclusion ALONE doesn't kill it — a software dashboard for a
        # construction agency is still in scope. But it should be a strong
        # penalty unless tier-1 also matches.
        for hit in excl_hits[:3]:
            reasons.append(
                ScoreReason("exclusion", hit, weights["exclusion_points"])
            )
            score += weights["exclusion_points"]

    # ---- Tier-1 keyword hits ----
    tier1_hits = _hits(haystack, weights["tier1_terms"])
    for hit in dict.fromkeys(tier1_hits):
        where = "title" if hit in title_l else "description"
        reasons.append(
            ScoreReason("tier1_keyword", f"{hit.strip()} ({where})", weights["tier1_points"])
        )
        score += weights["tier1_points"]

    # ---- Tier-2 keyword hits ----
    tier2_hits = _hits(haystack, weights["tier2_terms"])
    for hit in dict.fromkeys(tier2_hits):
        where = "title" if hit in title_l else "description"
        reasons.append(
            ScoreReason("tier2_keyword", f"{hit.strip()} ({where})", weights["tier2_points"])
        )
        score += weights["tier2_points"]

    # ---- False-positive guards (apply after tier-1 + tier-2) ----
    for guarded_term, fp_signals in FALSE_POSITIVE_GUARDS.items():
        offending = [
            reason for reason in reasons
            if reason.kind in {"tier1_keyword", "tier2_keyword"} and guarded_term in reason.detail
        ]
        if not offending:
            continue
        if _hits(haystack, fp_signals):
            penalty = sum(reason.points for reason in offending)
            matched_fp = _hits(haystack, fp_signals)[0]
            reasons.append(
                ScoreReason(
                    "false_positive_guard",
                    f"{guarded_term} likely matches {matched_fp}",
                    -penalty,
                )
            )
            score -= penalty

    # ---- Deliverable verbs (only count if a tier hit exists; else noted but worth 0) ----
    deliverable_hits = list(dict.fromkeys(_hits(haystack, DELIVERABLE_TERMS)))[:2]
    has_tier_hit = any(reason.kind in {"tier1_keyword", "tier2_keyword"} for reason in reasons)
    for hit in deliverable_hits:
        if has_tier_hit:
            reasons.append(
                ScoreReason("deliverable", hit, weights["deliverable_points"])
            )
            score += weights["deliverable_points"]
        else:
            reasons.append(
                ScoreReason("deliverable_unsupported", f"{hit} (no tier hit)", 0)
            )

    # ---- Field execution guard ----
    if profile == "technical_services":
        has_field_keyword = any(
            reason.kind in {"tier1_keyword", "tier2_keyword"} for reason in reasons
        )
        if has_field_keyword and not _hits(haystack, FIELD_EXECUTION_TERMS):
            positive_metadata_points = sum(
                reason.points
                for reason in reasons
                if reason.kind in {"tier1_keyword", "tier2_keyword", "deliverable"}
                and reason.points > 0
            )
            penalty = positive_metadata_points + 2
            reasons.append(
                ScoreReason(
                    "field_scope_missing",
                    "field-install keyword without install/upgrade/repair scope",
                    -penalty,
                )
            )
            score -= penalty
        if has_field_keyword and not _hits(title_l, FIELD_TITLE_TERMS):
            reasons.append(
                ScoreReason(
                    "field_title_weak",
                    "field-install evidence appears only outside the title",
                    -8,
                )
            )
            score -= 8

    # ---- Prohibited notice signals ----
    prohibited_hits = _hits(haystack, PROHIBITED_NOTICE_SIGNALS)
    if prohibited_hits:
        reasons.append(
            ScoreReason("prohibited_notice", prohibited_hits[0], -20)
        )
        score -= 20


    # ---- Resell / commodity signals ----
    resell_hits = _hits(haystack, RESELL_SIGNALS)
    if resell_hits:
        reasons.append(
            ScoreReason("resell_signal", resell_hits[0], weights["resell_points"])
        )
        score += weights["resell_points"]

    # ---- Set-aside bonus ----
    set_aside_code = (opportunity.get("set_aside_code") or "").upper()
    if set_aside_code in {"SBA", "SBP"}:
        reasons.append(
            ScoreReason("set_aside", f"Small Business ({set_aside_code})", weights["set_aside_points"])
        )
        score += weights["set_aside_points"]
    elif set_aside_code in {"8A", "8AN", "WOSB", "EDWOSB", "SDVOSBC", "HZC", "HZS", "IEE", "ISBEE"}:
        reasons.append(
            ScoreReason(
                "set_aside_conditional",
                f"{set_aside_code} — requires confirmed eligibility",
                0,
            )
        )

    # ---- NAICS bonus ----
    naics = (opportunity.get("naics_code") or "").strip()
    for prefix, points in PROFILE_NAICS_BOOSTS[profile].items():
        if naics.startswith(prefix) and points:
            reasons.append(ScoreReason("naics_hint", f"NAICS {prefix}", points))
            score += points
            break

    # ---- Runway / deadline ----
    deadline = _parse_deadline(opportunity.get("response_deadline"))
    if deadline:
        days_out = (deadline - today).days
        if days_out < 0:
            reasons.append(
                ScoreReason("deadline_expired", f"deadline {deadline.isoformat()}", -5)
            )
            score -= 5
        elif 5 <= days_out <= 90:
            reasons.append(
                ScoreReason("manageable_runway", f"{days_out} days out", weights["runway_points"])
            )
            score += weights["runway_points"]
        elif days_out < 5:
            reasons.append(
                ScoreReason("tight_runway", f"{days_out} days out", 0)
            )

    # ---- Notice type ----
    notice_type = (opportunity.get("type") or "").lower()
    if notice_type and not any(b in notice_type for b in BIDDABLE_TYPES):
        if any(info in notice_type for info in INFO_TYPES):
            reasons.append(
                ScoreReason("info_notice", notice_type, weights["info_type_points"])
            )
            score += weights["info_type_points"]

    # ---- Weak-keyword penalty: no tier1/tier2 hits but loose IT terms ----
    structural_hit = any(
        reason.kind in {"tier1_keyword", "tier2_keyword"} for reason in reasons
    )
    weak_only = (
        not structural_hit
        and any(term in haystack for term in [
            " it ", "information technology", "cybersecurity", "cyber",
        ])
    )
    if weak_only:
        reasons.append(
            ScoreReason("weak_keyword_only", "no tier-1/tier-2 evidence", weights["weak_keyword_points"])
        )
        score += weights["weak_keyword_points"]

    # ---- No-evidence penalty ----
    # Keep commodity buys from earning a "promising" band via set-aside +
    # runway alone. Without a tier-1 or tier-2 hit we apply -2.
    if not structural_hit:
        reasons.append(
            ScoreReason("no_technical_evidence", "no tier-1/tier-2 match", -2)
        )
        score -= 2

    lanes = _detect_lanes(title_l, desc_l, profile)

    return ScoreResult(
        notice_id=str(opportunity.get("notice_id") or ""),
        title=str(opportunity.get("title") or ""),
        score=score,
        band=_band_for(score),
        lanes=lanes,
        reasons=reasons,
    )


def bulk_score(
    opportunities: Iterable[dict[str, Any]],
    profile: str = "technical_services",
    today: date | None = None,
) -> list[ScoreResult]:
    return [score_opportunity(opp, profile=profile, today=today) for opp in opportunities]


# ---------------------------------------------------------------------------
# CLI for ad-hoc scoring
# ---------------------------------------------------------------------------


def _cli() -> None:
    import argparse
    import json
    import sqlite3
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Score opportunities from the local SAM mirror.")
    parser.add_argument("--db", default=str(Path(__file__).resolve().parent.parent / "data" / "contracts.db"))
    parser.add_argument("--profile", default="technical_services", choices=available_profiles())
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--min-score", type=int, default=2)
    parser.add_argument("--keyword", help="Optional keyword pre-filter")
    parser.add_argument("--days", type=int, default=30, help="Posted within last N days")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"DB not found at {db_path}. Run scripts/sync_bulk.py first.")

    where = ["active = 'Yes'"]
    params: list[Any] = []
    if args.keyword:
        where.append("(title LIKE ? OR description LIKE ?)")
        params.extend([f"%{args.keyword}%", f"%{args.keyword}%"])
    if args.days > 0:
        from datetime import timedelta
        cutoff = (datetime.now(LOCAL_TZ).date() - timedelta(days=args.days)).isoformat()
        where.append("posted_date >= ?")
        params.append(cutoff)
    where_sql = " AND ".join(where)
    sql = f"""
        SELECT notice_id, title, sol_number, department, sub_tier, posted_date,
               type, set_aside, set_aside_code, response_deadline, naics_code,
               pop_city, pop_state, active, link, description
        FROM opportunities
        WHERE {where_sql}
        ORDER BY posted_date DESC
        LIMIT ?
    """
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute(sql, params + [args.limit * 10]).fetchall()]

    scored = bulk_score(rows, profile=args.profile)
    scored = [s for s in scored if s.score >= args.min_score]
    scored.sort(key=lambda s: s.score, reverse=True)
    scored = scored[: args.limit]

    if args.json:
        print(json.dumps([s.to_dict() for s in scored], indent=2))
        return

    print(f"\nProfile: {args.profile}   min_score={args.min_score}   shown={len(scored)}\n")
    for i, result in enumerate(scored, 1):
        print(f"[{i}] score={result.score} band={result.band} lanes={','.join(result.lanes) or '-'}")
        print(f"    {result.title}")
        for reason in result.reasons:
            sign = "+" if reason.points > 0 else ""
            print(f"      {sign}{reason.points:>3}  {reason.kind:<22} {reason.detail}")
        print()


if __name__ == "__main__":
    _cli()
