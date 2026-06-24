<!--
Living business profile for Stormwind Contracting. This file is the
"spine" of the project per the Government-Contracting OS plan
([docs/V2_FEATURES.md](docs/V2_FEATURES.md) -> Stage 1 -> see
[docs/STAGE1_SPINE.md](docs/STAGE1_SPINE.md)). It is read by
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

_Last reviewed: 2026-06-17_

## Identity

- **Operator:** Jeremy Gerbert
- **Business name:** Stormwind Contracting
- **Operator status:** Service-disabled veteran (qualifies for SDVOSB once
  certification clears)
- **Operating model:** owner-led field-services business with a maximum
  **two-to-three-person crew** for near-term prime work
- **Day-job constraint:** W2 employee — schedule field work deliberately
- **Operating timezone:** America/New_York

## Place of performance focus

- Primary: **DMV** (Washington DC, Northern Virginia, Maryland)
- On-site outside the DMV: case-by-case when travel, warranty response, and
  licensing are practical
- Remote-only work is secondary to field installation work

## Primary NAICS

- **561621** — Security Systems Services (except Locksmiths)
  - SBA size standard: verify against the current
    [13 CFR 121.201 table](https://www.sba.gov/document/support--table-size-standards)
    at the moment of any filing.

## Secondary / supporting NAICS

| NAICS | Category | Use |
| --- | --- | --- |
| 238210 | Electrical contractors and other wiring installation contractors | Structured cabling, low-voltage, and fiber discovery hint |
| 541512 | Computer systems design services | Network configuration and integration discovery hint |
| 334290 | Other communications equipment manufacturing | Equipment-heavy notice discovery hint only |

## Capability lanes (what we actually pursue)

Detailed scoring rules live in [criteria/TECHNICAL_SERVICES_PROFILE.md](criteria/TECHNICAL_SERVICES_PROFILE.md)
and [criteria/ELASTIC_LEAD_PROFILE.md](criteria/ELASTIC_LEAD_PROFILE.md).
Short version:

### Tier-1 — direct technical fit

- Security-camera, CCTV, and video-monitoring installation and upgrades.
- Electronic access-control installation: card readers, badge readers,
  door-control components, and small physical-access systems.
- Structured cabling, low-voltage data cabling, Cat6, patch panels, cable
  testing, and bounded fiber runs.

### Tier-2 — adjacent technical fit

- Intrusion-detection and alarm-system installation or upgrade work when the
  exact licensing, OEM, and code requirements are executable.
- Small network, Wi-Fi, AV-over-IP, VTC, or intercom installation jobs when
  field labor, testing, and handoff are the core deliverables.

### Conditional

- Fire-alarm, life-safety, electrical-power, proprietary OEM, and recurring
  maintenance work: pursue only after confirming the required license,
  technician registration, code responsibility, OEM route, and response SLA.
- Multi-site or out-of-area installation work: pursue only when a
  two-to-three-person crew can meet travel, schedule, and warranty obligations.
- Product-heavy work: pursue only when the margin, sourcing, and installation
  responsibility are understood.
- Home-office product sourcing and resale: scan only when explicitly requested.
  Prefer bounded commercial-product RFQs with one or a few standard items,
  distributor-supported fulfillment, FOB-destination freight, adequate quote
  runway, manageable cash flow, and a documented nonmanufacturer-rule check.

### Out of scope by default

Large construction programs, high-voltage electrical work, broad facility
repair, janitorial, unrelated trades, nationwide staffing, 24/7 guard
operations, commodity resale without installation, medical/lab supplies,
ammunition, fuel delivery, and food service. Construction material in this
repo is historical test data only unless the operator explicitly requests it.

## Certifications, registrations, business posture

Detailed status, dependencies, and next-actions live in the
[tasks/](tasks/) directory. Quick reference:

| Item | Status | Notes |
| --- | --- | --- |
| Legal entity formed | **held** | Confirmed complete in [001-entity-formation.md](tasks/001-entity-formation.md) |
| EIN | **held** | Confirmed 2026-05-31; full TIN intentionally not stored in this repo |
| SAM.gov identifiers | **held** | UEI `LE4ZH9KC7BU1`; CAGE `1ZW38` |
| SAM.gov registration | **held** | Entity Workspace status `Active`; expires Apr 25, 2027; SAM public search authorization is `Yes`; SBA SBS public display is enabled |
| **SDVOSB (federal, via SBA VetCert)** | **planned** | [003-sdvosb-vetcert.md](tasks/003-sdvosb-vetcert.md) — free, ~12-day avg processing, mandatory since 2024-12-22 |
| FinCEN BOI filing | **planned** | [004-fincen-boi.md](tasks/004-fincen-boi.md) |
| Virginia SWaM + state SDVOSB (DSBSD) | **planned** | [005-virginia-swam.md](tasks/005-virginia-swam.md) |
| eVA registration | **planned** | [006-eva-registration.md](tasks/006-eva-registration.md) |
| Virginia field-installation licensing check | **planned** | [009-field-installation-licensing.md](tasks/009-field-installation-licensing.md) |
| First home-office reseller quote assessed | **in-progress** | [010-nist-scissor-lift-reseller-quote.md](tasks/010-nist-scissor-lift-reseller-quote.md) |
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

- **Project root:** repository root (`<PROJECT_DIR>` on a local machine)
- Local SAM.gov SQLite mirror — [scripts/sync_bulk.py](scripts/sync_bulk.py)
- Local Elasticsearch document evidence index — [scripts/document_store.py](scripts/document_store.py)
- Lead scoring engine + watchlist (v2) — [scripts/scoring.py](scripts/scoring.py), [scripts/watchlist.py](scripts/watchlist.py)
- Daily digest + local dashboard — [scripts/digest.py](scripts/digest.py), [scripts/dashboard.py](scripts/dashboard.py)
- Unified CLI — `swcb` ([scripts/swcb.py](scripts/swcb.py))
- FastMCP server for Claude Code / Codex / Claude Desktop — [scripts/mcp_server.py](scripts/mcp_server.py)
- This spine — [PROFILE.md](PROFILE.md), [tasks/](tasks/), [criteria/](criteria/), [ROADMAP_REVIEW.md](ROADMAP_REVIEW.md)
- Long-form docs — [docs/](docs/)

## How agents should use this file

1. Read PROFILE.md before suggesting business actions or interpreting "fit."
2. Treat `unknown` fields as questions to ask Jeremy at a natural pause —
   not blockers, not invented answers.
3. When facts change, edit this file in the same turn that records the
   change. Commit so the history is auditable.
4. The "never hard-block" scheduling rule lives in [ROADMAP_REVIEW.md](ROADMAP_REVIEW.md);
   apply it whenever you propose what to work on next.
