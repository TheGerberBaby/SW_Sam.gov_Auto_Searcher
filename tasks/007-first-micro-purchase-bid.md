---
id: 007-first-micro-purchase-bid
title: Submit Stormwind's first micro-purchase bid
status: planned
priority: high
effort: M
type: bid
dependencies: [002-sam-gov-registration]
tags: [milestone, validation, first-bid]
owner: jeremy
created: 2026-05-29
updated: 2026-05-31
---

## Why this matters

This is the **end-to-end validation milestone** for the entire
pipeline (scoring → digest → watchlist → response). Until a real
quote goes out, every upstream improvement is theoretical.

Micro-purchase threshold is currently **$15,000** for most federal
acquisitions ([FAR 2.101](https://www.acquisition.gov/far/2.101), adjusted
effective 2025-10-01 by [FAC 2025-06](https://www.acquisition.gov/fac/fac2025-06)).
Picking a true
micro-purchase keeps the response work proportional to learning
value rather than dollar stakes.

## Strategy

- Pick a Tier-1 or Tier-2 field-installation opportunity with
  - clear, bounded SOW
  - response deadline ≥ 7 days out
  - one site or a tightly bounded site list
  - place of performance compatible with the crew's travel and warranty radius
  - licensing, technician-registration, insurance, and site-access requirements confirmed
  - equipment sourcing and material lead times compatible with the schedule
  - manageable evaluation criteria
- Run it through [scripts/scoring.py](../scripts/scoring.py) and
  ingest the SOW into Elasticsearch via [scripts/document_store.py](../scripts/document_store.py)
  before drafting.
- Use the watchlist to track status: `tracking` → `assessing` →
  `pursuing` → `submitted`.

## Subtasks

- [ ] Identify candidate (add to watchlist with status `assessing`)
- [ ] Pull SOW / RFQ attachments into the document index
- [ ] Confirm Stormwind clears each "must-have" requirement
- [ ] Confirm jurisdiction-specific licensing and technician registrations
- [ ] Cost equipment, travel, insurance, installation labor, and warranty response
- [ ] Decide go/no-go — record the call
- [ ] If go: draft quote / capability statement / response
- [ ] Submit
- [ ] Record submission in watchlist (status `submitted`)
- [ ] Whatever the outcome: log lessons learned here

## Acceptance criteria

A real quote is submitted to a real federal buying activity through
the prescribed channel before the response deadline. Outcome doesn't
have to be "won" — submission is the validation.

## Notes

(empty)
