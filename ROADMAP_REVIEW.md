# Roadmap Review — Agent Policy

> Read this file whenever Jeremy (or another agent) asks "what should I
> work on next?" or "what's the state of the roadmap?". This is the
> **never-hard-block** rule the spine depends on.

## TL;DR

1. Run `swcb tasks unblocked` (or call `tasks_lib.next_unblocked()`).
2. Pick from the top of that list, weighted by priority.
3. **Never spend two consecutive cycles on a blocked task.**
4. Surface at least one parallel workstream so progress stays
   visible while any one item is gated by an external system.

## The data model in one paragraph

Every business workstream is a file in [`tasks/`](tasks/) with YAML
frontmatter. The fields that matter for scheduling are `status`,
`priority`, and `dependencies`. A task is **actionable** when its
status is `planned`, `in-progress`, or `unknown` and every dependency
has status `done`. Anything else (`blocked`, `pending`, `done`,
`dropped`) is *not* in the next-action set.

The parser at [`scripts/tasks_lib.py`](scripts/tasks_lib.py) is the
source of truth. Don't reinvent the dependency graph; call it.

## Status semantics in agent terms

| status | agent should do |
| --- | --- |
| `planned` | Surface as a candidate. Ask Jeremy if he wants to start it. |
| `in-progress` | Continue or report progress. Do not silently switch off it. |
| `blocked` | Note the blocker once. Move on — don't loop. |
| `pending` | Don't push it. Mention when its expected external action lands. |
| `done` | Treat as foundation; surface dependents as newly actionable. |
| `dropped` | Ignore entirely. The reason is in the body. |
| `unknown` | First priority is to ask Jeremy the question — don't fabricate the answer. |

## The "advance at least N parallel workstreams" rule

When summarizing what to do next, **surface at least three tracks**
(or all of them, if fewer are actionable). Never present a single
serial path through dependencies — that recreates the hard-block the
report warned against.

Example — once `001-entity-formation` flips to `done`, four tasks
unblock at once:

```
[H] 002-sam-gov-registration
[H] 004-fincen-boi
[M] 005-virginia-swam
[M] 006-eva-registration
```

Present them all. Let Jeremy decide which to drive in parallel based
on his attention budget. Don't queue them serially.

## When something is blocked

A task with `status: blocked` should have the blocker named in its
body — typically a date, an external review, or a missing document.

Agent behavior on a blocked task:

1. Read the blocker; if it has lifted (date passed, document arrived),
   propose changing the status back to `planned` or `in-progress`.
2. If it hasn't lifted, **mention it once in the report and move on**.
3. Don't ask the same question two cycles in a row. Save it for the
   next time the blocker plausibly might have moved.

## When a status field is `unknown`

Jeremy hasn't told the agent what's true. Don't invent it. The
correct move is:

1. Surface it in the report as a fast question.
2. Group `unknown`s together so Jeremy can knock several out in one
   pass.
3. If the answer is obvious from context (e.g., SAM.gov registration
   would be reflected in his actual account status), propose the
   answer and ask for confirmation; do not silently flip the field.

## How to update tasks

Always go through the CLI / library so updates and audit notes are
consistent:

```powershell
.\swcb.bat tasks status 003-sdvosb-vetcert in-progress --note "DD-214 located"
.\swcb.bat tasks status 003-sdvosb-vetcert pending --note "filed at VetCert"
.\swcb.bat tasks status 003-sdvosb-vetcert done --note "approved; cert # XYZ"
```

The library appends a dated note to the task body and updates the
`updated:` frontmatter field. Commit each meaningful change so Git
preserves the history.

## How to propose a new task

```powershell
$id = .\swcb.bat tasks next-id   # e.g. 008
```

Create `tasks/008-<short-slug>.md` using the schema in
[`tasks/README.md`](tasks/README.md). Wire `dependencies:` carefully.
Run `swcb tasks validate` before committing.

## What this policy is NOT

- Not a substitute for Jeremy's judgement. The agent's job is to
  surface options, not pick for him.
- Not a license to auto-execute tasks that touch the world
  (submitting filings, sending emails, etc.). Those require explicit
  consent.
- Not a replacement for the opportunity watchlist. Tasks/ holds
  *business* workstreams (certs, registrations, foundational bids).
  Individual SAM opportunities live in `data/watchlist.db`.
