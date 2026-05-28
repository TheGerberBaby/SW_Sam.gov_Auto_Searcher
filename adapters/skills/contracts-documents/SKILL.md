---
name: contracts-documents
description: Ingest and search SAM.gov solicitation attachments, statements of work, amendments, and contracting research notes in the local Elasticsearch knowledge index. Use when the user provides contract documents, asks to remember or analyze an attachment, asks about requirements hidden in documents, or wants evidence for technical fit or bid risk.
---

# Contract Document Knowledge Index

Use this skill for unstructured solicitation evidence. Use `contracts-bulk` or
`find-contracts` for opportunity discovery and structured filters.

Project root:

`<PROJECT_DIR>`

## Execution

Prefer MCP tools `document_index_status`, `ingest_public_document`, and
`search_documents` when the `technical-contract-research` server is available.

For direct-command fallback in Codex, Elasticsearch runs on the Windows host
at `127.0.0.1:9200`; run Python commands from the project root.

## Ingest Documents

When a user asks to store, analyze, or remember a solicitation attachment:

1. Prefer the public HTTPS download URL so the MCP tool can retain it as source
   metadata. A local file is usable only with direct-command fallback.
2. Capture the SAM `notice_id`, solicitation number, and a useful title when available.
3. Direct-command fallback for a file or URL:

```powershell
python .\scripts\document_store.py ingest "<file-or-https-url>" --notice-id "<notice-id>" --solicitation-number "<sol-number>" --title "<title>" --json
```

Use only files supplied by the user or public procurement-document URLs relevant
to the request. Do not ingest credentials, private correspondence, or controlled
SAM attachments without explicit approval and proper access.

If the output says a PDF has no extractable text, report that OCR is required.

## Search Document Evidence

For requirements, scope, required platforms, clearances, partner/reseller
status, or bid-risk questions, search indexed documents. Direct-command
fallback:

```powershell
python .\scripts\document_store.py search "<query>" --notice-id "<notice-id>" --json
```

If there is no particular notice, omit `--notice-id`.

Use `--mode hybrid` only when the project `.env` has semantic embeddings enabled
and previously ingested documents were embedded. Otherwise, use the default
text search.

## Response Rules

- Treat retrieved excerpts as evidence, not as final legal or bid advice.
- Always identify the source filename and notice ID when summarizing a requirement.
- State clearly when required information was not found in indexed documents.
- Use the SQLite/SAM opportunity tools for deadlines and current notice status;
  the document index may contain superseded amendments.
