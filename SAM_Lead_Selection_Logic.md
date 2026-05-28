# SAM.gov Lead Selection Logic — Portable Spec
**Reverse-engineered from live searches run 2026-05-25**  
**Domain used as source: specialty trades / construction. All domain values are labeled — swap them out for any field.**

> **Historical example only:** The active default for the operator is technical
> services work. Read `TECHNICAL_SERVICES_PROFILE.md` before performing current
> lead research. Use `ELASTIC_LEAD_PROFILE.md` only for an Elastic-specific
> sweep. Do not use the construction values below unless explicitly requested.

---

## 1. Signal Extraction

Every field pulled from a SAM.gov `/opportunities/v2/search` response record, what it contains, and how it was used.

| Field | JSON path in API record | Used for |
|-------|------------------------|----------|
| Notice ID | `noticeId` | Deduplication |
| Title | `title` | Keyword matching, scope inference |
| Solicitation number | `solicitationNumber` | Output / reference |
| Full agency chain | `fullParentPathName` | Agency tier scoring (see §2) |
| Short agency | last segment of `fullParentPathName` split on `.` | Display |
| NAICS code | `naicsCode` | Domain filter (primary gate) |
| PSC / classification code | `classificationCode` | Domain filter (secondary gate) |
| Notice type | `type` and `baseType` | Procurement type filter |
| Set-aside code | `typeOfSetAside` | Eligibility scoring |
| Set-aside description | `typeOfSetAsideDescription` | Human-readable output |
| Response deadline | `responseDeadLine` (ISO 8601 with tz offset) | Deadline filter; urgency scoring |
| Posted date | `postedDate` | Recency filter (search window) |
| Active flag | `active` | Hard filter (must be "Yes") |
| Archive type | `archiveType` | Signal: `auto15` = small/quick buy |
| Award record | `award.awardee` | Already-awarded filter |
| Place of performance — country | `placeOfPerformance.country.code` | Domestic filter |
| Place of performance — state | `placeOfPerformance.state.code` | Geographic filter (optional) |
| Place of performance — city | `placeOfPerformance.city.name` | Geographic filter (optional) |
| SAM link | `uiLink` | Output |
| Point of contact — email | `pointOfContact[0].email` | Output (who to call) |

**Fields NOT in the API record (require fetching attached documents):**
- Estimated / ceiling value — in RFP PDF attachments
- Performance period (base + options)
- Statement of Work / PWS detail
- Incumbent contractor name
- Required clearance level

---

## 2. Scoring Model

### 2a. Binary hard filters (applied before scoring — a "no" on any eliminates the record)

| Test | Logic | Notes |
|------|-------|-------|
| Active | `active == "Yes"` | API field |
| Deadline open | `responseDeadLine[:10] >= TODAY` | Drop closed opportunities |
| Domestic | `placeOfPerformance.country.code in ("USA", "", null)` | Drops overseas embassy / OCONUS postings |
| Not already awarded | `award.awardee` is empty / null | Awarded records still show as active |
| Not excluded notice type | `baseType NOT IN ["Sources Sought"]` | User explicitly excluded these |
| Not excluded vehicle type | title.lower() does NOT contain any of: `idiq`, `indefinite delivery`, `bpa`, `blanket purchase agreement`, `multiple award`, `omnibus`, `cso` (unless specifically targeted) | Vehicles ≠ direct buys |

### 2b. Easy-Win Score (0–5 points)

Apply these additive point rules to every record that passes 2a. Maximum score = 5.

| Points | Condition | Rationale |
|--------|-----------|-----------|
| **+2** | `typeOfSetAside == "SBA"` (Total Small Business) | Largest eligibility reduction; most competitors excluded |
| **+1** | `baseType == "Combined Synopsis/Solicitation"` | Simplified acquisition; no formal proposal; just a quote |
| **+1** | Title matches **scope-narrow keywords** (see §3b for domain values) | Single deliverable = lower risk, easier to price |
| **+1** | Agency in **repeat-buyer tier** (see §3b for domain values) | Agencies with a pattern of small repeat buys have lower barriers |
| **−1** | `typeOfSetAside in ["HZC", "SDVOSBC", "8A", "WOSB", "EDWOSB", "ISBEE"]` | Requires specific certification you may not hold |
| **−1** | `placeOfPerformance.country.code NOT IN ("USA", "", null)` | Already filtered out, but kept as explicit penalty if missed |
| **+1** | `responseDeadLine[:10]` is within **7 days of today** | Short runway usually signals small, urgent, well-scoped work |
| **+0** | `typeOfSetAside == "NONE"` or open | Neutral — still biddable, just wider competition |

**Score → display tier:**
- 5: ★★★★★ / 🏆 — bid today
- 4: ★★★★ — strong, queue for this week  
- 3: ★★★ — worth reviewing before deadline
- 1–2: skip unless it's your exact specialty

### 2c. Implicit judgment made explicit

