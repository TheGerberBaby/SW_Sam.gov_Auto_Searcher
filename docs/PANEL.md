# Independent Evaluation Panel

The Phase-1 panel adds independent expert judgment after finder/triage. It does
not change lead discovery or deterministic scoring. Every judge receives a new
API request containing only SQLite opportunity facts, structured operator facts,
and retrieved evidence that has been explicitly marked public.

## Setup

Install dependencies and add the API key to `.env`:

```dotenv
ANTHROPIC_API_KEY=your_key_here
```

Create a local operator-facts file and review every value before running the
panel. The local file is intentionally ignored by Git:

```powershell
Copy-Item criteria\PANEL_OPERATOR_FACTS.example.json criteria\PANEL_OPERATOR_FACTS.json
```

Create the additive tables:

```powershell
python scripts\panel.py init --json
```

Panel evidence must be public. MCP ingestion marks public HTTPS documents
automatically. For local files, assert that classification explicitly:

```powershell
python scripts\document_store.py ingest "C:\path\to\public-sow.pdf" `
  --notice-id "SAM-NOTICE-ID" `
  --public `
  --json
```

## Run And Inspect

```powershell
python scripts\panel.py run "SAM-NOTICE-ID" --json
python scripts\panel.py show "SAM-NOTICE-ID" --json
.\swcb.bat panel show "SAM-NOTICE-ID"
```

`run` also accepts a solicitation number as a convenience fallback when it
resolves in the local mirror. Use `NGA-2026-02` to resolve the current NGA
Industry Day row without copying its SAM bulk notice hash.

The Phase-1 call fans out three stateless experts concurrently:

| Expert | Purpose |
| --- | --- |
| `eligibility` | Owns hard vetoes and prime-versus-teamable distinction. |
| `fit_pwin` | Evaluates lane fit, delivery realism, past performance, and Pwin. |
| `redteam` | Argues no-bid and identifies the most likely fatal blocker. |

The aggregator is deterministic. An eligibility `ineligible` veto forces
`reject`; `prime_blocked_teamable` forces `monitor_partner`. Otherwise, the
most conservative grounded expert verdict with confidence at least `0.5`
wins. Narrative claims without evidence references are capped below that
threshold and recorded as grounding warnings.

## Stored Data

`data/contracts.db` receives additive `panel_runs` and `panel_verdicts` tables.
Each run stores the final verdict, consensus score, dissent, model, prompt
version, and token count. Each expert row stores scores, blockers, evidence
references, confidence, and raw JSON. Daily SAM mirror sync preserves these
tables while refreshing `opportunities`.

## Deferred Work

Phase 2 adds metadata-only cost gating, the pricing expert, and complete token
cost reporting. Phase 3 adds proposal skeleton and DOCX generation for
`assess` survivors only.
