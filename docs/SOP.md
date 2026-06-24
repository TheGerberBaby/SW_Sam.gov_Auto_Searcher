# SOP - SAM Opportunity Research Bots

**Purpose:** how to search US federal contract opportunities from SAM.gov using the local tools in this folder.

**Owner:** Project operator

**Last updated:** 2026-05-31

---

## 1. What this is

**Active lead profile:** the operator pursues small-team field installations. Use
[`criteria/TECHNICAL_SERVICES_PROFILE.md`](../criteria/TECHNICAL_SERVICES_PROFILE.md) for current
opportunity research. It covers security cameras, video monitoring, access
control, structured cabling, low-voltage data cabling, and bounded fiber work.
Use [`criteria/ELASTIC_LEAD_PROFILE.md`](../criteria/ELASTIC_LEAD_PROFILE.md)
only for deliberate legacy specialist sweeps.

Two ways to search SAM.gov contract opportunities:

| Tool | What | Speed | Freshness | When to use |
|------|------|-------|-----------|-------------|
| **`scripts/search_bulk.py`** | Queries a local SQLite mirror of SAM.gov's daily extract | Sub-second | Up to 24h old | **Default for everything.** Fast, reliable, no key needed |
| **`scripts/find_contracts.py`** | Hits the live SAM.gov API | 30–90s (SAM is slow) | Real-time | Only when "just-posted" data matters and bulk is stale |

There's also **`scripts/sync_bulk.py`** which downloads the daily extract and refreshes the local DB. Run it once a day or whenever you want fresh data.

For solicitation attachments and statements of work, **`scripts/document_store.py`**
indexes extracted document text into local Elasticsearch so an agent can search
evidence such as required systems, deliverables, licenses, insurance, or OEM
requirements. See
[`DOCUMENT_INDEX.md`](DOCUMENT_INDEX.md).

---

## 2. One-time setup

### 2.1 Install Python dependencies

Open PowerShell anywhere and run:

```
pip install -r "<PROJECT_DIR>\requirements.txt"
```

That installs `requests` and `python-dotenv`. Takes ~5 seconds.

### 2.2 (Optional) Add a SAM.gov API key

Only needed for the live-API script. The bulk scripts don't need one.

1. Sign in at https://sam.gov → Account Details → API Key (it generates one)
2. Copy `.env.example` to `.env` in this folder
3. Paste the key after `SAM_API_KEY=`

Keep the API key only in the local `.env` file and do not commit it.

### 2.3 First sync

Download today's data into the local DB:

```
python "<PROJECT_DIR>\scripts\sync_bulk.py"
```

Takes ~13 seconds (downloads 220 MB, parses ~80k rows, indexes the DB). When it's done, you'll have a `data/contracts.db` file in this folder (~250 MB).

---

## 3. Daily usage

### 3.1 Refresh the database (once per day)

```
python "<PROJECT_DIR>\scripts\sync_bulk.py"
```

