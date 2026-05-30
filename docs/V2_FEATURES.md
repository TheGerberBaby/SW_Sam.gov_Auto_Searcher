# SW Contracting Bots — v2 Feature Guide

v2 layers a deterministic **scoring engine**, a **watchlist + saved-search
store**, a **daily digest generator**, a **local web dashboard**, and a
**unified CLI** on top of the v1 SAM mirror + Elasticsearch document index.

Everything in v1 still works the same way. v2 modules are additive.

The git tag `v1.0` points at the last v1 commit. A local source-tree
snapshot can be kept outside this repository when needed.

---

## 1. Scoring engine — `scripts/scoring.py`

Translates the `criteria/TECHNICAL_SERVICES_PROFILE.md` and `criteria/ELASTIC_LEAD_PROFILE.md`
rubrics into a deterministic, explainable scorer. Each opportunity gets:

- a numeric **score**
- a **band** — `strong` / `promising` / `monitor` / `reject`
- a list of detected **lanes** — e.g. `elastic_search`, `ai_retrieval`,
  `observability_siem`, `data_platform`, `network_vtc`
- a list of **reasons** showing every signal that contributed to (or
  reduced) the score

### Profiles

- `technical_services` — the broad default profile. Tier-1 keyword = +4,
  tier-2 = +3, deliverable = +2.
- `elastic_only` — the narrow Elastic/search/observability profile.
  Tier-1 = +3, tier-2 = +2, deliverable = +1.

### How matches work

- Keyword matching is **word-boundary regex**, not raw substring. `llm`
  does not match `fulfillment`. `rag` does not match `fragmentation`.
- A `false_positive_guard` knocks out keyword hits when a known
  collision appears (e.g. `siem` + `siemens`, `rag` + `coveralls`).
- An opportunity with no tier-1 or tier-2 hit gets a `no_technical_evidence`
  penalty so commodity buys (BRACKET, VALVE, HOSE) do not surface in
  the "promising" band on set-aside + runway alone.
- Deliverable verbs (`design`, `integration`, `implementation`, ...)
  only earn points when a tier hit is also present.

### CLI

```powershell
# Top opportunities scored against the broad profile
python scripts/scoring.py --profile technical_services --min-score 3 --days 14

# Elastic-only lane with keyword pre-filter
python scripts/scoring.py --profile elastic_only --keyword "observability" --days 30

# JSON output for piping
python scripts/scoring.py --profile technical_services --json
```

### Python API

```python
from scoring import score_opportunity, bulk_score, available_profiles

result = score_opportunity(opportunity_dict, profile="technical_services")
print(result.score, result.band, result.lanes)
for reason in result.reasons:
    print(f"  {reason.points:+d}  {reason.kind}: {reason.detail}")
```

---

## 2. Watchlist + saved searches — `scripts/watchlist.py`

Stores pursuit state in `data/watchlist.db` so it survives every
SAM mirror refresh.

- **Watchlist** — track every notice the operator is actively pursuing
  through status transitions (`tracking` → `assessing` → `pursuing` →
  `submitted` → `won` / `lost` / `withdrawn` / `expired`).
- **Watchlist events** — append-only timeline of status changes and notes.
- **Saved searches** — named filter sets that can be replayed later.
- **Digest runs** — record of every digest that has been generated.

### CLI

```powershell
# Add an opportunity to the watchlist
python scripts/watchlist.py add NOTICE-ID --title "355 Wing VTC Upgrade" --status assessing

# List everything you're tracking
python scripts/watchlist.py list

# Update status
python scripts/watchlist.py status NOTICE-ID pursuing --note "PWS reviewed, drafting response"

# Add a freeform note
python scripts/watchlist.py note NOTICE-ID "Contracting officer responded — extension granted"

# Save a search filter set
python scripts/watchlist.py save-search elastic-weekly --keyword Elasticsearch --days 7 `
  --profile elastic_only --min-score 3 --description "Weekly Elastic scan"

# List saved searches
python scripts/watchlist.py list-searches
```

### Python API

```python
from watchlist import Store

store = Store()
entry = store.add_to_watchlist(opportunity_row, status="assessing", score=9, band="strong")
store.update_status(entry.notice_id, "pursuing", note="drafting response")
store.add_note(entry.notice_id, "Contracting officer reached out")
for entry in store.list_watchlist(status="pursuing"):
    print(entry.notice_id, entry.title, entry.response_deadline)
