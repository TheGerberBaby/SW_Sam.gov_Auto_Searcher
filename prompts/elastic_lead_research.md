Use the `technical-contract-research` MCP server for an Elastic-focused scan.

Find current public SAM.gov opportunities that plausibly match my work as an
Elastic engineer: Elasticsearch, Elastic Stack, OpenSearch, Kibana, Logstash,
Elastic Agent/Fleet, observability, log analytics, SIEM implementation, or
search-platform engineering.

Rules:

- Start by calling
  `get_elastic_lead_profile`.
- Use `search_opportunities` for discovery, then validate promising leads with
  current official public information.
- Do not rely on `active=Yes`; reject notices whose actual response deadline
  has already passed as of the exact date used in the run.
- Do not return construction, facility repair, physical installation, hardware
  purchasing, license resale, or generic IT/cyber work without public-document
  evidence of an Elastic/search/logging/observability fit.
- Set-aside status does not prove I am eligible. Report it as a check, not a
  selling point.
- For a serious candidate, call `ingest_public_document` for one public SOW,
  PWS, requirements document, or amendment, then call `search_documents` to
  retrieve technical-fit and execution-blocker evidence.
- If there is no strong supported fit, say so plainly and show the nearest
  candidates that were rejected and why.

Output:

1. System/data validation and the exact current date used for deadline checks.
2. Up to five verified candidates, ranked by supported Elastic-engineering fit.
3. For the strongest candidate, indexed-document evidence for required
   technology, deliverables, cloud/security/clearance constraints,
   partner/reseller restrictions, on-site requirements, and deadline.
4. A practical recommendation: assess now, monitor, or reject.

Use only public official sources and do not contact agencies, register, submit,
or access gated documents.
