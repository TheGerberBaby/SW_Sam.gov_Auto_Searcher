# Technical Opportunity Research Architecture

## System Schematic

```mermaid
flowchart LR
    U["the operator<br/>technical-services pursuit"] --> C["Codex Desktop<br/>skills + MCP client"]
    U --> D["Claude Desktop<br/>MCP client"]

    C -->|stdio: docker compose run mcp| M["technical-contract-research MCP<br/>Docker one-shot server"]
    D -->|stdio: docker compose run mcp| M

    M --> P["criteria/TECHNICAL_SERVICES_PROFILE.md<br/>broad fit rules + scoring"]
    M --> Q["Prompt library<br/>technical_services_lead_research.md"]

    M --> O["search_opportunities"]
    O --> S[("SQLite<br/>data/contracts.db")]
    B["SAM.gov daily public extract"] --> R["scripts/sync_bulk.py"]
    R --> S

    M --> I["ingest_public_document"]
    M --> A["SAM attachment metadata<br/>opps/v3 resources"]
    A --> G["Official public attachments<br/>PDF / DOCX / XLSX / HTML"]
    G --> I
    G --> MD["document_store.py markdown<br/>non-OCR PDF/DOCX to .md"]
    I --> X["document_store.py ingest<br/>download · normalize · chunk"]
    MD --> CACHED[("local markdown cache<br/>data/document-cache/")]
    X --> E[("Elasticsearch<br/>stormwind_documents_v1")]

    M --> F["search_documents"]
    M --> H["document_index_status"]
    M --> W["publish_research_scan"]
    F --> E
    H --> E
    W --> WB[("Workbench / watchlist<br/>research scans")]
    K["Kibana optional dashboard"] --> E
```

## Research Flow

```mermaid
flowchart TD
    A["Ask for opportunities"] --> B["Load profile + explicit lane override<br/>technical services / construction exception"]
    B --> C["Search local SAM mirror<br/>keywords, NAICS, set-aside, open deadline"]
    C --> D{"Deadline still open?"}
    D -->|No| X["Reject as expired"]
    D -->|Yes| E{"Plausible scope and crew size?"}
    E -->|No| Y["Reject oversized, unrelated, sole-source, or passed site-visit"]
    E -->|Yes| F["Verify current official notice<br/>SAM.gov page/API"]
    F --> G["Read attachment metadata<br/>opps/v3 resources"]
    G --> H{"Public attachment available?"}
    H -->|No| I["Use notice text only<br/>flag document gap"]
    H -->|Yes| J["Download SOW/PWS/RFQ<br/>public resource file URL"]
    J --> K["Convert to Markdown without OCR<br/>document_store.py markdown"]
    K --> L["Ingest into Elasticsearch<br/>document_store.py ingest"]
    L --> M["Search indexed evidence<br/>scope, deadlines, bonding, site visit, licenses"]
    I --> N{"Evidence supports pursuit?"}
    M --> N
    N -->|No| O["Reject or monitor with reason"]
    N -->|Yes| P["Assess now / partner / monitor"]
    O --> Q["publish_research_scan once"]
    P --> Q
    Q --> R["Workbench card updates"]
```

## Runtime Responsibilities

| Component | Responsibility |
| --- | --- |
| Codex skill | Guides the research workflow and output quality. |
| Claude Desktop | Uses the same MCP tools without requiring Codex skills. |
| Docker MCP server | Presents controlled research tools to either AI client. |
| SQLite mirror | Fast discovery from SAM.gov bulk opportunity records. |
| SAM attachment API | Lists public solicitation attachment metadata and resource IDs for download. |
| Markdown cache | Optional durable `.md` copy of public SOW/PWS/RFQ files for inspection and debugging. |
| Elasticsearch | Searchable evidence store for chunked public solicitation documents. |
| Profile/prompt files | Define the operator's technical capability lanes and research rules. |
| **Scoring engine** (v2) | Deterministic, explainable lead scoring against the profile rubric. |
| **Watchlist store** (v2) | Per-opportunity pursuit state, status history, saved searches, digest run log. |
| **Digest generator** (v2) | Daily ranked markdown + HTML report by capability lane. |
| **Local dashboard** (v2) | Zero-dependency web UI for search, score, watchlist, saved searches, digest. |
| **Unified CLI** (v2) | `swcb <command>` dispatcher in front of every script. |

## v2 Module Flow

```mermaid
flowchart LR
    DB[("SQLite<br/>data/contracts.db")] --> SCORE["scoring.py<br/>tier-1/2 keywords + structural rules"]
    SCORE --> DIGEST["digest.py<br/>ranked markdown + HTML report"]
    SCORE --> DASH["dashboard.py<br/>local web UI (http.server)"]
    SCORE --> MCP2["mcp_server.py v2 tools<br/>score_opportunities, generate_daily_digest, ..."]
    DASH <--> WL[("watchlist.db<br/>watchlist + saved searches + digest runs")]
    DIGEST --> WL
    MCP2 <--> WL
    CLI["swcb.py / swcb.bat<br/>unified dispatcher"] --> SCORE
    CLI --> DIGEST
    CLI --> DASH
    CLI --> WL
```

## Boundary Rules

- SQLite finds candidates; it is not proof that a notice remains open or fits.
- Official public notice data verifies status and deadlines.
- Deadline filtering uses the operator's configured timezone, not container UTC.
- Public scope documents establish technical fit and blockers.
- Elasticsearch preserves retrievable evidence; it does not create missing facts.
- A set-aside is worth surfacing, but eligibility must be confirmed separately.
