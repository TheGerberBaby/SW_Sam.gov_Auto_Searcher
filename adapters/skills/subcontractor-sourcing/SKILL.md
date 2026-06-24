---
name: subcontractor-sourcing
description: Source local subcontractors or vendors for an opportunity the operator has already decided to prime. Use when the operator needs performer discovery, phone numbers, a cold-call script, or a follow-up email ask-list for a selected pursuit.
---

# Subcontractor Sourcing

Use this skill after the operator decides to pursue an opportunity as prime and
needs local performers. The canonical sourcing and qualification rules are in:

`<PROJECT_DIR>\criteria\VENDOR_SOURCING_PROFILE.md`

## Workflow

1. Read `criteria/VENDOR_SOURCING_PROFILE.md`.
2. Confirm the opportunity's service scope, NAICS, place or places of
   performance, and response deadline from source evidence.
3. Run the sourcing command from the project root:

```powershell
python .\scripts\swcb.py vendors --naics 561621 --place "Alexandria, VA" --due "29 Jun 2026"
python .\scripts\swcb.py vendors "tree removal" --place "Accokeek, MD" --json
```

4. Use the returned call script and email ask-list as outreach preparation.
5. Treat discovered businesses as candidates only. Confirm capabilities,
   service area, quote, schedule, licensing, certifications, insurance, payment
   terms, and size status directly with the vendor.

## Workbench Card Jobs

Each opportunity card can create a durable sourcing job through
`POST /api/vendors/source-opportunity`. The preliminary report is written under
`reports/` and the Codex handoff context is written under
`data/vendor-sourcing-jobs/`.

When MCP tools are available:

1. Call `list_vendor_sourcing_jobs` to find `queued_for_codex` jobs.
2. Call `get_vendor_sourcing_job` for the selected job.
3. Complete the public solicitation-document and vendor-web research.
4. Call `complete_vendor_sourcing_job` with the sourced Markdown report.

The queued preliminary report is not a bid approval and is not evidence that a
vendor is qualified.

## Judgement Rules

- Do not use this lane to justify an unrelated opportunity. It is downstream of
  bid selection.
- Never claim a vendor holds a license, certification, clearance, OEM status,
  size status, or eligibility without confirmation.
- Check whether the prime, subcontractor, or both must hold each solicitation
  requirement.
- For multi-site work, confirm each service location rather than relying on one
  local search.