```

---

## 3. Daily digest — `scripts/digest.py`

Scans the local SAM mirror, scores every recent opportunity, and writes a
ranked markdown + HTML report to `data/digests/`. Each run is recorded
in the watchlist DB so a history is preserved.

```powershell
# Default: technical_services profile, last 3 days, min_score=3
python scripts/digest.py

# Tighter Elastic-only scan, last 7 days
python scripts/digest.py --profile elastic_only --days 7 --min-score 3

# Preview to stdout without writing files
python scripts/digest.py --no-write
```

Reports are grouped by capability lane and sorted by score. Each
candidate's score includes the full chain of `+points reason` and
`-points reason` so the rating is auditable.

---

## 4. Local web dashboard — `scripts/dashboard.py`

A zero-dependency local web app built on the standard-library HTTP
server. Run it and open `http://127.0.0.1:8765/`:

```powershell
python scripts/dashboard.py
# or, pick a non-default port:
python scripts/dashboard.py --port 9000 --no-browser
```

Tabs:

- **Search & Score** — filter the local mirror, see scored results with
  reasons + lane chips, save the current filters, push results onto the
  watchlist with one click.
- **Watchlist** — table of tracked opportunities, inline status
  dropdowns, add-note, remove.
- **Saved Searches** — list, replay (drops filters back into Search),
  delete.
- **Digest** — kick off a new digest run, view past runs.

The dashboard wraps the same modules used by the CLI and MCP server,
so anything you do here is reflected everywhere else.

---

## 5. Unified CLI — `scripts/swcb.py` (+ `swcb.bat`)

A single dispatcher:

```powershell
swcb sync                 # refresh local mirror (sync_bulk.py)
swcb search "Elastic"     # search local mirror
swcb live "OpenSearch"    # live SAM.gov API
swcb score --profile elastic_only --min-score 4
swcb digest --days 3
swcb watch list
swcb watch add NOTICE-ID --title "..."
swcb dashboard
swcb docs status          # Elasticsearch index status
```

Use `swcb <command> --help` for per-command flags. Each subcommand
forwards to its implementation module, which is still runnable
standalone too.

---

## 6. MCP server — new v2 tools

`scripts/mcp_server.py` now exposes these additional tools to Claude
Code, Claude Desktop, and Codex:

| Tool | Purpose |
| --- | --- |
| `list_scoring_profiles` | Available profile names + valid watchlist statuses. |
| `score_opportunities` | Search the local mirror and return scored, ranked candidates with reasons. |
| `score_one_opportunity` | Score a single notice already in the local mirror. |
| `generate_daily_digest` | Produce a fresh digest report; returns counts + file paths. |
| `add_to_watchlist` | Add a notice (auto-loads metadata from the mirror if `title` is omitted). |
| `list_watchlist` | List watchlist entries, optionally filtered by status. |
| `update_watchlist_status` | Move a watchlist entry to a new status. |
| `add_watchlist_note` | Append a dated note to a watchlist entry. |
| `save_search` | Persist a named search-filter set. |
| `list_saved_searches` | List all saved searches. |
| `run_saved_search` | Replay a saved search through the scoring engine. |

The existing v1 tools (`search_opportunities`, `ingest_public_document`,
`search_documents`, profile getters) are unchanged.

---

## 7. Tests

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

v2 adds:

- `tests/test_scoring.py` — 9 tests covering tier-1/tier-2 detection,
  profile differences, exclusion handling, false-positive guards,
  deadline parsing, lane assignment.
- `tests/test_watchlist.py` — 8 tests covering watchlist CRUD, status
  transitions, note appending, saved-search round-trips, digest-run
  recording.
- `tests/test_digest.py` — 3 tests covering markdown + HTML rendering
  and empty-state handling.

All 27 tests (v1 + v2) pass.

---

## Day-in-the-life

```powershell
# Morning: refresh the mirror and generate a digest
swcb sync
swcb digest --days 1 --min-score 3

# Browse, score, and push promising leads to the watchlist
swcb dashboard
# (open http://127.0.0.1:8765/ — search a lane, click "+ Watchlist" on hits)

# As you make progress, update status from the CLI or dashboard
swcb watch status NOTICE-ID assessing --note "PWS arrived, reviewing"
swcb watch status NOTICE-ID pursuing --note "drafting response"

# Or hand off to Claude through the MCP server, which now has the v2 tools
```
