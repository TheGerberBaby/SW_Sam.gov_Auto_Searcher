<!--
Living business profile for Stormwind Contracting. This file is the
"spine" of the project per the Government-Contracting OS plan
(V2_FEATURES.md → Stage 1 → see STAGE1_SPINE.md). It is read by
agents (Claude Code, Codex) and humans to ground every other decision.

Edit freely. Status fields use a fixed vocabulary:
  held         confirmed in place
  pending      filed / submitted, awaiting external action
  in-progress  Jeremy is actively working on it
  planned      committed-to-do but not started
  blocked      cannot advance until a dependency lifts
  dropped      explicitly decided not to pursue (record the reason)
  unknown      Jeremy hasn't told the agent yet (default for new fields)

Many fields below are seeded with reasonable defaults marked `unknown`
or `planned`. Correct anything wrong on first read.
-->

# Stormwind Contracting — Living Business Profile

_Last reviewed: 2026-05-29_

## Identity

- **Operator:** Jeremy Gerbert
- **Business name:** Stormwind Contracting
- **Operator status:** Service-disabled veteran (qualifies for SDVOSB once
  certification clears)
- **Day-job constraint:** W2 employee — time-constrained solo founder
- **Operating timezone:** America/New_York

## Place of performance focus

- Primary: **DMV** (Washington DC, Northern Virginia, Maryland)
- Remote-eligible work is in scope
- On-site outside the DMV: case-by-case, lower priority

## Primary NAICS

- **541512** — Computer Systems Design Services
  - SBA size standard: verify against the current
    [13 CFR 121.201 table](https://www.sba.gov/document/support--table-size-standards)
    at the moment of any filing.

## Secondary / supporting NAICS

| NAICS | Category | Use |
| --- | --- | --- |
| 541511 | Custom computer programming services | Discovery hint |
| 541513 | Computer facilities management services | Discovery hint |
| 541519 | Other computer related services | Discovery hint |
| 518210 | Computing infrastructure, data processing, hosting | Discovery hint |
| 517810 | Telecommunications | VTC/network discovery hint |
| 541715 | R&D in physical, engineering, life sciences | Discovery hint |

## Capability lanes (what we actually pursue)

Detailed scoring rules live in [criteria/TECHNICAL_SERVICES_PROFILE.md](criteria/TECHNICAL_SERVICES_PROFILE.md)
and [criteria/ELASTIC_LEAD_PROFILE.md](criteria/ELASTIC_LEAD_PROFILE.md).
Short version:

### Tier-1 — direct technical fit

- Elasticsearch, Elastic Stack, Kibana, Logstash, Elastic Agent / Fleet,
  Elastic Security, OpenSearch.
- AI search / RAG / vector / semantic / hybrid retrieval; LLM-grounded
  enterprise content systems.
- Observability, log analytics, APM, SIEM, detection engineering,
  security analytics.

### Tier-2 — adjacent technical fit

- AI/ML engineering services, data engineering, DevSecOps automation,
  cloud platform integration, zero-trust telemetry.
- Network engineering, VTC, unified communications, AV-over-IP,
  network modernization (when the SOW includes design / integration /
  configuration / engineering / monitoring).

### Conditional

- Hardware, appliances, license renewals: only with a meaningful
  services component or an established reseller/partner route
  (currently **none confirmed**).
- Staffing, managed-ops, broad enterprise programs: only when scope,
  team size, clearance, location, and subcontracting are realistic.

### Out of scope by default

Construction, facility repair, janitorial, trades, AV install only,
commodity resale, medical/lab supplies, ammunition, fuel delivery,
food service. (Construction material in this repo is historical test
data only.)

## Certifications, registrations, business posture

Detailed status, dependencies, and next-actions live in the
[tasks/](tasks/) directory. Quick reference:

| Item | Status | Notes |
| --- | --- | --- |
| Legal entity formed | **unknown** | See [001-entity-formation.md](tasks/001-entity-formation.md) — confirm or correct |
| EIN | **unknown** | Dependency of every cert below |
| SAM.gov registration | **unknown** | Required prerequisite for VetCert |
| **SDVOSB (federal, via SBA VetCert)** | **planned** | [003-sdvosb-vetcert.md](tasks/003-sdvosb-vetcert.md) — free, ~12-day avg processing, mandatory since 2024-12-22 |
| FinCEN BOI filing | **planned** | [004-fincen-boi.md](tasks/004-fincen-boi.md) |
| Virginia SWaM + state SDVOSB (DSBSD) | **planned** | [005-virginia-swam.md](tasks/005-virginia-swam.md) |
| eVA registration | **planned** | [006-eva-registration.md](tasks/006-eva-registration.md) |
| First micro-purchase bid submitted | **planned** | [007-first-micro-purchase-bid.md](tasks/007-first-micro-purchase-bid.md) — validation milestone |

## Set-aside strategy

- **Total Small Business (SBA)** opportunities are the default target while
  SDVOSB certification is pending.
- **SDVOSB** is the highest-leverage future lane: federal goal is **5%**
  (raised from 3% by FY2024 NDAA Sec. 863; SDVOSBs received $31.9 B in
  FY2024 per SBA). Mandatory certification since 2024-12-22 — self-cert
  no longer counts.
- **8(a), WOSB, EDWOSB, HUBZone, ISBEE, IEE** — eligibility not claimed
  unless explicitly confirmed; surface as "monitor for partner path."
- Sources Sought / RFI: pipeline-building, not current bids.

## Operating tooling

- **Project root:** `C:\Users\dflaj\OneDrive\Desktop\projects\SW_Contracting_Bots`
- Local SAM.gov SQLite mirror — [scripts/sync_bulk.py](scripts/sync_bulk.py)
- Local Elasticsearch document evidence index — [scripts/document_store.py](scripts/document_store.py)
- Lead scoring engine + watchlist (v2) — [scripts/scoring.py](scripts/scoring.py), [scripts/watchlist.py](scripts/watchlist.py)
- Daily digest + local dashboard — [scripts/digest.py](scripts/digest.py), [scripts/dashboard.py](scripts/dashboard.py)
- Unified CLI — `swcb` ([scripts/swcb.py](scripts/swcb.py))
- FastMCP server for Claude Code / Codex / Claude Desktop — [scripts/mcp_server.py](scripts/mcp_server.py)
- This spine — [PROFILE.md](PROFILE.md), [tasks/](tasks/), [criteria/](criteria/), [ROADMAP_REVIEW.md](ROADMAP_REVIEW.md)

## How agents should use this file

1. Read PROFILE.md before suggesting business actions or interpreting "fit."
2. Treat `unknown` fields as questions to ask Jeremy at a natural pause —
   not blockers, not invented answers.
3. When facts change, edit this file in the same turn that records the
   change. Commit so the history is auditable.
4. The "never hard-block" scheduling rule lives in [ROADMAP_REVIEW.md](ROADMAP_REVIEW.md);
   apply it whenever you propose what to work on next.