You can automate this — see [§5 Automation](#5-automation).

### 3.2 Search the database

```
python "<PROJECT_DIR>\scripts\search_bulk.py" [keyword] [flags]
```

Run with `--help` for the full flag list.

### 3.3 Rank simplified-acquisition candidates

Use the SAP selector to find small SAM.gov buys that may help build past
performance. This path applies hard gates only. It does not score capability
keywords.

```
python "<PROJECT_DIR>\scripts\swcb.py" sap
```

The command prints the observed set-aside and PSC encodings first, then writes:

- `reports/sap-opportunities.md`
- `reports/sap-opportunities.csv`
- `reports/sam-opportunity-encodings.md`

The SAM bulk CSV currently does not expose an estimated solicitation-value
field. The selector automatically uses `estimated_value` if the mirror gains
that column later. For the current schema, a populated `Award$` value is used
only as a conservative ceiling fallback; blank values remain eligible and sort
after populated values.

---

## 4. Common search recipes

| Need | Command |
|------|---------|
| Security-camera candidates | `search_bulk.py "security camera" --active-only` and `search_bulk.py "CCTV" --active-only` |
| Video-monitoring candidates | `search_bulk.py "video monitoring" --active-only` and `search_bulk.py "video surveillance" --active-only` |
| Access-control candidates | `search_bulk.py "access control" --active-only` and `search_bulk.py "card reader" --active-only` |
| Structured-cabling candidates | `search_bulk.py "structured cabling" --active-only` and `search_bulk.py "data cabling" --active-only` |
| Fiber candidates | `search_bulk.py "fiber optic" --active-only` |
| NAICS 561621 expansion | `search_bulk.py --naics 561621 --active-only` |
| Filtered NAICS 238210 expansion | `search_bulk.py "cabling" --naics 238210 --active-only` and `search_bulk.py "fiber" --naics 238210 --active-only` |
| Sources sought for pipeline scouting | `search_bulk.py "data cabling" --type "Sources Sought"` |
| JSON output for piping to another tool | append `--json` to any of the above |

`--active-only` follows SAM's active field and does not prove that the response
deadline is still open. Filter actual deadlines against today's date before
presenting biddable candidates.

---

## 5. Automation

### Daily auto-sync via Windows Task Scheduler

Open PowerShell **as admin** and run:

```
schtasks /Create /SC DAILY /TN "SAM Daily Sync" /TR "python <PROJECT_DIR>\scripts\sync_bulk.py" /ST 06:30
```

This sets up a job that runs at 6:30 AM every day. To remove it later:

```
schtasks /Delete /TN "SAM Daily Sync" /F
```

---

## 6. Reference

### 6.1 All `search_bulk.py` flags

| Flag | Purpose | Default |
|------|---------|---------|
| `keyword` (positional) | Free-text in title + description | none |
| `--naics CODE` | NAICS code, exact or **prefix** (`54151` catches `541511`, `541512`, and `541519`) | none |
| `--state XX` | 2-letter state code, place of performance | none |
| `--set-aside CODE` | See §6.3 | none |
| `--type STR` | Notice type substring (`Solicitation`, `Sources Sought`, ...) | none |
| `--days N` | Posted within last N days. `0` = no limit | 30 |
| `--active-only` | Only currently active opportunities | off |
| `--limit N` | Max results | 20 |
| `--json` | JSON instead of pretty text | off |

### 6.2 NAICS discovery hints for field installations

| NAICS | Candidate category |
|-------|-------|
| 561621 | Security Systems Services (except Locksmiths) |
| 238210 | Electrical contractors and other wiring installation contractors; filter for low-voltage, cabling, and fiber scope |
| 541512 | Computer systems design services; conditional for small integration work |
| 334290 | Equipment-heavy installation discovery hint only |

These codes broaden discovery only. A public scope document must establish
camera, video-monitoring, access-control, cabling, fiber, or adjacent
small-installation fit before ranking an opportunity.

### 6.3 Set-aside codes

| Code | Meaning |
|------|---------|
| `SBA` | Total Small Business |
| `SBP` | Partial Small Business |
| `8A` | 8(a) Set-Aside |
| `8AN` | 8(a) Sole Source |
| `WOSB` | Women-Owned Small Business |
| `EDWOSB` | Economically Disadvantaged WOSB |
| `SDVOSBC` | Service-Disabled Veteran-Owned SB |
| `HZC` | HUBZone |
| `HZS` | HUBZone Sole Source |
| `IEE` | Indian Economic Enterprise |
| `ISBEE` | Indian Small Business Economic Enterprise |

### 6.4 Procurement type codes (`--ptype` on live API only)

| Code | Type |
|------|------|
| `o` | Solicitation (active RFP) |
| `k` | Combined synopsis/solicitation |
| `p` | Presolicitation |
| `r` | Sources sought (early scouting) |
| `s` | Special notice |
| `g` | Sale of surplus property |

For the bulk script use `--type "Solicitation"` etc. instead (substring match on the notice type field).

---

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `DB not found at data/contracts.db` | You haven't run sync yet | Run `sync_bulk.py` once |
| Search returns zero hits when you expected some | Filters too tight (often `--state` or `--active-only`) | Drop one filter at a time |
| `search_bulk.py` results feel stale | DB is more than a day old | Re-run `sync_bulk.py` |
| `sync_bulk.py` hangs on download | Rare — SAM's S3 is usually fast | Wait, then retry. Check `https://falextracts.s3.amazonaws.com/Contract%20Opportunities/datagov/ContractOpportunitiesFullCSV.csv` in a browser |
| Live API (`find_contracts.py`) hangs for ages | SAM API is regularly slow (30–90s at peak) | Wait — script's timeout is 120s. Or just use bulk instead |
| `pip` says module not found | Dependencies not installed | `pip install -r requirements.txt` |
| The `link` URL in a result is broken | SAM occasionally archives notices | Search SAM.gov directly for the `notice_id` |

---

## 8. Where things live

| What | Where |
|------|-------|
| **Scripts** | `<PROJECT_DIR>\scripts\` |
| **Local DB** (after first sync) | `<PROJECT_DIR>\data\contracts.db` |
| **Elasticsearch document index** | Docker volume managed by `compose.yaml`; accessed through `scripts\document_store.py` |
| **MCP server** | `<PROJECT_DIR>\scripts\mcp_server.py` |
| **Codex broad lead skill** | `<PROJECT_DIR>\adapters\skills\technical-services-leads\SKILL.md` |
| **Codex Elastic-only skill** | `<PROJECT_DIR>\adapters\skills\elastic-contract-leads\SKILL.md` |
| **Codex document skill** | `<PROJECT_DIR>\adapters\skills\contracts-documents\SKILL.md` |
| **API key file** (if you use the live script) | `<PROJECT_DIR>\.env` |

Claude Desktop consumes the Docker MCP server; Codex can use that same MCP
server plus project-local skills for workflow guidance.

---

## 9. Data source

- **URL:** `https://falextracts.s3.amazonaws.com/Contract Opportunities/datagov/ContractOpportunitiesFullCSV.csv`
- **Format:** CSV, ~220 MB, ~80k rows
- **Refresh:** daily (overnight US Eastern)
- **Auth:** none (public)
- **License:** public domain (US Government work)
- **Documentation:** https://sam.gov/data-services/Contract%20Opportunities/datagov?privacy=Public

---

## 10. Quick reference card

```
# Refresh the local DB (~13s, run daily)
python "<PROJECT_DIR>\scripts\sync_bulk.py"

# Search (sub-second)
python "<PROJECT_DIR>\scripts\search_bulk.py" "Elasticsearch" --active-only

# Show flag help
python "<PROJECT_DIR>\scripts\search_bulk.py" --help

# Live API fallback (slow, real-time)
python "<PROJECT_DIR>\scripts\find_contracts.py" "Elasticsearch"
```
