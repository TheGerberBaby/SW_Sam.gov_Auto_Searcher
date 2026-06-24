# Solicitation Document Index

This layer stores unstructured contract evidence in local Elasticsearch:
solicitation PDFs, statements of work, amendments, public attachments, and
research notes. It supplements the SQLite opportunity mirror; it does not
replace exact deadline, status, or eligibility filtering.

## Start Elasticsearch

Docker Desktop must be running. From this project directory:

```powershell
docker compose up -d elasticsearch
python scripts\document_store.py init
python scripts\document_store.py status
```

Elasticsearch is published only to `127.0.0.1:9200`. Security is disabled for
this local development service and it must not be exposed to another machine or
the public internet.

Kibana is optional:

```powershell
docker compose --profile dashboard up -d
```

It is available locally at `http://127.0.0.1:5601`.

## Ingest Documents

Index one downloaded solicitation file:

```powershell
python scripts\document_store.py ingest "C:\path\to\scope-of-work.pdf" `
  --notice-id "NOTICE-ID" `
  --solicitation-number "SOL-NUMBER" `
  --title "Elastic Platform Requirements" `
  --public `
  --json
```

Index a public HTTPS attachment URL directly:

```powershell
python scripts\document_store.py ingest "https://public.example.gov/file.pdf" `
  --notice-id "NOTICE-ID" `
  --title "Solicitation attachment" `
  --json
```

SAM.gov download endpoints that end in `/download` are supported: the indexer
uses the response filename and PDF signature when the server returns a generic
`application/octet-stream` content type.

PDF ingestion uses a Markdown-first extractor (`pymupdf4llm`) with OCR disabled.
This keeps public attachments searchable without routing normal text-layer PDFs
through OCR. Image-only scanned PDFs still need a separate OCR pass; the tool
will fail clearly when no extractable text is present.

If a PDF's embedded text layer is cleaner through the older plain extractor,
retry with `--pdf-extractor pypdf` or set `PDF_EXTRACTOR=pypdf` in `.env`.
Both extractor modes avoid OCR; `pymupdf4llm` usually preserves more headings
and tables, while `pypdf` can be better for exact text on some generated PDFs.

Convert one public attachment or local PDF to a durable Markdown artifact:

```powershell
python scripts\document_store.py markdown "https://public.example.gov/scope.pdf" `
  --output-dir "data\documents\markdown" `
  --json
```

Retry with the plain text-layer extractor when the Markdown output looks
garbled:

```powershell
python scripts\document_store.py markdown "https://public.example.gov/scope.pdf" `
  --output-dir "data\documents\markdown" `
  --pdf-extractor pypdf `
  --json
```

Convert a local folder of downloaded attachments:

```powershell
python scripts\document_store.py markdown "C:\path\to\attachments" `
  --output-dir "data\documents\markdown"
```

Folders are accepted and recursively index supported files: PDF, DOCX, TXT,
Markdown, HTML, and CSV. A re-ingest of identical content is idempotent. Use a
stable `--document-id` when a known document should be replaced by a corrected
or amended copy.

The indexer extracts text and stores overlapping chunks with source metadata.
For PDFs, the extracted text is Markdown-flavored so headings, lists, and many
tables survive better than plain `pypdf` extraction.

## Search Evidence

Keyword/full-text search works without an additional API key:

```powershell
python scripts\document_store.py search "bonding and insurance requirements" --json
python scripts\document_store.py search "base access" --notice-id "NOTICE-ID" --json
```

Search results return document identity, source, notice ID, and an excerpt for
an agent to cite when assessing bid risk.

## Optional Semantic Search

The index mapping supports vector embeddings. To enable semantic and hybrid
retrieval, add these values to `.env`:

```dotenv
EMBEDDING_PROVIDER=openai
OPENAI_API_KEY=your_key_here
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSIONS=1536
```

Documents ingested after this change receive embeddings:

```powershell
python scripts\document_store.py ingest "C:\path\to\scope-of-work.pdf" `
  --notice-id "NOTICE-ID" `
  --embedding-provider openai `
  --json

python scripts\document_store.py search "requirements that make this hard to bid" `
  --mode hybrid `
  --json
```

`hybrid` search uses local reciprocal-rank fusion over Elasticsearch text
results and vector results. Previously ingested text-only documents can still
be found lexically; re-ingest them after enabling embeddings to include them in
semantic results.

## MCP Server

The Dockerized `technical-contract-research` MCP server makes the SQLite
opportunity mirror and Elasticsearch evidence index available to Codex and
Claude Desktop through the same tool surface.

Build it once:

```powershell
docker compose --profile mcp build mcp
```

The clients launch it over stdio with:

```powershell
docker compose -f "<PROJECT_DIR>\compose.yaml" --profile mcp run --rm -T mcp
```

Available MCP tools:

| Tool | Purpose |
| --- | --- |
| `get_technical_services_profile` | Return the broad active fit and exclusion rules. |
| `get_elastic_lead_profile` | Return the focused Elastic-only lane when needed. |
| `search_opportunities` | Discover SQLite candidates, filtering past deadlines by default. |
| `document_index_status` | Confirm Elasticsearch/index health. |
| `ingest_public_document` | Ingest a public HTTPS solicitation attachment. |
| `search_documents` | Retrieve source-backed evidence from indexed documents. |
| `publish_research_scan` | Publish one final curated AI scan into the production Workbench. |
| `evaluate_opportunity` | Run and persist the independent Phase-1 expert panel. |
| `get_panel_verdict` | Fetch the latest stored panel verdict for a notice. |
| `list_vendor_sourcing_jobs` | List card-created subcontractor-sourcing jobs waiting for Codex. |
| `get_vendor_sourcing_job` | Load one queued job with its opportunity context and research handoff. |
| `complete_vendor_sourcing_job` | Save the sourced public-web/document report and close the queue item. |

The server also publishes the `technical-contracts://profiles/service-fit`
resource and a `find_technical_services_leads` prompt. SQLite results remain discovery
data; agents must verify serious candidates with current official sources.
Deadline filtering uses `USER_TIMEZONE`, defaulting to
`America/New_York`, rather than the container's UTC clock.
After a user-requested contract-lead search, agents publish one curated scan so
the Workbench updates automatically. Intermediate discovery calls remain
transient.

## Client Registration

This machine is configured for both clients to launch the same local Docker
MCP process over stdio.

Codex uses `<CODEX_HOME>\config.toml`:

```toml
[mcp_servers.technical_contract_research]
command = 'C:\Program Files\Docker\Docker\resources\bin\docker.exe'
args = ["compose", "-f", "<PROJECT_DIR>\\compose.yaml", "--profile", "mcp", "run", "--rm", "-T", "mcp"]
startup_timeout_sec = 120
```

Claude Desktop uses
`%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "technical-contract-research": {
      "command": "C:\\Program Files\\Docker\\Docker\\resources\\bin\\docker.exe",
      "args": [
        "compose",
        "-f",
        "<PROJECT_DIR>\\compose.yaml",
        "--profile",
        "mcp",
        "run",
        "--rm",
        "-T",
        "mcp"
      ]
    }
  }
}
```

Restart Codex or Claude Desktop after changing client configuration. Local MCP
servers configured this way apply to Claude Desktop; Claude web/Cowork remote
connectors require a separately hosted HTTP MCP server.
