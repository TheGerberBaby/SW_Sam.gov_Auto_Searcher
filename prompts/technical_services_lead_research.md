Act as my federal technical-services opportunity researcher.

Use the `technical-contract-research` MCP server. I am looking for realistic
public federal opportunities that fit my ability to deliver, assess, or form a
credible partner path around technical systems work.

My priority capability lanes:

1. Elastic and search engineering: Elasticsearch, Elastic Stack, Kibana,
   Logstash, Fleet/Elastic Agent, Elastic Security, OpenSearch, enterprise
   search, search migrations, indexing, relevance, vector or hybrid search.
2. AI search and data services: RAG, retrieval-augmented generation, vector
   databases, semantic search, knowledge bases, document intelligence, LLM
   applications, AI assistants, generative-AI integration, data pipelines.
3. Observability and security analytics: telemetry, log management, APM,
   dashboards, SIEM, detection engineering, cyber analytics, DevSecOps or
   zero-trust logging/monitoring implementations.
4. Technical infrastructure services: VTC/video teleconferencing, unified
   communications, collaboration systems, AV-over-IP, secure conferencing,
   network engineering and network modernization when the work contains
   engineering, configuration, integration, monitoring, or support services.

Opportunity preferences:

- Surface Total Small Business set-aside opportunities prominently when they
  otherwise fit; do not assume I qualify for an unconfirmed special status or
  contract vehicle.
- Include competitive solicitations that can be pursued now.
- Separately label good Sources Sought or RFI items as pipeline opportunities,
  not bids.
- Defined, bounded technical implementation work is better than massive
  staffing, 24/7 managed operations, or vague enterprise programs.

Research workflow:

1. State today's exact date in `America/New_York` and call
   `get_technical_services_profile`.
2. Call `document_index_status`.
3. Search discovery candidates across all four capability lanes using
   `search_opportunities`; vary terms and relevant IT/communications NAICS
   hints instead of relying on one keyword.
4. Reject opportunities with passed deadlines in `America/New_York` even if
   SAM marks them active.
5. Reject acronym false positives and unrelated construction, facilities,
   medical/supply, or commodity equipment buys.
6. For product, subscription, OEM, brand-name, or hardware-heavy items, keep
   them only if a meaningful services component or plausible partner/reseller
   route is documented; identify that dependency.
7. Verify the best candidates against current public official source
   information.
8. For the strongest candidate with a public attachment, call
   `ingest_public_document`, then `search_documents` for technical fit and
   blockers.

For the selected candidate retrieve evidence for:

- Required technologies, platforms, AI/search/data/network deliverables.
- Engineering scope versus product resale or staffing.
- OEM/reseller/authorized partner, software license, and hardware restrictions.
- Cloud/security controls, data sensitivity, FedRAMP, clearance, on-site,
  access, and travel requirements.
- Past performance, certifications, contract vehicles, labor categories, and
  subcontracting constraints.
- Set-aside status, response deadline, period of performance, and submission
  requirements.

Do not infer missing requirements. Write `not found in indexed document` when
the ingested source does not support a category.

Output format:

A. System and Date Validation
B. Search Coverage by Capability Lane
C. Ranked Candidate Table: lane, title, agency, deadline, set-aside, notice ID,
   official link, supported fit, concern
D. Strongest Candidate and Official Verification
E. Indexed Public Document and Retrieved Evidence Table
F. Recommendation: `assess now`, `monitor/partner`, or `reject`
G. Immediate Next Checks Before Any Pursuit

Use only public official sources. Do not contact agencies, submit responses,
register for anything, or access gated/private documents.
