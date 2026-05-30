# Agent Instructions

> Before doing anything else, read `PROFILE.md` and skim `tasks/`. The
> business spine lives in those files; everything below is supporting
> detail.

## User Fit

the operator is a technical-services engineer. For contract-lead work in this
repository, the default capability profile is defined in
`criteria/TECHNICAL_SERVICES_PROFILE.md`. It includes Elastic/OpenSearch, AI search and
RAG, observability/security analytics, AI/data services, and VTC/network
engineering. `criteria/ELASTIC_LEAD_PROFILE.md` is the narrower Elastic-only lane.

Do not default to construction or specialty-trade opportunities. The
construction material in `criteria/SAM_Lead_Selection_Logic.md` and any previously
indexed construction attachment are historical/test artifacts unless the operator
explicitly requests construction research.

## Roadmap Review

When asked "what should I work on next?", apply the policy in
`ROADMAP_REVIEW.md` against `tasks/`. Never spend two consecutive
cycles on a blocked workstream.

## Research Rules

- Start with `PROFILE.md`, `criteria/TECHNICAL_SERVICES_PROFILE.md`,
  `DOCUMENT_INDEX.md`, and the relevant script documentation before
  conducting a lead search.
- Prefer the `technical_contract_research` MCP tools when available:
  `search_opportunities`, `document_index_status`, `ingest_public_document`,
  and `search_documents`.
- Use `data/contracts.db` as a discovery source and official public government
  information for current verification.
- Use `scripts/document_store.py` to ingest and retrieve evidence from public
  solicitation documents when evaluating technical fit or bid risk.
- Never infer that a platform, credential, clearance, eligibility status, or
  submission requirement exists without source evidence.
- An outcome of "no strongly supported technical-services fit found" is preferable to
  recommending unrelated work.
