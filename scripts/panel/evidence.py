"""Retrieve public indexed evidence for panel transmission."""

from __future__ import annotations

from typing import Any

from document_store import DocumentStoreError, ElasticDocumentStore, Settings

from .schema import EvidenceRef, EvidenceSnippet

PANEL_EVIDENCE_QUERY = (
    "requirements scope deliverables clearance facility clearance certifications "
    "past performance subcontracting staffing schedule security technical approach"
)


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "public"}


def is_explicitly_public(source: dict[str, Any]) -> bool:
    metadata = source.get("metadata") or {}
    if not isinstance(metadata, dict):
        return False
    public_url = str(metadata.get("public_source_url") or "").strip().lower()
    return _truthy(metadata.get("public")) or public_url.startswith("https://")


def retrieve_public_evidence(
    notice_id: str,
    *,
    store: ElasticDocumentStore | None = None,
    limit: int = 12,
) -> list[EvidenceSnippet]:
    """Retrieve evidence chunks; API-boundary validation decides if transmission is allowed."""
    store = store or ElasticDocumentStore(Settings.from_env())
    try:
        store.ensure_index()
        hits = store.lexical_search(
            PANEL_EVIDENCE_QUERY,
            [{"term": {"notice_id": notice_id}}],
            max(1, min(limit, 20)),
        )
    except DocumentStoreError:
        raise
    if not hits:
        raise DocumentStoreError(
            f"No indexed evidence found for notice {notice_id!r}. "
            "Ingest a public solicitation document before running the panel."
        )
    snippets = []
    for hit in hits:
        source = hit.get("_source", {})
        document_id = str(source.get("document_id") or "").strip()
        chunk_number = str(source.get("chunk_number") or "").strip()
        if not document_id or not chunk_number:
            continue
        snippets.append(
            EvidenceSnippet(
                ref=EvidenceRef(doc_id=document_id, locator=f"chunk:{chunk_number}"),
                text=str(source.get("text") or ""),
                title=str(source.get("title") or source.get("filename") or ""),
                source=str(source.get("source") or ""),
                public=is_explicitly_public(source),
            )
        )
    if not snippets:
        raise DocumentStoreError(f"Indexed evidence for notice {notice_id!r} has no usable chunks.")
    return snippets