These were "I know this looks good" calls during curation. Quantified below so you can replicate or override them.

| Implicit call | Made explicit | Weight |
|---------------|--------------|--------|
| "USCG paints a lot of small stations" | If agency contains "COAST GUARD" AND title contains paint/coating keyword → +0.5 (round up) | +0.5 |
| "NASA Combined Synopsis = usually small, quick" | If `fullParentPathName` contains "NASA" AND baseType = Combined Synopsis → treat archiveType `auto15` as confirmation of small buy | +0.5 |
| "Sole source notice = someone already owns this" | If title contains "sole source" OR "notice of intent" → score = 0 (skip, even if SBA) | Override to 0 |
| "IDIQ / CSO = not a direct buy" | `responseDeadLine > 2 years from today` is a strong signal of an open-ended vehicle → skip | Override to 0 |
| "Renewal = reseller relationship required" | If title contains "renewal" → flag as COTS/resale; note vendor authorization barrier | No score change; add flag |
| "Draft solicitation = too early to bid" | If title contains "DRAFT" → downgrade by 1 point | −1 |

---

## 3. Filters Applied

### 3a. Domain-independent filters (keep these for any field)

| Filter | Type | Value/Logic |
|--------|------|-------------|
| Active only | Hard | `active == "Yes"` |
| Deadline not passed | Hard | `responseDeadLine[:10] >= TODAY` |
| US domestic only | Hard | country code = USA or blank |
| Not already awarded | Hard | `award.awardee` is null/empty |
| Not Sources Sought | Hard | `baseType != "Sources Sought"` |
| Not IDIQ/BPA vehicle | Hard | title keyword exclusion list (see §2a) |
| Search window | Soft | `postedFrom` = 30–60 days back (catches active windows) |
| Result cap | Soft | `limit=25–50` per NAICS query |
| Deduplication | Post-processing | `noticeId` uniqueness across merged query results |
| SBA/open set-aside preferred | Scoring | +2 for SBA; −1 for restricted certs you don't hold |
| Short deadline = simple | Scoring | +1 if ≤ 7 days; used as proxy for small scope |
| Combined Synopsis preferred | Scoring | +1 for simplified acquisition format |

### 3b. Domain-specific filters — CONSTRUCTION (swap these out)

| Filter | Current value (construction) | Swap slot |
|--------|------------------------------|-----------|
| NAICS codes queried | `238220, 238210, 238160, 238320, 238910, 238310, 238990, 236220, 237310` | **[YOUR NAICS]** |
| NAICS prefix broad sweep | `238` (all specialty trades via LIKE `238%`) | **[YOUR PREFIX]** |
| PSC prefix expected | `Z` prefix = construction/maintenance/repair of real property | **[YOUR PSC]** |
| Scope-narrow title keywords | `HVAC, chiller, roofing, roof, painting, paint, electrical, generator, plumbing, renovation, flooring, drywall` | **[YOUR KEYWORDS]** |
| Repeat-buyer agencies | `US Coast Guard, National Park Service, VA Medical Centers, Army Corps of Engineers, Air Force MICC` | **[YOUR AGENCIES]** |
| Excluded NAICS | `561xxx (facilities management), 23xxxx (in IT context)` | **[YOUR EXCLUSIONS]** |
| ptype queried | `o,k,p` (Solicitation + Combined Synopsis + Presolicitation) | **[YOUR PTYPE]** |
| Geographic filter | None applied (national sweep); optionally `--state AZ,NM,TX,CO` | **[YOUR STATES]** |
| Set-aside priority | SBA → open → HZC/SDVOSBC (if certified) | **[YOUR CERTS]** |

---

## 4. The Swap Interface

A single table. Left column = what was used for construction. Right column = blank. Fill in the right and you have a fully re-targeted search.

| Parameter | Construction value used | Your domain value |
|-----------|------------------------|-------------------|
| **Primary NAICS codes** | `238220, 238210, 238160, 238320, 238910` | `[FILL IN]` |
| **Broad NAICS prefix (optional sweep)** | `238` | `[FILL IN]` |
| **PSC codes / prefixes** | `Z1, Z2` (construction/maintenance of real property) | `[FILL IN]` |
| **Title keyword inclusions** | `HVAC, roofing, painting, electrical, generator, plumbing, renovation` | `[FILL IN]` |
| **Title keyword exclusions** (in addition to universal ones) | *(none beyond universal)* | `[FILL IN]` |
| **Procurement types** (`ptype`) | `o,k,p` | `[FILL IN]` |
| **Preferred agency patterns** | `COAST GUARD, NATIONAL PARK SERVICE, VETERANS AFFAIRS, AIR FORCE` | `[FILL IN]` |
| **Set-asides you're certified for** | `SBA` (Total Small Business) | `[FILL IN]` |
| **Geographic filter** | None (national) | `[FILL IN]` |
| **Search window (days back)** | `30` | `[FILL IN]` |
| **Result cap per NAICS** | `25` | `[FILL IN]` |
| **Scope-narrow signal keywords** | Single building / single trade terms: `"Building 840", "replace", "repaint", "R&R"` | `[FILL IN]` |
| **Scope-complex penalty keywords** | `"design-build", "multi-phase", "base year plus"` | `[FILL IN]` |

