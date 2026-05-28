# MCP Setup - technical-contract-research

The MCP server runs in Docker per [ARCHITECTURE.md](ARCHITECTURE.md). Every
client talks to the same `docker compose run mcp` stdio process. The bits
below are the per-client *registration* steps.

Prereqs: Docker Desktop running, `pip install -r requirements.txt` already
done on the host (for the daily sync scripts), and a `data/contracts.db`
produced by `scripts/sync_bulk.py`.

---

## Claude Code (CLI)

Already wired. `.mcp.json` in the project root registers the server.
The first time Claude Code launches in this folder it will ask you to
trust the project-level MCP config - approve once and `search_opportunities`,
`document_index_status`, `ingest_public_document`, and `search_documents`
appear as `mcp__technical-contract-research__*` tools.

Restart Claude Code (or run `/mcp` to reconnect) after pulling new commits
that change `.mcp.json`.

---

## Codex (CLI / Desktop)

Add to `~/.codex/config.toml`:

```toml
[mcp_servers.technical-contract-research]
command = "docker"
args = [
  "compose",
  "-f", "<PROJECT_DIR>/compose.yaml",
  "--profile", "mcp",
  "run", "--rm", "-i", "mcp",
]
```

Codex reads the config globally, so the `-f` pin to `compose.yaml` is
required - Codex does not cd into the project before spawning the server.

Codex skills that drive this MCP live under
`adapters/skills/technical-services-leads/`,
`adapters/skills/elastic-contract-leads/`, and
`adapters/skills/contracts-documents/`. Install them with the
`scripts/install_*.ps1` helpers if Codex isn't picking them up.

---

## Claude Desktop

Add to `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "technical-contract-research": {
      "command": "docker",
      "args": [
        "compose",
        "-f", "<PROJECT_DIR>/compose.yaml",
        "--profile", "mcp",
        "run", "--rm", "-i", "mcp"
      ]
    }
  }
}
```

Same `-f` rationale as Codex - Claude Desktop spawns from its own working
directory, not the project root.

---

## Sanity check

After registration, ask the client to run the `find_technical_services_leads`
prompt or call `document_index_status`. Docker will pull `elasticsearch:9.4.1`
on first run (~1.3 GB, one-time) and the MCP startup will wait for the ES
healthcheck. Subsequent invocations attach to the already-healthy ES
container and are fast.
