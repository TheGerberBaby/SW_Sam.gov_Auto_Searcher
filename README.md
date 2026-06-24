# SW SAM.gov Auto Searcher

Local tools for finding, filtering, and researching public SAM.gov small-team field-installation opportunities.

This project keeps a fast local mirror of SAM.gov opportunity data, stores public solicitation documents in a searchable evidence index, and exposes the workflow to AI clients through a Dockerized MCP server.

> **v2 update.** The toolkit now includes a deterministic lead-scoring engine, a watchlist + saved-search store, a daily digest report generator, and a zero-dependency local web dashboard. See [docs/V2_FEATURES.md](docs/V2_FEATURES.md). The portable v1 reference is git tag `v1.0`.
>
> **Stage 1 spine.** [`PROFILE.md`](PROFILE.md) is now the living business profile. Business workstreams live as markdown task files in [`tasks/`](tasks/) and are managed via `swcb tasks ...`. The scoring rubrics moved to [`criteria/`](criteria/). See [docs/STAGE1_SPINE.md](docs/STAGE1_SPINE.md) and [ROADMAP_REVIEW.md](ROADMAP_REVIEW.md).
>
> **Stages 2-5.** USAspending incumbent analysis, eCFR clause grounding, Goose recipes, IMAP email scaffold, a single-page operator dashboard (HTTP Basic auth, expandable system-tree panels), labeled-gold-set harness (macro-F1 + Cohen's kappa), and a DSPy GEPA scaffold for self-evolving criteria. See [docs/STAGES_2_5.md](docs/STAGES_2_5.md).

## System Schematic

<p align="center">
  <img src="docs/system-schematic.svg" alt="SW SAM.gov Auto Searcher system schematic" width="100%">
</p>

## What It Does

- Downloads the public SAM.gov daily opportunity extract into SQLite.
- Searches opportunities locally in milliseconds.
- Falls back to the live SAM.gov API when current same-day data matters.
- Indexes public solicitation attachments, SOWs, PWS files, and amendments in Elasticsearch.
- Gives Codex and Claude an MCP tool surface for structured opportunity search plus document evidence retrieval.
- Keeps lead research focused on security cameras, video monitoring, access control, structured cabling, low-voltage data cabling, and bounded fiber work.
- **v2:** scores every candidate against the operator's rubric, tracks pursuits in a watchlist, generates ranked daily digest reports, and ships a single-page local web dashboard (system-tree panels for leads, pursuits, and business setup).

## Repository Layout

| Path | Purpose |
| --- | --- |
| [`scripts/`](scripts/) | CLI tools, MCP server, dashboard, scoring, digest, document index, vendor sourcing, and API helpers. |
| [`scripts/adhoc/`](scripts/adhoc/) | Historical one-off filters kept out of the main workflow. |
| [`criteria/`](criteria/) | Technical-services and Elastic scoring profiles. |
| [`tasks/`](tasks/) | Git-tracked business roadmap spine. |
| [`docs/`](docs/) | Architecture, setup, operating guides, stage notes, and source research material. |
| [`data/`](data/) | Local runtime state only; databases, caches, digests, and exports are ignored by Git. |
| [`adapters/skills/`](adapters/skills/) | Codex skills for lead research and document evidence workflows. |

## Quick Start

Install dependencies:

```powershell
pip install -r requirements.txt
```

Create a local environment file:

```powershell
Copy-Item .env.example .env
```

Refresh the local SAM.gov mirror:

```powershell
python .\scripts\sync_bulk.py
```

Run a fast local search:

```powershell
python .\scripts\search_bulk.py "security camera" --active-only
python .\scripts\search_bulk.py "structured cabling" --naics 238210 --active-only --json
```

Use the live API fallback only when needed:

```powershell
python .\scripts\find_contracts.py "access control" --days 14
```

## Subcontractor Sourcing

After you decide to prime an opportunity, source local performers and generate
the cold-call script plus follow-up email ask-list:

```powershell
python .\scripts\swcb.py vendors --naics 561621 --place "Alexandria, VA"
python .\scripts\swcb.py vendors --naics 562111 --place "St. Croix Falls, WI" --due "19 Jun 2026"
python .\scripts\swcb.py vendors "tree removal" --place "Accokeek, MD" --json
python .\scripts\swcb.py vendors --naics 561790 --place "Dover AFB, DE" --script-only
```

Business discovery uses Google Places API (New). Add
`GOOGLE_PLACES_API_KEY` to `.env`; see
[`criteria/VENDOR_SOURCING_PROFILE.md`](criteria/VENDOR_SOURCING_PROFILE.md)
for the deterministic NAICS profiles and qualification rules.

The phone-friendly Workbench exposes the same flow under **Source Subs**.
Enter the NAICS profile, place of performance, and quote due date, then tap
**Generate subs + script**. Each request generates the cold-call script,
follow-up email draft, and qualification ask-list. When the Places key is
configured, the request also returns fresh local businesses with tap-to-call
phone numbers.

Opportunity cards also expose **Source subs + questions**. That action resolves
the selected notice from the local SAM mirror, writes an immediate preliminary
report under `reports/`, queues a durable Codex handoff under
`data/vendor-sourcing-jobs/`, and displays the cold-call narrative,
subcontractor follow-up email, contracting-officer clarification draft, and
future-chat unknowns checklist inline.

To find optional prime-with-subcontractor candidates first:

```powershell
python .\scripts\swcb.py subcontract-leads
```

This produces `reports/subcontract-opportunities.md` and `.csv`. It is a
discovery report, not a bid approval. See
[`criteria/SUBCONTRACTING_PRIME_PROFILE.md`](criteria/SUBCONTRACTING_PRIME_PROFILE.md)
for the hard gates and limitations-on-subcontracting guardrails.

## Document Evidence Index

Start Elasticsearch:

```powershell
docker compose up -d elasticsearch
python .\scripts\document_store.py init
python .\scripts\document_store.py status
```

Ingest a public solicitation attachment:

```powershell
python .\scripts\document_store.py ingest "https://public.example.gov/solicitation.pdf" `
  --notice-id "NOTICE-ID" `
  --solicitation-number "SOL-NUMBER" `
  --title "Solicitation attachment" `
  --public `
  --json
```

Convert a public attachment to Markdown without OCR before or after ingest:

```powershell
python .\scripts\document_store.py markdown "https://sam.gov/api/prod/opps/v3/opportunities/resources/files/RESOURCE-ID/download?&token=" `
  --output-dir "data\document-cache\solicitation-md" `
  --pdf-extractor pypdf `
  --json
```

Search indexed evidence:

```powershell
python .\scripts\document_store.py search "required platform and security controls" --notice-id "NOTICE-ID" --json
```

## MCP / AI Client Use

Build the MCP container:

```powershell
docker compose --profile mcp build mcp
```

The MCP server exposes:

| Tool | Purpose |
| --- | --- |
| `get_technical_services_profile` | Load the active fit and exclusion rules. |
| `get_elastic_lead_profile` | Load the narrower Elastic/search-only lane. |
| `search_opportunities` | Query the SQLite SAM mirror with deadline filtering. |
| `document_index_status` | Check Elasticsearch and index health. |
| `ingest_public_document` | Ingest a public HTTPS solicitation document. |
| `search_documents` | Retrieve source-backed document evidence. |
| `publish_research_scan` | Publish one final curated AI scan into the production Workbench. |
| `evaluate_opportunity` | Run and persist the independent Phase-1 expert panel. |
| `get_panel_verdict` | Fetch the latest stored panel verdict for a notice. |
| `list_vendor_sourcing_jobs` | List card-created subcontractor-sourcing jobs waiting for Codex. |
| `get_vendor_sourcing_job` | Load one queued job with its opportunity context and research handoff. |
| `complete_vendor_sourcing_job` | Save the sourced public-web/document report and close the queue item. |

See [docs/MCP_SETUP.md](docs/MCP_SETUP.md) for Codex, Claude Code, and Claude Desktop registration.

## Research Flow

1. Refresh `data/contracts.db` with `scripts/sync_bulk.py`.
2. Search each capability lane with `scripts/search_bulk.py` or the MCP `search_opportunities` tool.
3. Reject closed, unrelated, construction, commodity, and weak keyword-only matches.
4. Verify serious candidates against official public notice data.
5. Read SAM attachment metadata and download public SOW/PWS/RFQ files.
6. Convert public PDF/DOCX attachments to Markdown without OCR when inspection or debugging matters.
7. Ingest the public requirements document into Elasticsearch.
8. Search indexed evidence for scope, site visits, bonding, licensing, and bid blockers.
9. Recommend `assess now`, `monitor/partner`, or `reject`.
10. Publish the final curated `assess now` and `monitor/partner` results with
   `publish_research_scan` so the production Workbench updates automatically.
   Publish an empty result set when no supported fit is found.

## Tests

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

## GitHub Safety

The repository is set up to keep local and sensitive artifacts out of GitHub:

- `.env`
- `data/contracts.db`
- downloaded SAM.gov CSV extracts
- generated lead-export CSV/XLSX files, including local copies under `data/exports/`
- Python caches and local runtime files
- private or controlled solicitation attachments

Check before pushing:

```powershell
git status --short --ignored
git check-ignore -v .env data\contracts.db data\ContractOpportunitiesFullCSV.csv
```

## v2 Quick Start

```powershell
# Score the local mirror against the broad profile, last 30 days
python scripts/scoring.py --profile technical_services --min-score 3 --days 30

# Generate today's digest (markdown + HTML written to data/digests/)
python scripts/digest.py --days 3 --min-score 3

# Launch the local web dashboard
python scripts/dashboard.py

# Production dashboard: real pursuits and digest history
python scripts/dashboard.py --env prod

# Development dashboard: separate watchlist/digest state under data/dev/
python scripts/dashboard.py --env dev

# Unified CLI dispatcher
.\swcb.bat search "Elasticsearch"
.\swcb.bat score --profile elastic_only --min-score 4
.\swcb.bat digest
.\swcb.bat watch list
.\swcb.bat dashboard
```

Full v2 reference: [docs/V2_FEATURES.md](docs/V2_FEATURES.md).

## Small-Acquisition Resale Search

Use this optional lane when the operator explicitly wants straightforward
commercial-product RFQs that can be sourced from a supplier and drop-shipped or
freight-delivered to the government. It is intentionally separate from the
default field-installation scorer.

Saved searches live in the local `data/watchlist.db`, which is ignored by Git.
Recreate the resale preset on a fresh clone with:

```powershell
.\swcb.bat watch save-search small-acquisition-resale `
  --set-aside SBA `
  --notice-type "Combined Synopsis/Solicitation" `
  --days 30 `
  --profile technical_services `
  --min-score -10 `
  --description "Small acquisitions and straightforward reseller RFQs. Prioritize standard commercial products, supplier-supported fulfillment, drop-shipping or freight delivery, simple quote submission, and adequate sourcing runway. Reject hidden installation, onsite labor, engineered drawings, restricted documents, special licensing, and complex logistics unless explicitly flagged as partner-only."
```

The low machine-score threshold is deliberate: commodity RFQs are normally
demoted by the field-installation scorer. Replay the preset with the MCP
`run_saved_search` tool, then manually screen attachments for delivery terms,
freight, cash flow, reseller authorization, and nonmanufacturer-rule risk.

## Independent Evaluation Panel

After finder/triage and public-document ingest, run the stateless Phase-1
eligibility, fit/Pwin, and red-team panel:

```powershell
Copy-Item criteria\PANEL_OPERATOR_FACTS.example.json criteria\PANEL_OPERATOR_FACTS.json
python scripts/panel.py init --json
python scripts/panel.py run "SAM-NOTICE-ID" --json
python scripts/panel.py show "SAM-NOTICE-ID" --json
```

See [docs/PANEL.md](docs/PANEL.md) for the public-evidence boundary, stored
schema, verdict rules, and deferred Phase 2/3 work.

## Operator Dashboard

`scripts/dashboard.py` serves a single self-contained app — no build step, no
external dependencies (UI lives in `scripts/dashboard_html.py`, served over the
standard-library HTTP server). It is an **app shell**: a sidebar on desktop, a
bottom tab bar + "More" sheet on phones, and exactly one view on screen at a
time (deep-linkable, e.g. `/#agents`).

- **Home** is the landing view: pursuit/task/scan counts, quick actions
  (run a scan, find leads, ask, launch an agent), the latest scan, your next
  unblocked setup tasks, and a dismissable getting-started banner whose prompt
  interviews you and writes [`PROFILE.md`](PROFILE.md), scoring
  [`criteria/`](criteria/), and [`tasks/`](tasks/).
- **Scans** holds every scan (run from the page, or published by Claude/Codex)
  as a card with lead count, date, and a **0–5 star rating**. Open a scan to
  explore its leads inline and send the ones you like to **Pursuits**.

| View | What it does |
| --- | --- |
| Ask Assistant | Plain-English command palette over local data — "what should I work on next?", "show my pursuits", FAR/incumbent lookups. Deterministic, not an LLM. |
| Find Leads | Search the local SAM mirror by keyword, agency, place, set-aside. |
| Source Subs | Generate local performer leads and outreach scripts for a pursuit. |
| Pursuits | Working watchlist; move leads through stages and rate your own fit. |
| Business Setup | Stormwind operating tasks (formation, SAM, VetCert, eVA, first bid). |
| Prompt Library | Reusable research prompts and saved filter searches. |
| Profile & Rules | The profile and fit rules your AI should read; copy the onboarding or research prompt. |
| Agents | Browser handoff launcher: pick a prompt (or a queued sourcing job) and launch ChatGPT Codex or Claude in a tab — prompt copied, Claude prefilled. Sign in once in the browser; no API keys. |

The Ask panel routes keywords to local APIs — for real research, use Claude or
Codex directly. Prod and dev run on separate state and ports:

```powershell
python scripts/dashboard.py --env prod   # http://127.0.0.1:8765/  (data/watchlist.db)
python scripts/dashboard.py --env dev    # http://127.0.0.1:8766/  (data/dev/watchlist.db)
```

Scans are only as current as the local mirror — refresh it with
`python scripts/sync_bulk.py` so deadlines aren't stale.

### Use it like a phone app

The dashboard is an installable PWA. On a phone-width screen it switches to an
app layout: a fixed bottom tab bar (Home / Scans / Leads / Pursuits / More),
a slide-up sheet for the remaining views, and Pursuits rendered as cards
instead of a table.

1. Expose the dashboard on your LAN (password required for non-loopback binds):
   ```powershell
   python scripts/dashboard.py --host 0.0.0.0 --password <pick-one>
   ```
2. On your phone (same Wi-Fi), open `http://<your-pc-ip>:8765/` and sign in
   (user `stormwind`).
3. **Add to Home Screen** (Android Chrome: ⋮ → *Add to Home screen*; iPhone
   Safari: Share → *Add to Home Screen*). It launches full-screen with its own
   icon, like a native app.

## More Detail

- [PROFILE.md](PROFILE.md) is the living Stormwind Contracting business profile (start here).
- [docs/STAGE1_SPINE.md](docs/STAGE1_SPINE.md) explains the markdown-task spine and `swcb tasks` CLI.
- [ROADMAP_REVIEW.md](ROADMAP_REVIEW.md) is the agent policy for "what should I work on next?"
- [docs/STAGES_2_5.md](docs/STAGES_2_5.md) walks through USAspending, eCFR, Goose recipes, email scaffold, phone dashboard, harness, and DSPy GEPA.
- [docs/V2_FEATURES.md](docs/V2_FEATURES.md) covers the v2 scoring engine, watchlist, daily digest, dashboard, and CLI.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) has the internal architecture notes.
- [docs/SOP.md](docs/SOP.md) has daily operating recipes.
- [docs/DOCUMENT_INDEX.md](docs/DOCUMENT_INDEX.md) explains Elasticsearch document ingest and retrieval.
- [docs/MCP_SETUP.md](docs/MCP_SETUP.md) covers AI-client MCP registration.
