# Technical Opportunity Research Architecture

## System Schematic

```mermaid
flowchart LR
    U["the operator<br/>technical-services pursuit"] --> C["Codex Desktop<br/>skills + MCP client"]
    U --> D["Claude Desktop<br/>MCP client"]

    C -->|stdio: docker compose run mcp| M["technical-contract-research MCP<br/>Docker one-shot server"]
    D -->|stdio: docker compose run mcp| M

    M --> P["TECHNICAL_SERVICES_PROFILE.md<br/>broad fit rules + scoring"]
    M --> Q["Prompt library<br/>technical_services_lead_research.md"]

    M --> O["search_opportunities"]
    O --> S[("SQLite<br/>data/contracts.db")]
    B["SAM.gov daily public extract"] --> R["scripts/sync_bulk.py"]
    R --> S

    M --> I["ingest_public_document"]
    G["Official public government<br/>SOW / PWS / requirements PDF"] --> I
    I --> X["text extraction + chunking<br/>scripts/document_store.py"]
    X --> E[("Elasticsearch<br/>stormwind_documents_v1")]

    M --> F["search_documents"]
    M --> H["document_index_status"]
    F --> E
    H --> E
    K["Kibana optional dashboard"] --> E
```

## Research Flow

```mermaid
flowchart TD
    A["Ask for opportunities"] --> B["Load technical-services profile"]
    B --> C["Search local SAM mirror<br/>terms + NAICS discovery hints"]
    C --> D{"Deadline still open?"}
    D -->|No| X["Reject as expired"]
    D -->|Yes| E{"Plausible service fit?"}
    E -->|No| Y["Reject unrelated / resale-only / overbroad"]
    E -->|Yes| F["Verify current official notice"]
    F --> G["Download one public SOW/PWS/requirements document"]
    G --> H["Ingest document into Elasticsearch"]
    H --> I["Retrieve requirements and blockers"]
    I --> J{"Evidence supports capability fit?"}
    J -->|No| Z["Monitor or reject with reason"]
    J -->|Yes| K["Recommend assessment<br/>with eligibility and bid checks"]
```

## Runtime Responsibilities

| Component | Responsibility |
| --- | --- |
| Codex skill | Guides the research workflow and output quality. |
| Claude Desktop | Uses the same MCP tools without requiring Codex skills. |
| Docker MCP server | Presents controlled research tools to either AI client. |
| SQLite mirror | Fast discovery from SAM.gov bulk opportunity records. |
| Elasticsearch | Searchable evidence store for public solicitation documents. |
| Profile/prompt files | Define the operator's technical capability lanes and research rules. |

## Boundary Rules

- SQLite finds candidates; it is not proof that a notice remains open or fits.
- Official public notice data verifies status and deadlines.
- Deadline filtering uses the operator's configured timezone, not container UTC.
- Public scope documents establish technical fit and blockers.
- Elasticsearch preserves retrievable evidence; it does not create missing facts.
- A set-aside is worth surfacing, but eligibility must be confirmed separately.