---

## 5. Portable Re-Run Prompt

Copy the block below into a fresh chat. Fill every `[FILL IN]` and the assistant will reproduce the exact methodology.

```
You are a federal contracting lead researcher. Use the SAM.gov API (key: [FILL IN: your SAM API key]) 
to find small, simple opportunities I can win as a solo/small business. 
Follow this exact methodology:

─────────────────────────────────────────
STEP 1 — QUERY
─────────────────────────────────────────
For each NAICS code in [FILL IN: comma-separated NAICS list], call:
  GET https://api.sam.gov/opportunities/v2/search
  params:
    api_key    = [FILL IN]
    ncode      = [one NAICS per call]
    ptype      = [FILL IN: e.g. k   or   o,k,p   or   k,o]
    postedFrom = [FILL IN: MM/DD/YYYY — 30-60 days back]
    postedTo   = [today's date MM/DD/YYYY]
    limit      = 25
    offset     = 0

Run all NAICS queries in parallel and merge results. Deduplicate by noticeId.

─────────────────────────────────────────
STEP 2 — HARD FILTERS (drop any record failing any test)
─────────────────────────────────────────
  • active == "Yes"
  • responseDeadLine[:10] >= TODAY
  • placeOfPerformance.country.code in ("USA", "", null)
  • award.awardee is null or empty  (not already awarded)
  • baseType NOT IN ["Sources Sought"]
  • title.lower() does NOT contain any of:
      "idiq","indefinite delivery","bpa","blanket purchase","multiple award",
      "omnibus","draft"  [add domain-specific exclusions: FILL IN]
  • [FILL IN: any additional domain-specific hard filters, e.g. "exclude NAICS 23xxxx"]

─────────────────────────────────────────
STEP 3 — SCORE each surviving record (0–5 pts)
─────────────────────────────────────────
  +2  typeOfSetAside == "SBA"
  +1  baseType == "Combined Synopsis/Solicitation"
  +1  title contains any scope-narrow keyword: [FILL IN: e.g. "renewal","license","subscription" OR "paint","replace","upgrade"]
  +1  fullParentPathName contains any preferred agency: [FILL IN: e.g. "COAST GUARD","VA","NASA"]
  +1  responseDeadLine[:10] is within 7 days of today
  −1  typeOfSetAside in ["HZC","SDVOSBC","8A","WOSB","EDWOSB","ISBEE"] AND I am NOT certified for it
       [FILL IN: list which certs you DO hold so those become 0 instead of −1]
  −1  title contains "sole source" OR "notice of intent to sole source"  → override total score to 0 (skip)
  −1  responseDeadLine is more than 2 years away  → override total score to 0 (it's a vehicle, not a buy)

─────────────────────────────────────────
STEP 4 — OUTPUT TABLE
─────────────────────────────────────────
Sort surviving records by responseDeadLine ASC. Cap at 50.

For each record output these columns:
  Title | Agency (last segment of fullParentPathName) | NAICS | PSC (classificationCode) |
  Set-Aside (typeOfSetAsideDescription) | Est Value (write "See RFP" — not in API) |
  Response Deadline | Solicitation Number | Notice ID | SAM Link (uiLink)

─────────────────────────────────────────
STEP 5 — FLAG EASY WINS
─────────────────────────────────────────
From the sorted table, identify the 3–5 records with:
  • Score ≥ 4, AND
  • At least one of:
      - baseType == "Combined Synopsis/Solicitation"  (simplified acquisition = just submit a quote)
      - title suggests COTS / subscription / renewal  (known price, no custom dev risk)
      - title suggests narrow single-item scope  (one building, one system, one piece of software)
      - Agency is a repeat small-buy customer in this domain

For each flagged record, write a short note covering:
  (a) Why it's simple
  (b) What you'd actually do / deliver
  (c) One watch-out or blocker to verify before bidding

─────────────────────────────────────────
MY DOMAIN INPUTS
─────────────────────────────────────────
  NAICS codes:         [FILL IN]
  PSC codes/prefixes:  [FILL IN]
  ptype filter:        [FILL IN]
  Title keywords (include): [FILL IN]
  Title keywords (exclude): [FILL IN — add to universal exclusion list above]
  Preferred agencies:  [FILL IN]
  Set-asides I hold:   [FILL IN — e.g. SBA, SDVOSBC, HZC, 8A, WOSB]
  Geographic filter:   [FILL IN — e.g. state=TX,CO,NM  or  leave blank for national]
  Search window:       [FILL IN — e.g. 30 or 60 days back]
  SAM API key:         [FILL IN]
```

---

*Document version: 2026-05-25. Source sessions: construction trades search + IT/software solo buys search.*
