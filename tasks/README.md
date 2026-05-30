# tasks/

One markdown file per business workstream. Frontmatter is YAML
(`---` delimited). The body is freeform markdown — context, decisions,
links, dated notes.

This is the "spine" of the project. Agents and humans both read and
update these files. Git is the state machine; every status change is
auditable.

## Frontmatter schema

```yaml
---
id: 003-sdvosb-vetcert          # filename slug, also unique key
title: SDVOSB certification via SBA VetCert
status: planned                 # see vocabulary below
priority: high                  # high | medium | low
effort: M                       # S (hours) | M (days) | L (weeks)
type: certification             # certification | registration | bid | infrastructure | research
dependencies: [001-entity-formation, 002-sam-gov-registration]
tags: [sdvosb, federal, sba]
owner: jeremy                   # who's expected to drive it
created: 2026-05-29
updated: 2026-05-29
---
```

## Status vocabulary

| status | meaning |
| --- | --- |
| `planned` | Committed-to-do but not started |
| `in-progress` | Active work is happening on this |
| `blocked` | Cannot advance until a dependency lifts (record the blocker in the body) |
| `pending` | Filed / submitted, awaiting external action |
| `done` | Completed — record outcome in body |
| `dropped` | Explicitly decided not to pursue (record the reason) |

## Adding a task

```powershell
.\swcb.bat tasks new "Register for eVA" --priority medium --type registration
```

…or copy an existing file. The `id` field must match the filename
slug (`tasks/<id>.md`).

## Querying

```powershell
.\swcb.bat tasks list              # all tasks, grouped by status
.\swcb.bat tasks list --status blocked
.\swcb.bat tasks unblocked         # next-actionable workstreams
.\swcb.bat tasks validate          # frontmatter check
.\swcb.bat tasks status 003-sdvosb-vetcert in-progress --note "DD-214 located"
```

## The "never hard-block" rule

When Jeremy or an agent asks "what should I work on next?", consult
[ROADMAP_REVIEW.md](../ROADMAP_REVIEW.md) for the scheduling policy.
The short version: never spend two consecutive cycles on a blocked
task; always advance at least one unblocked workstream.
