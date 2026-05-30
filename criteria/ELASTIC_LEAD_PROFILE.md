# Elastic Engineering Lead Profile - Specialized Lane

## Use This Lane

Use this profile for focused Elastic/search/observability research. The active
broad default for the operator is `TECHNICAL_SERVICES_PROFILE.md`, which also covers
AI/RAG/data services and VTC/network engineering opportunities.

Do not default to construction, HVAC, roofing, doors, electrical contracting,
plumbing, facility repair, or other physical trades. The construction searches
already in this project are historical validation examples only unless the operator
explicitly asks for that market.

## Work worth finding

Strong fits include public solicitations, RFIs, and sources-sought notices for:

- Elasticsearch, Elastic Stack, Kibana, Logstash, Elastic Agent, Fleet, or
  OpenSearch engineering.
- Search platform implementation, migration, tuning, relevance, indexing, or
  dashboard development.
- Observability, application performance monitoring, log ingestion, telemetry
  pipelines, or operational dashboards where the implementation scope fits an
  Elastic engineer.
- SIEM, security analytics, detection dashboards, or log-management work when
  public documents establish a search/telemetry implementation component.
- Short assessments, pilots, integrations, migrations, training, or
  configuration work with a bounded deliverable.

## Discovery hints

Use keywords first, because an NAICS code alone does not prove technical fit:

`Elasticsearch`, `"Elastic Stack"`, `Kibana`, `Logstash`, `"Elastic Agent"`,
`Fleet`, `OpenSearch`, `observability`, `"log analytics"`, `"log management"`,
`SIEM`, `"security analytics"`, `"search platform"`, and `DevSecOps`.

Useful NAICS discovery filters include:

| NAICS | Use as a discovery hint for |
| --- | --- |
| `541512` | Computer systems design services |
| `541519` | Other computer related services |
| `541511` | Custom computer programming services |
| `518210` | Computing infrastructure, data processing, and hosting services |

Treat these only as candidate-generating filters. Validate the actual
statement of work or requirements attachment before calling an opportunity a
fit.

## Hard exclusions by default

- Construction, facilities, physical installation, repair, or maintenance.
- Audio/visual installation and commodity hardware purchasing.
- Pure product resale, subscriptions, or license renewals unless the operator states
  that he has the required reseller or partner authority.
- Generic IT staffing, enterprise transformation, managed security operations,
  or broad cybersecurity programs with no documented Elastic/search/logging fit.
- Clearance-heavy or on-site operations work unless the operator explicitly confirms
  the required capability.
- Award notices, notices of intent, sole-source actions, expired deadlines, or
  other non-compete notices when the task is to find biddable work.

## Ranking evidence

Rank a lead only after reading current public notice information and, where
available, a public scope, performance work statement, requirements document,
or attachment.

| Score | Evidence |
| --- | --- |
| `+3` | Public title or document explicitly names Elasticsearch, Elastic, Kibana, Logstash, Elastic Agent/Fleet, or OpenSearch. |
| `+2` | Public document requires search, log ingestion, observability, dashboards, SIEM analytics, cluster work, or migration matching Elastic skills. |
| `+1` | Defined engineering deliverable: implementation, configuration, integration, tuning, assessment, training, or pilot. |
| `+1` | Scope is bounded and realistically assessable by an individual or small technical business. |
| `-2` | Generic IT/cyber language only, with no supported Elastic/search/telemetry implementation fit. |

Set-aside status, deadline, registration, contract vehicle, clearance,
insurance, and place-of-performance constraints are eligibility and execution
checks. Do not claim the operator is eligible solely because a notice is set aside.

## Research workflow

1. Search the local SAM.gov mirror broadly with the terms and NAICS hints above.
2. Remove hard exclusions and generic false positives. Do not treat
   `active=Yes` as an open bid: compare each response deadline to today's
   exact date because active SAM records can already be past due.
3. Verify each surviving notice against current official public information.
4. For promising leads, ingest a public SOW, PWS, requirements file, or
   amendment into Elasticsearch using `scripts/document_store.py`.
5. Retrieve evidence for the required platform, deliverables, certifications,
   clearance, on-site work, partner/reseller requirements, period of
   performance, security controls, and submission deadline.
6. Mark every unsupported requirement as `not found in indexed document`.
7. Recommend work only when retrieved evidence shows technical fit and the
   practical blockers are understood.
