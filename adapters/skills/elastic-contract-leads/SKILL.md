---
name: elastic-contract-leads
description: Find and evaluate public SAM.gov opportunities aligned to the operator's Elastic engineering work, including Elasticsearch, Elastic Stack, OpenSearch, Kibana, Logstash, Fleet, observability, log analytics, SIEM, and search-platform implementation. Use when asked to find federal work, scan opportunities, rank leads, or analyze a solicitation for technical fit.
---

# Elastic Contract Leads

Use this skill to research federal opportunities for an Elastic engineer. Do
not return construction, facility repair, physical trade, AV-installation, or
commodity-resale work unless the operator explicitly asks for it.

Project root:

`<PROJECT_DIR>`

## Required Context

Before ranking opportunities, read:

- `criteria/ELASTIC_LEAD_PROFILE.md` for fit, exclusions, terms, and scoring.
- `docs/DOCUMENT_INDEX.md` when a public solicitation attachment is available.
- `scripts/search_bulk.py` or its usage output before running structured
  discovery if flags are unclear.

The construction values in `criteria/SAM_Lead_Selection_Logic.md` are historical
examples, not active defaults.

## Discovery

When the `technical-contract-research` MCP tools are available, call
`search_opportunities` for discovery and use `get_elastic_lead_profile` when
the profile is not already in context. Otherwise, fall back to the local
SQLite mirror through `scripts/search_bulk.py`.

Search individually for terms such as `Elasticsearch`, `Elastic Stack`,
`Kibana`, `OpenSearch`, `observability`, `log analytics`, `SIEM`, and `search
platform`, then use the relevant NAICS hints from `criteria/ELASTIC_LEAD_PROFILE.md` to
broaden discovery. Direct-script fallback:

```powershell
python .\scripts\search_bulk.py "<term>" --active-only --json
```

The local database is only a discovery source. `active=Yes` does not prove a
response deadline is still open; compare the deadline against today's exact
date. Verify promising notices against current official public information
before recommending them.

## Evidence Review

When an exact notice has a public SOW, PWS, requirements attachment, or
amendment, prefer MCP tools `ingest_public_document` and `search_documents`.
The `contracts-documents` skill and `scripts/document_store.py` are the
direct-command fallback.

Look specifically for:

- named Elastic, OpenSearch, logging, observability, SIEM, or search
  technology and the actual engineering deliverables;
- incumbent-platform migration or partner/reseller requirements;
- cloud, FedRAMP, security-control, clearance, and on-site constraints;
- contract vehicle, eligibility, submission deadline, and period of
  performance.

State `not found in indexed document` for missing evidence. A keyword or NAICS
match alone is never sufficient technical-fit evidence.

## Output Standard

Report the best supported technical matches, their official links, why each
fits Elastic engineering, public-document evidence obtained, and blockers.
Returning no strongly supported fit is correct when the available notices are
generic IT/cyber work or unrelated implementation.
