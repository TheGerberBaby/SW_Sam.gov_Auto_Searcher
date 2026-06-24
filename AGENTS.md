# Agent Instructions

> Before doing anything else, read `PROFILE.md` and skim `tasks/`. The
> business spine lives in those files; everything below is supporting
> detail.

## User Fit

the operator is building a small field-installation business. For contract-lead
work in this repository, the default capability profile is defined in
`criteria/TECHNICAL_SERVICES_PROFILE.md`. It prioritizes security-camera and
access-control installation, structured cabling, low-voltage data cabling, and
bounded fiber work that a two-to-three-person crew can execute.
`criteria/ELASTIC_LEAD_PROFILE.md` is a separate legacy specialist lane.

Do not default to large construction, high-voltage electrical, or unrelated
specialty-trade opportunities. The
construction material in `criteria/SAM_Lead_Selection_Logic.md` and any previously
indexed construction attachment are historical/test artifacts unless the operator
explicitly requests construction research.

## Roadmap Review

When asked "what should I work on next?", apply the policy in
`ROADMAP_REVIEW.md` against `tasks/`. Never spend two consecutive
cycles on a blocked workstream.

## Research Rules

- Start with `PROFILE.md`, `criteria/TECHNICAL_SERVICES_PROFILE.md`,
  `docs/DOCUMENT_INDEX.md`, and the relevant script documentation before
  conducting a lead search.
- Prefer the `technical_contract_research` MCP tools when available:
  `search_opportunities`, `document_index_status`, `ingest_public_document`,
  `search_documents`, and `publish_research_scan`.
- Use `data/contracts.db` as a discovery source and official public government
  information for current verification.
- Use `scripts/document_store.py` to ingest and retrieve evidence from public
  solicitation documents when evaluating technical fit or bid risk.
- Never infer that a platform, credential, clearance, eligibility status, or
  submission requirement exists without source evidence.
- An outcome of "no strongly supported technical-services fit found" is preferable to
  recommending unrelated work.
- After every user-requested contract-lead search, call `publish_research_scan`
  exactly once with the final curated `assess now` and `monitor/partner`
  results so the production Stormwind Workbench updates automatically. Publish
  an empty item list when no supported fit is found. Never publish intermediate
  keyword-search results or rejected false positives.
- When asked to process Workbench card-created subcontractor research, use
  `list_vendor_sourcing_jobs`, `get_vendor_sourcing_job`, and
  `complete_vendor_sourcing_job` when available. Treat the generated package as
  preliminary queue context and verify public sources before completing it.
