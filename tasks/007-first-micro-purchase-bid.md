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
updated: 2026-05-29
---

## Why this matters

This is the **end-to-end validation milestone** for the entire
pipeline (scoring → digest → watchlist → response). Until a real
quote goes out, every upstream improvement is theoretical.

Micro-purchase threshold is currently **$10,000** for most federal
acquisitions (FAR 2.101, periodically adjusted). Picking a true
micro-purchase keeps the response work proportional to learning
value rather than dollar stakes.

## Strategy

- Pick a Tier-1 or Tier-2 technical-fit opportunity with
  - clear, bounded SOW
  - response deadline ≥ 7 days out
  - place of performance compatible with DMV / remote
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
