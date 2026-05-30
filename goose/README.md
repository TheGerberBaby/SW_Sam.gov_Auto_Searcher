# Goose orchestration

This directory holds the [Goose](https://github.com/aaif-goose/goose)
recipes and extension-config snippets for unattended runs of the
SW Contracting Bots pipeline. Goose is an Apache-2.0 MCP-native agent
runtime now hosted by the Linux Foundation's AAIF.

The deep-research report's recommendation: keep heavy unattended work
(nightly SAM hunt, email ingest, roadmap review) inside Goose, while
keeping the FastMCP server as the tool surface and Claude Code /
Codex as the model providers via ACP.

## What you need to install separately

Goose isn't bundled in this repo. Install it once, then point it at
the files here.

```powershell
# Windows install via winget (per the AAIF goose README)
winget install Block.Goose

# or download a release binary from
# https://github.com/aaif-goose/goose/releases
```

Verify:

```powershell
goose --version
```

## Wiring our FastMCP server as a Goose extension

Goose extensions are stdio MCP servers. The FastMCP server in this
repo is already that. Drop the block from
[`config.example.yaml`](config.example.yaml) into
`~/.config/goose/config.yaml` (or your Windows equivalent under
`%APPDATA%\Goose\config.yaml`) — adjust the working directory to
match where this repo lives on your machine.

## Recipes

| Recipe | What it does | Suggested cron |
| --- | --- | --- |
| [`recipes/sam-hunt.yaml`](recipes/sam-hunt.yaml) | Refresh the SAM mirror, score recent notices, write a digest, surface strong hits | `0 6 * * *` (06:00 local) |
| [`recipes/roadmap-review.yaml`](recipes/roadmap-review.yaml) | Read `tasks/`, identify unblocked workstreams, summarize what's actionable today | `0 7 * * MON` (weekly) |
| [`recipes/incumbent-research.yaml`](recipes/incumbent-research.yaml) | For a given NAICS / agency, pull USAspending incumbents and write a report | on-demand |
| [`recipes/email-ingest.yaml`](recipes/email-ingest.yaml) | Poll IMAP for SAM alert mail, parse into watchlist (scaffold — needs IMAP MCP installed and app password configured first) | `*/30 * * * *` |

## Scheduling

```powershell
# Daily SAM hunt at 06:00 local
goose schedule add --schedule-id sam-hunt-daily --cron "0 6 * * *" `
  --recipe-source ./goose/recipes/sam-hunt.yaml

# Weekly roadmap review Monday 07:00
goose schedule add --schedule-id roadmap-weekly --cron "0 7 * * MON" `
  --recipe-source ./goose/recipes/roadmap-review.yaml
```

The first time a recipe runs, Goose spins up a fresh agent session
with the listed extensions loaded, executes the instructions, and
exits.

## Conservative defaults

All recipes here are **read-and-summarize** by default. Nothing
auto-submits, auto-emails, or auto-edits external state. The boundary
of "what Goose may do unattended" is intentionally tight:

- It may query SAM, USAspending, eCFR.
- It may run the scorer and write digest reports to `data/digests/`.
- It may append entries to the watchlist.
- It may read and report on `tasks/` but does **not** mutate task
  status without explicit user confirmation.

Stricter than the report's defaults, on purpose — until Jeremy
trusts the loop.
