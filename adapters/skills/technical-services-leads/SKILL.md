---
name: technical-services-leads
description: "Find and evaluate public federal opportunities aligned to the operator's small-team field-installation business: security cameras, CCTV/video monitoring, access control, structured cabling, low-voltage data cabling, bounded fiber, and adjacent network installs. Use for SAM.gov lead scans, set-aside candidate research, solicitation fit analysis, or opportunity ranking."
---

# Technical Services Leads

Use this skill for federal small-team field-installation opportunity research.
the operator's canonical fit and exclusion rules are in:

`<PROJECT_DIR>\criteria\TECHNICAL_SERVICES_PROFILE.md`

## Workflow

1. Read `criteria/TECHNICAL_SERVICES_PROFILE.md`.
2. Prefer MCP tools from `technical_contract_research` when available:
   `get_technical_services_profile`, `search_opportunities`,
   `document_index_status`, `ingest_public_document`, and `search_documents`.
3. Search multiple lanes independently: CCTV/security cameras; video
   monitoring; access control; structured cabling; data cabling; low voltage;
   Cat6; fiber; bounded adjacent network installs; Total Small Business
   opportunities under `561621` and filtered `238210`.
4. Reject closed deadlines, unrelated construction or high-voltage work,
   product-only buys, proprietary sustainment without a documented route, and
   work that is too large for a two-to-three-person crew.
5. For a serious candidate, verify current official notice data and index one
   public SOW/PWS/requirements document before recommending it.
6. Call `publish_research_scan` exactly once with the final curated `assess now`
   and `monitor/partner` results. Publish an empty item list when no supported
   fit is found. Do not publish intermediate discovery results or rejected
   false positives. A chat scan is not complete until the final response
   includes the Workbench scan ID returned by the publish call.

Direct-script fallback from the project root:

```powershell
python .\scripts\search_bulk.py "<term>" --active-only --json
python .\scripts\document_store.py search "<query>" --notice-id "<notice-id>" --json
```

## Judgement Rules

- Security-camera, video-monitoring, access-control, structured-cabling, and
  bounded fiber installation work are primary fits.
- Small network, Wi-Fi, VTC, AV-over-IP, alarm, and intercom installations are
  valid when documents establish executable field scope.
- Surface Total Small Business set-asides as favorable candidates, but do not
  claim eligibility or any special certification status without confirmation.
- Treat product resale, OEM equipment, license, technician-registration,
  electrical-power, code, insurance, staffing, travel, and 24/7
  managed-operation requirements as blockers or conditional routes unless
  evidence resolves them.
- Returning no strong fit is better than recommending unrelated work.

## Output

Report the opportunity lane, official link, deadline, set-aside, supported
technical fit, indexed-document evidence, unresolved blockers, and a practical
disposition: `assess now`, `monitor/partner`, or `reject`.

The final curated result set must also be written to the production Stormwind
Workbench with `publish_research_scan` so the operator can open it from Past
Scans without rerunning the search.

If the MCP publish tool is unavailable, publish the same final set through the
local fallback from the project root:

```powershell
python .\scripts\swcb.py publish-scan --summary "Final scan summary" --item "{\"notice_id\":\"...\",\"title\":\"...\",\"disposition\":\"assess now\"}"
```

Use repeated `--item` flags or `--input path\to\scan.json` for multi-item
scans. The fallback writes an `ai_research` scan into the same Workbench table.
