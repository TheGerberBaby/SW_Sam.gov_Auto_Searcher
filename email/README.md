# Email ingest (scaffold)

This directory holds the configuration and docs for plugging an IMAP
MCP server into the pipeline. The runtime work is **not** done by
code in this repo — it's done by a third-party MCP server that
Stormwind operates against the operator's mailbox with an
app-specific password.

The deep-research report recommends
[`ai-zerolab/mcp-email-server`](https://github.com/ai-zerolab/mcp-email-server)
as the starting point: IMAP + SMTP over MCP, multi-account, TOML
config, can run **read-only** (omit SMTP).

## Why read-only matters

Unattended agents with shell + email access can do damage fast. The
boundary we want:

- Agents may **read** SAM alert mail and parse notice IDs.
- Agents may **mark messages read**.
- Agents may **NOT** send, reply, forward, draft, label, move, or
  delete.

`mcp-email-server` enforces this when SMTP is left unconfigured (the
compose / send tools are hidden from the MCP surface).

## Setup

### 1. Generate an app password

- **Gmail:** Google account → Security → 2-Step Verification → App
  passwords. Generate a 16-char password for "Mail." Never use your
  primary Google password.
- **Microsoft 365 / Outlook.com:** Microsoft account → Security →
  Advanced security options → App passwords.
- **Other IMAP hosts:** check the provider's docs.

Store the password in an environment variable (do **not** commit it):

```powershell
# add to your shell profile or the goose service environment
$env:EMAIL_APP_PASSWORD = "<16-char-app-password>"
```

### 2. Install the IMAP MCP server

```powershell
pipx install mcp-email-server
# or run on demand:
uvx mcp-email-server@latest stdio --help
```

### 3. Configure read-only access

See [`config.example.toml`](config.example.toml) in this directory.
Adjust the host, username, and `allowed_folders` list to scope the
agent's access to just what it needs (typically the folder where
your SAM alert emails land).

### 4. Wire it into Goose

Uncomment the `imap-mail` extension block in
[`../goose/config.example.yaml`](../goose/config.example.yaml).

### 5. Schedule the recipe

```powershell
goose schedule add --schedule-id email-ingest --cron "*/30 * * * *" \
  --recipe-source ./goose/recipes/email-ingest.yaml
```

The recipe scans for SAM alert messages, extracts notice IDs,
scores them, and adds high-score hits to the watchlist. It never
sends mail and never modifies folder structure. See
[`../goose/recipes/email-ingest.yaml`](../goose/recipes/email-ingest.yaml)
for the exact instructions.

## Sanity checklist

Before you turn the recipe loose, manually verify each invariant once:

- [ ] App password works on a manual IMAP login
- [ ] `mcp-email-server` lists messages but **cannot** send (try a
      send call; should be hidden / refused)
- [ ] `allowed_folders` is set to the smallest viable scope
- [ ] Goose recipe `email-ingest.yaml` runs once successfully on demand
- [ ] Scheduled run produces a watchlist entry from a known test email

Only after all five pass should the schedule run unattended.
