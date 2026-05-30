# Stages 2 – 5

Layered on top of the [Stage 1 spine](STAGE1_SPINE.md) and the
[v2 toolset](V2_FEATURES.md). Each stage is independent — you can
adopt any subset.

| Stage | Layer in the report | What it gives you |
| --- | --- | --- |
| 2.1 USAspending | Layer 3 — Tools | Keyless incumbent and award-history lookups |
| 2.2 eCFR | Layer 3 — Tools | FAR / CFR / SBA size-standard clause grounding |
| 2.3 Goose recipes | Layer 1 — Orchestrator | Cron-scheduled unattended runs |
| 2.4 IMAP email scaffold | Layer 3 — Tools | SAM-alert mail → watchlist pipeline (read-only) |
| 3 Phone-accessible dashboard | Layer 4 — UI | Mobile-responsive UI + LAN binding + HTTP Basic + Ask command palette |
| 4 Labeled-gold-set harness | Layer 5 — Harness | Macro-F1 / Cohen's κ comparison of scoring profiles against your labels |
| 5 DSPy GEPA scaffold | Layer 5 — Harness | Self-evolving criteria (requires DSPy + LLM key) |

---

## 2.1 USAspending — incumbent + award-history analysis

Keyless API at <https://api.usaspending.gov>. Cached for 24 hours
at `data/usaspending_cache.json`.

```powershell
# Top recent procurement recipients matching a NAICS / agency / keyword
swcb incumbents incumbents --naics 541512 --limit 10
swcb incumbents incumbents --naics 541512 --agency "Department of the Air Force"

# Specific recipient's award history (incumbent intel)
swcb incumbents award-history --recipient "BOOZ ALLEN HAMILTON" --naics 541512 --limit 20

# Top recipients by NAICS over the window
swcb incumbents top-recipients --naics 541512 --years-back 3 --limit 10
```

MCP tools added: `find_incumbents`, `award_history`,
`top_recipients_by_naics`.

Caveat the report flags (and the tool always returns alongside
results): GAO has documented completeness gaps; treat results as
directional.

---

## 2.2 eCFR — FAR / CFR clause grounding

Keyless REST API at <https://www.ecfr.gov/api>. Cached for 7 days at
`data/ecfr_cache.json` — regulation text doesn't change daily.

```powershell
# List CFR titles
swcb ecfr titles

# Pull a specific section
swcb ecfr section --title 48 --section 52.212-2          # FAR evaluation clause
swcb ecfr section --title 13 --section 121.201           # SBA size standards
swcb ecfr section --title 13 --section 128               # SDVOSB program rule

# Full-text search across a title
swcb ecfr search "service-disabled veteran" --title 13 --limit 5
```

MCP tools added: `get_cfr_section`, `search_ecfr`.

FAR is Title 48; SBA size standards are Title 13 Part 121.

---

## 2.3 Goose — scheduled / unattended orchestration

