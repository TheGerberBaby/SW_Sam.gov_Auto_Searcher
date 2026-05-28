---
name: technical-services-leads
description: "Find and evaluate public federal opportunities aligned to the operator's technical-services capabilities: Elastic/OpenSearch, AI search and RAG, vector/semantic retrieval, observability/log analytics/SIEM, AI/data/platform services, and VTC/unified-communications/network engineering. Use for SAM.gov lead scans, set-aside candidate research, solicitation fit analysis, or technical opportunity ranking."
---

# Technical Services Leads

Use this skill for broad federal technical-services opportunity research.
the operator's canonical fit and exclusion rules are in:

`<PROJECT_DIR>\TECHNICAL_SERVICES_PROFILE.md`

## Workflow

1. Read `TECHNICAL_SERVICES_PROFILE.md`.
2. Prefer MCP tools from `technical_contract_research` when available:
   `get_technical_services_profile`, `search_opportunities`,
   `document_index_status`, `ingest_public_document`, and `search_documents`.
3. Search multiple lanes independently: Elastic/search; AI/RAG/vector search;
   observability/SIEM/logging; AI/data/platform services; VTC/UC/network
   engineering; Total Small Business opportunities in relevant IT NAICS.
4. Reject closed deadlines, acronym false positives, unrelated construction or
   supply work, and weak generic-IT matches.
5. For a serious candidate, verify current official notice data and index one
   public SOW/PWS/requirements document before recommending it.

Direct-script fallback from the project root:

```powershell
python .\scripts\search_bulk.py "<term>" --active-only --json
python .\scripts\document_store.py search "<query>" --notice-id "<notice-id>" --json
```

## Judgement Rules

- Elastic/OpenSearch and AI-search/RAG work are primary fits.
- Observability, SIEM, AI/data engineering, and VTC/network integration are
  valid when documents establish a real implementation or engineering scope.
- Surface Total Small Business set-asides as favorable candidates, but do not
  claim eligibility or any special certification status without confirmation.
- Treat product resale, OEM equipment, license renewal, contract-vehicle,
  clearance, staffing, and 24/7 managed-operation requirements as blockers or
  conditional routes unless evidence resolves them.
- Returning no strong fit is better than recommending unrelated work.

## Output

Report the opportunity lane, official link, deadline, set-aside, supported
technical fit, indexed-document evidence, unresolved blockers, and a practical
disposition: `assess now`, `monitor/partner`, or `reject`.