Install [Goose](https://github.com/aaif-goose/goose) separately
(it's a Rust binary, not bundled here). See [`goose/README.md`](../goose/README.md)
for the install + extension-config flow.

Drop the block from [`goose/config.example.yaml`](../goose/config.example.yaml)
into your Goose config to register the FastMCP server in this repo
as a Goose extension. Then schedule any of the recipes:

```powershell
goose schedule add --schedule-id sam-hunt-daily --cron "0 6 * * *" `
  --recipe-source ./goose/recipes/sam-hunt.yaml

goose schedule add --schedule-id roadmap-weekly --cron "0 7 * * MON" `
  --recipe-source ./goose/recipes/roadmap-review.yaml
```

Recipes shipped:

| Recipe | What it does | Auto-mutates external state? |
| --- | --- | --- |
| [`sam-hunt.yaml`](../goose/recipes/sam-hunt.yaml) | Score recent notices, write digest, surface top hits | Adds high-score notices to the watchlist (`status=tracking`). |
| [`roadmap-review.yaml`](../goose/recipes/roadmap-review.yaml) | Summarize unblocked / unknown / blocked tasks | No — never mutates `tasks/*.md`. |
| [`incumbent-research.yaml`](../goose/recipes/incumbent-research.yaml) | USAspending pull for a notice or NAICS | No. |
| [`email-ingest.yaml`](../goose/recipes/email-ingest.yaml) | Process SAM alert emails into watchlist (scaffold — needs IMAP MCP) | Marks messages read. Never sends. |

All recipes are deliberately conservative: nothing auto-submits, auto-emails,
or auto-mutates `tasks/`. Tighten or relax in your fork.

---

## 2.4 IMAP email scaffold

A configuration scaffold for the [`ai-zerolab/mcp-email-server`](https://github.com/ai-zerolab/mcp-email-server)
recommended by the report. See [`email/README.md`](../email/README.md)
for the full app-password + read-only setup, then uncomment the
`imap-mail` extension block in [`goose/config.example.yaml`](../goose/config.example.yaml)
and enable the `email-ingest.yaml` schedule.

The boundary: agents may **read** SAM alert mail and mark messages
read. They may **not** send, reply, forward, draft, label, move, or
delete.

---

## 3 — Phone-accessible dashboard

Same dashboard from v2, now mobile-responsive and LAN-safe.

```powershell
# Loopback only (default — no password needed)
swcb dashboard

# LAN-accessible, password from env var (recommended)
$env:SWCB_DASHBOARD_PASSWORD = "<long-random>"
swcb dashboard --host 0.0.0.0

# Or pass --password explicitly (avoid shell history if you do this)
swcb dashboard --host 0.0.0.0 --password "<long-random>"
```

Then open the printed `http://<your-LAN-ip>:8765/` URL on your phone.
HTTP Basic prompt: username `stormwind`, password whatever you set.

The dashboard refuses to bind to a non-loopback host without a
password, on purpose.

New tabs:

- **Ask** — command palette that routes natural-language commands.
  Pattern-matched (no LLM needed, works offline, no API costs):
  - `next` / `unblocked` — next-actionable tasks
  - `tasks [status]` — list tasks (optionally filter)
  - `watchlist` — current opportunity watchlist
  - `digest` — run today's scored digest
  - `elastic` / `vtc` / `kibana` — score search for that lane
  - `incumbents 541512` — USAspending top recipients
  - `far 52.212-2` — fetch a FAR section
  - `cfr 13 121.201` — fetch SBA size standards
  - `help` — list commands
- **Tasks** — surface unblocked workstreams, change status inline.

---

## 4 — Labeled-gold-set harness

Stage 4 from the report, **without** the promptfoo install. We
already have a fast deterministic Python scorer — what matters is
measuring whether it agrees with your judgment, before we layer LLM
evaluation on top.

The pattern (from Karpathy autoresearch):

- Locked **scorer**: [`scripts/harness.py`](../scripts/harness.py)
- Locked **labels**: `harness/gold/*.csv`
- The **program** (the editable knob): [`criteria/*.md`](../criteria/) +
  the keyword tables in [`scripts/scoring.py`](../scripts/scoring.py)
- One comparable **metric**: macro-F1 + Cohen's κ

### Gold-set format

`harness/gold/<name>.csv`:

```csv
notice_id,label,note
c773efdb6f5c489fad2f734f67d07a6c,fit,355 Wing VTC Upgrade — real services opportunity
6560465a32b44ebbab5d1ed7279c8361,reject,HOSE HYD commodity buy
```

Labels: `fit` / `monitor` / `reject`. Use real past go/no-go calls.

### CLI

```powershell
swcb harness status                                    # all gold sets
swcb harness status --gold demo                        # one set's class counts
swcb harness label NOTICE-ID fit --gold default --note "real Elastic services"
swcb harness run --profile technical_services --gold default
swcb harness compare --profiles technical_services,elastic_only --gold default
```

The compare output shows accuracy, macro-F1, Cohen's κ, per-class
precision/recall, a confusion matrix, and a final ranking. Threshold
the report calls out: if **macro-F1 < ~0.6 on your held-out labels,
the criteria files (not the tooling) need work**. Iterate the
markdown before automating.

A 6-row `harness/gold/demo.csv` ships with the repo to demonstrate
the output — it isn't a real evaluation set.

### Path to promptfoo

If you later want LLM-judged rubrics side-by-side with the Python
scorer (the report's Stage 4 v1), promptfoo can load this same CSV
via `tests.csv` + `__expected` — no migration needed.

---

## 5 — DSPy GEPA self-evolution scaffold

[`harness/dspy_gepa_scaffold.py`](../harness/dspy_gepa_scaffold.py).

GEPA (Genetic-Pareto reflective prompt evolution) takes your labeled
gold set, asks an LLM to classify each opportunity, and evolves the
criteria text on a Pareto frontier of agreement-with-you scores. The
key trick: the metric returns `(score, natural_language_feedback)`,
so the LLM doing the evolution sees *why* it was wrong, not just
that it was.

Not runnable as-is — it needs:

1. `pip install dspy-ai`
2. An LLM API key (`OPENAI_API_KEY`, etc.)
3. At least ~150 labeled examples in `harness/gold/<name>.csv` —
   fewer than that and GEPA will overfit your sample.

Then:

```powershell
pip install dspy-ai
$env:OPENAI_API_KEY = "..."
python harness/dspy_gepa_scaffold.py --gold default --model openai/gpt-4o-mini
```

The output is an evolved set of criteria-text instructions. Review
before promoting them into `criteria/*.md` as the next baseline.

---

## Tests

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

This batch adds 18 unit tests (USAspending: 4, eCFR: 5, harness: 9).
56/56 total tests pass.

## Caveats from the report worth re-reading

- USAspending has GAO-documented completeness gaps → directional only.
- SAM Opportunities API is **10 req/day** for non-federal users
  (1,000/day if tied to a registered entity). Local mirror is essential.
- LLM-as-judge has documented verbosity + position bias (Zheng et al.
  2023). Spot-check anything LLM-graded.
- Cohen's κ can mislead under heavy class imbalance — always read it
  alongside macro-F1 + per-class P/R.
- Ecosystem churn is real. Goose / promptfoo / DSPy all moving fast;
  pin versions in any production pipeline.
