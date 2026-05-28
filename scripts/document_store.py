"""Ingest and retrieve solicitation documents with Elasticsearch.

This is the document knowledge layer for public opportunity research. It is
separate from the SQLite opportunity database: SQLite remains authoritative for
deadlines and eligibility fields, while Elasticsearch stores searchable chunks
from solicitation files, amendments, and research notes.

Usage:
  python document_store.py init
  python document_store.py status --json
  python document_store.py ingest "path\\to\\sow.pdf" --notice-id NOTICE --json
  python document_store.py ingest "https://example/document.pdf" --notice-id NOTICE
  python document_store.py search "bonding requirement" --notice-id NOTICE --json
  python document_store.py search "authorized reseller" --mode hybrid --json
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import mimetypes
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import Message
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote, unquote_plus, urlparse

import requests
from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
load_dotenv(PROJECT_DIR / ".env")

SUPPORTED_SUFFIXES = {".pdf", ".docx", ".txt", ".md", ".html", ".htm", ".csv"}
DEFAULT_INDEX = "stormwind_documents_v1"


class DocumentStoreError(RuntimeError):
    """Raised for a user-facing document store failure."""


@dataclass(frozen=True)
class Settings:
    elasticsearch_url: str
    index_name: str
    chunk_chars: int
    chunk_overlap: int
    max_document_bytes: int
    request_timeout: int
    embedding_provider: str
    embedding_model: str
    embedding_dimensions: int
    openai_api_key: str | None
    elasticsearch_api_key: str | None
    elasticsearch_username: str | None
    elasticsearch_password: str | None

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            elasticsearch_url=os.getenv("ELASTICSEARCH_URL", "http://localhost:9200").rstrip("/"),
            index_name=os.getenv("ELASTICSEARCH_INDEX", DEFAULT_INDEX),
            chunk_chars=int(os.getenv("DOCUMENT_CHUNK_CHARS", "3500")),
            chunk_overlap=int(os.getenv("DOCUMENT_CHUNK_OVERLAP", "350")),
            max_document_bytes=int(os.getenv("MAX_DOCUMENT_BYTES", str(50 * 1024 * 1024))),
            request_timeout=int(os.getenv("DOCUMENT_REQUEST_TIMEOUT", "60")),
            embedding_provider=os.getenv("EMBEDDING_PROVIDER", "none").strip().lower(),
            embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
            embedding_dimensions=int(os.getenv("EMBEDDING_DIMENSIONS", "1536")),
            openai_api_key=os.getenv("OPENAI_API_KEY") or None,
            elasticsearch_api_key=os.getenv("ELASTICSEARCH_API_KEY") or None,
            elasticsearch_username=os.getenv("ELASTICSEARCH_USERNAME") or None,
            elasticsearch_password=os.getenv("ELASTICSEARCH_PASSWORD") or None,
        )


class _PlainTextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.fragments: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.fragments.append(text)

    def text(self) -> str:
        return "\n".join(self.fragments)


class ElasticDocumentStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _headers(self, content_type: str = "application/json") -> dict[str, str]:
        headers = {"Content-Type": content_type}
        if self.settings.elasticsearch_api_key:
            headers["Authorization"] = f"ApiKey {self.settings.elasticsearch_api_key}"
        return headers

    def _auth(self) -> tuple[str, str] | None:
        if self.settings.elasticsearch_username and self.settings.elasticsearch_password:
            return (self.settings.elasticsearch_username, self.settings.elasticsearch_password)
        return None

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        data: str | None = None,
        content_type: str = "application/json",
        allowed: tuple[int, ...] = (200,),
    ) -> requests.Response:
        url = f"{self.settings.elasticsearch_url}/{path.lstrip('/')}"
        try:
            response = requests.request(
                method,
                url,
                json=body,
                data=data,
                headers=self._headers(content_type),
                auth=self._auth(),
                timeout=(5, self.settings.request_timeout),
            )
        except requests.RequestException as exc:
            raise DocumentStoreError(
                f"Cannot connect to Elasticsearch at {self.settings.elasticsearch_url}. "
                "Start it with: docker compose up -d elasticsearch"
            ) from exc
        if response.status_code not in allowed:
            detail = response.text[:500].replace("\n", " ")
            raise DocumentStoreError(
                f"Elasticsearch request failed ({response.status_code}) for {path}: {detail}"
            )
        return response

    def ensure_index(self) -> bool:
        exists = self.request("HEAD", self.settings.index_name, allowed=(200, 404))
        if exists.status_code == 200:
            return False
        mapping = {
            "settings": {
                "index": {
                    "number_of_shards": 1,
                    "number_of_replicas": 0,
                }
            },
            "mappings": {
                "properties": {
                    "document_id": {"type": "keyword"},
                    "chunk_id": {"type": "keyword"},
                    "chunk_number": {"type": "integer"},
                    "total_chunks": {"type": "integer"},
                    "notice_id": {"type": "keyword"},
                    "solicitation_number": {"type": "keyword"},
                    "title": {
                        "type": "text",
                        "fields": {"keyword": {"type": "keyword", "ignore_above": 512}},
                    },
                    "document_type": {"type": "keyword"},
                    "filename": {"type": "keyword"},
                    "source": {"type": "keyword", "index": False},
                    "content_type": {"type": "keyword"},
                    "content_sha256": {"type": "keyword"},
                    "ingested_at": {"type": "date"},
                    "text": {"type": "text"},
                    "metadata": {"type": "object", "enabled": False},
                    "embedding_model": {"type": "keyword"},
                    "embedding": {
                        "type": "dense_vector",
                        "dims": self.settings.embedding_dimensions,
                        "index": True,
                        "similarity": "cosine",
                    },
                }
            },
        }
        self.request("PUT", self.settings.index_name, body=mapping, allowed=(200,))
        return True

    def health(self) -> dict[str, Any]:
        cluster = self.request("GET", "_cluster/health", allowed=(200,)).json()
        exists = self.request("HEAD", self.settings.index_name, allowed=(200, 404))
        count = 0
        if exists.status_code == 200:
            count = self.request("GET", f"{self.settings.index_name}/_count", allowed=(200,)).json()[
                "count"
            ]
        return {
            "elasticsearch_url": self.settings.elasticsearch_url,
            "cluster_name": cluster.get("cluster_name"),
            "status": cluster.get("status"),
            "index": self.settings.index_name,
            "index_exists": exists.status_code == 200,
            "chunks": count,
            "embedding_provider": self.settings.embedding_provider,
        }

    def replace_document_chunks(self, document_id: str, chunks: list[dict[str, Any]]) -> None:
        self.ensure_index()
        self.request(
            "POST",
            f"{self.settings.index_name}/_delete_by_query?refresh=true&conflicts=proceed",
            body={"query": {"term": {"document_id": document_id}}},
            allowed=(200,),
        )
        lines: list[str] = []
        for chunk in chunks:
            lines.append(
                json.dumps(
                    {"index": {"_index": self.settings.index_name, "_id": chunk["chunk_id"]}},
                    ensure_ascii=True,
                )
            )
            lines.append(json.dumps(chunk, ensure_ascii=True))
        response = self.request(
            "POST",
            "_bulk?refresh=true",
            data="\n".join(lines) + "\n",
            content_type="application/x-ndjson",
            allowed=(200,),
        ).json()
        if response.get("errors"):
            failures = []
            for item in response.get("items", []):
                result = item.get("index", {})
                if "error" in result:
                    failures.append(str(result["error"])[:200])
            raise DocumentStoreError(f"Elasticsearch bulk index failed: {'; '.join(failures[:3])}")

    def lexical_search(
        self, query: str, filters: list[dict[str, Any]], limit: int
    ) -> list[dict[str, Any]]:
        body = {
            "size": limit,
            "_source": {"excludes": ["embedding"]},
            "query": {
                "bool": {
                    "must": [
                        {
                            "multi_match": {
                                "query": query,
                                "fields": ["title^4", "filename^2", "text"],
                            }
                        }
                    ],
                    "filter": filters,
                }
            },
            "highlight": {"fields": {"text": {"fragment_size": 320, "number_of_fragments": 1}}},
        }
        return self.request("POST", f"{self.settings.index_name}/_search", body=body).json()[
            "hits"
        ]["hits"]

    def semantic_search(
        self, query_vector: list[float], filters: list[dict[str, Any]], limit: int
    ) -> list[dict[str, Any]]:
        knn: dict[str, Any] = {
            "field": "embedding",
            "query_vector": query_vector,
            "k": limit,
            "num_candidates": max(50, limit * 10),
        }
        if filters:
            knn["filter"] = {"bool": {"filter": filters}}
        body = {"size": limit, "_source": {"excludes": ["embedding"]}, "knn": knn}
        return self.request("POST", f"{self.settings.index_name}/_search", body=body).json()[
            "hits"
        ]["hits"]


def normalize_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_text(text: str, max_chars: int, overlap: int) -> list[str]:
    text = normalize_text(text)
    if not text:
        return []
    if max_chars < 200 or overlap < 0 or overlap >= max_chars:
        raise DocumentStoreError("Invalid chunk configuration: overlap must be smaller than chunk size.")
    chunks: list[str] = []
    start = 0
    while start < len(text):
        hard_end = min(len(text), start + max_chars)
        end = hard_end
        if hard_end < len(text):
            split_window = text[start + int(max_chars * 0.6) : hard_end]
            paragraph_break = split_window.rfind("\n\n")
            sentence_break = max(split_window.rfind(". "), split_window.rfind("; "))
            split_at = paragraph_break if paragraph_break >= 0 else sentence_break
            if split_at >= 0:
                end = start + int(max_chars * 0.6) + split_at + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks


def _read_limited_response(response: requests.Response, max_bytes: int) -> bytes:
    output = bytearray()
    for piece in response.iter_content(chunk_size=1024 * 1024):
        output.extend(piece)
        if len(output) > max_bytes:
            raise DocumentStoreError(f"Document exceeds maximum allowed size ({max_bytes} bytes).")
    return bytes(output)


def _is_windows_path(source: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", source)) or source.startswith("\\\\")


def _response_filename(content_disposition: str | None) -> str | None:
    if not content_disposition:
        return None
    message = Message()
    message["content-disposition"] = content_disposition
    raw_filename = message.get_filename()
    if not raw_filename:
        return None
    decoded_filename = unquote_plus(raw_filename)
    return Path(decoded_filename.replace("\\", "/")).name or None


def _is_pdf(data: bytes, filename: str, content_type: str) -> bool:
    return (
        Path(filename).suffix.lower() == ".pdf"
        or content_type == "application/pdf"
        or data.lstrip().startswith(b"%PDF-")
    )


def load_source(source: str, settings: Settings) -> tuple[bytes, str, str]:
    parsed = urlparse(source)
    if parsed.scheme in ("http", "https"):
        try:
            response = requests.get(source, stream=True, timeout=(10, settings.request_timeout))
            response.raise_for_status()
        except requests.RequestException as exc:
            raise DocumentStoreError(f"Unable to download {source}: {exc}") from exc
        filename = (
            _response_filename(response.headers.get("Content-Disposition"))
            or Path(unquote(parsed.path)).name
            or "downloaded-document"
        )
        content_type = response.headers.get("Content-Type", "").split(";")[0].strip()
        data = _read_limited_response(response, settings.max_document_bytes)
        return data, filename, content_type
    if parsed.scheme and not _is_windows_path(source):
        raise DocumentStoreError(f"Unsupported source URI scheme: {parsed.scheme}")
    path = Path(source).expanduser().resolve()
    if not path.exists() or not path.is_file():
        raise DocumentStoreError(f"Document not found: {path}")
    if path.stat().st_size > settings.max_document_bytes:
        raise DocumentStoreError(f"Document exceeds maximum allowed size: {path}")
    guessed_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return path.read_bytes(), path.name, guessed_type


def extract_text(data: bytes, filename: str, content_type: str) -> str:
    suffix = Path(filename).suffix.lower()
    if _is_pdf(data, filename, content_type):
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise DocumentStoreError("PDF ingestion requires pypdf. Run: pip install -r requirements.txt") from exc
        reader = PdfReader(io.BytesIO(data))
        return normalize_text("\n\n".join(page.extract_text() or "" for page in reader.pages))
    if suffix == ".docx" or "wordprocessingml" in content_type:
        try:
            from docx import Document
        except ImportError as exc:
            raise DocumentStoreError(
                "DOCX ingestion requires python-docx. Run: pip install -r requirements.txt"
            ) from exc
        document = Document(io.BytesIO(data))
        return normalize_text("\n".join(paragraph.text for paragraph in document.paragraphs))
    decoded = data.decode("utf-8", errors="replace")
    if suffix in {".html", ".htm"} or content_type == "text/html":
        parser = _PlainTextHTMLParser()
        parser.feed(decoded)
        return normalize_text(parser.text())
    return normalize_text(decoded)


def gather_sources(values: Iterable[str]) -> list[str]:
    sources: list[str] = []
    for value in values:
        parsed = urlparse(value)
        if parsed.scheme in ("http", "https"):
            sources.append(value)
            continue
        path = Path(value).expanduser().resolve()
        if path.is_dir():
            sources.extend(
                str(child)
                for child in sorted(path.rglob("*"))
                if child.is_file() and child.suffix.lower() in SUPPORTED_SUFFIXES
            )
        else:
            sources.append(value)
    return sources


def parse_metadata(values: list[str]) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise DocumentStoreError(f"Metadata must use key=value form: {value}")
        key, raw = value.split("=", 1)
        if not key.strip():
            raise DocumentStoreError(f"Metadata key is empty: {value}")
        metadata[key.strip()] = raw.strip()
    return metadata


def embedding_enabled(settings: Settings, provider: str | None) -> str:
    chosen = (provider or settings.embedding_provider).lower()
    if chosen not in {"none", "openai"}:
        raise DocumentStoreError("Embedding provider must be 'none' or 'openai'.")
    if chosen == "openai" and not settings.openai_api_key:
        raise DocumentStoreError("OPENAI_API_KEY is required when embedding provider is openai.")
    return chosen


def create_embeddings(settings: Settings, texts: list[str], provider: str) -> list[list[float]]:
    if provider == "none":
        return []
    vectors: list[list[float]] = []
    for offset in range(0, len(texts), 32):
        batch = texts[offset : offset + 32]
        payload = {
            "model": settings.embedding_model,
            "input": batch,
            "dimensions": settings.embedding_dimensions,
        }
        try:
            response = requests.post(
                "https://api.openai.com/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=(10, settings.request_timeout),
            )
        except requests.RequestException as exc:
            raise DocumentStoreError(f"Embedding request failed: {exc}") from exc
        if response.status_code != 200:
            raise DocumentStoreError(
                f"Embedding request failed ({response.status_code}): {response.text[:300]}"
            )
        result = response.json().get("data", [])
        vectors.extend(item["embedding"] for item in sorted(result, key=lambda item: item["index"]))
    if len(vectors) != len(texts):
        raise DocumentStoreError("Embedding provider returned an unexpected number of vectors.")
    return vectors


def make_document_id(source: str, filename: str, data: bytes, explicit_id: str | None) -> str:
    if explicit_id:
        return explicit_id
    seed = f"{source}|{filename}|{hashlib.sha256(data).hexdigest()}".encode("utf-8")
    return hashlib.sha256(seed).hexdigest()[:32]


def build_filters(args: argparse.Namespace) -> list[dict[str, Any]]:
    filters: list[dict[str, Any]] = []
    if args.notice_id:
        filters.append({"term": {"notice_id": args.notice_id}})
    if args.document_type:
        filters.append({"term": {"document_type": args.document_type}})
    return filters


def display_hits(hits: list[dict[str, Any]], json_output: bool, mode: str) -> None:
    output = []
    for hit in hits:
        source = hit.get("_source", {})
        highlighted = hit.get("highlight", {}).get("text", [])
        excerpt = highlighted[0] if highlighted else source.get("text", "")[:500]
        output.append(
            {
                "score": hit.get("_score"),
                "document_id": source.get("document_id"),
                "chunk_number": source.get("chunk_number"),
                "notice_id": source.get("notice_id"),
                "title": source.get("title"),
                "filename": source.get("filename"),
                "source": source.get("source"),
                "excerpt": excerpt,
            }
        )
    if json_output:
        print(json.dumps({"mode": mode, "shown": len(output), "results": output}, indent=2))
        return
    print(f"\nDocument search mode={mode}; results={len(output)}")
    for position, item in enumerate(output, 1):
        print(f"\n[{position}] {item['title'] or item['filename'] or '(untitled)'}")
        print(f"    Notice: {item['notice_id'] or '-'}  Chunk: {item['chunk_number']}")
        print(f"    Source: {item['source'] or '-'}")
        print(f"    Text:   {item['excerpt']}")
    print()


def reciprocal_rank_fusion(
    lexical_hits: list[dict[str, Any]], semantic_hits: list[dict[str, Any]], rank_constant: int = 60
) -> list[dict[str, Any]]:
    combined: dict[str, tuple[float, dict[str, Any]]] = {}
    for group in (lexical_hits, semantic_hits):
        for rank, hit in enumerate(group, 1):
            item_id = hit["_id"]
            score = 1.0 / (rank_constant + rank)
            previous = combined.get(item_id)
            if previous:
                combined[item_id] = (previous[0] + score, previous[1])
            else:
                combined[item_id] = (score, hit)
    ordered = sorted(combined.values(), key=lambda item: item[0], reverse=True)
    results = []
    for score, hit in ordered:
        fused = dict(hit)
        fused["_score"] = score
        results.append(fused)
    return results


def command_init(store: ElasticDocumentStore, args: argparse.Namespace) -> None:
    created = store.ensure_index()
    result = {"index": store.settings.index_name, "created": created}
    print(json.dumps(result, indent=2) if args.json else f"Index ready: {result}")


def command_status(store: ElasticDocumentStore, args: argparse.Namespace) -> None:
    result = store.health()
    print(json.dumps(result, indent=2) if args.json else "\n".join(f"{k}: {v}" for k, v in result.items()))


def command_ingest(store: ElasticDocumentStore, args: argparse.Namespace) -> None:
    provider = embedding_enabled(store.settings, args.embedding_provider)
    metadata = parse_metadata(args.metadata)
    indexed: list[dict[str, Any]] = []
    sources = gather_sources(args.sources)
    if not sources:
        raise DocumentStoreError("No supported documents found to ingest.")
    for source in sources:
        data, filename, content_type = load_source(source, store.settings)
        text = extract_text(data, filename, content_type)
        if not text:
            raise DocumentStoreError(
                f"No extractable text found in {filename}. Scanned PDFs require OCR before ingest."
            )
        pieces = chunk_text(text, store.settings.chunk_chars, store.settings.chunk_overlap)
        explicit_id = args.document_id if len(sources) == 1 else None
        document_id = make_document_id(source, filename, data, explicit_id)
        vectors = create_embeddings(store.settings, pieces, provider)
        digest = hashlib.sha256(data).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        chunks: list[dict[str, Any]] = []
        for number, piece in enumerate(pieces, 1):
            chunk: dict[str, Any] = {
                "document_id": document_id,
                "chunk_id": f"{document_id}:{number}",
                "chunk_number": number,
                "total_chunks": len(pieces),
                "notice_id": args.notice_id,
                "solicitation_number": args.solicitation_number,
                "title": args.title or filename,
                "document_type": args.document_type,
                "filename": filename,
                "source": source,
                "content_type": content_type,
                "content_sha256": digest,
                "ingested_at": now,
                "text": piece,
                "metadata": metadata,
            }
            if vectors:
                chunk["embedding"] = vectors[number - 1]
                chunk["embedding_model"] = store.settings.embedding_model
            chunks.append(chunk)
        store.replace_document_chunks(document_id, chunks)
        indexed.append(
            {
                "document_id": document_id,
                "filename": filename,
                "chunks": len(chunks),
                "characters": len(text),
                "embedded": bool(vectors),
            }
        )
    result = {"indexed": indexed, "index": store.settings.index_name}
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for document in indexed:
            print(
                f"Indexed {document['filename']}: {document['chunks']} chunks "
                f"(embedded={document['embedded']}, id={document['document_id']})"
            )


def command_search(store: ElasticDocumentStore, args: argparse.Namespace) -> None:
    store.ensure_index()
    filters = build_filters(args)
    if args.mode == "lexical":
        hits = store.lexical_search(args.query, filters, args.limit)
    else:
        provider = embedding_enabled(store.settings, args.embedding_provider)
        if provider == "none":
            raise DocumentStoreError(
                "Semantic and hybrid search require embeddings. Set EMBEDDING_PROVIDER=openai "
                "and OPENAI_API_KEY, then ingest embedded documents."
            )
        query_vector = create_embeddings(store.settings, [args.query], provider)[0]
        semantic_hits = store.semantic_search(query_vector, filters, args.limit)
        if args.mode == "semantic":
            hits = semantic_hits
        else:
            lexical_hits = store.lexical_search(args.query, filters, args.limit)
            hits = reciprocal_rank_fusion(lexical_hits, semantic_hits)[: args.limit]
    display_hits(hits, args.json, args.mode)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Store and search solicitation documents in Elasticsearch.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="Create the Elasticsearch document index if needed.")
    init.add_argument("--json", action="store_true")

    status = subparsers.add_parser("status", help="Show Elasticsearch connection and index status.")
    status.add_argument("--json", action="store_true")

    ingest = subparsers.add_parser("ingest", help="Extract and index files, directories, or HTTP(S) URLs.")
    ingest.add_argument("sources", nargs="+", help="Files, folders, or document URLs.")
    ingest.add_argument("--document-id", help="Stable ID for replacing one previously ingested document.")
    ingest.add_argument("--notice-id", default="", help="SAM.gov notice ID associated with the document.")
    ingest.add_argument("--solicitation-number", default="", help="Solicitation number associated with the document.")
    ingest.add_argument("--title", help="Opportunity or document title.")
    ingest.add_argument("--document-type", default="solicitation_attachment")
    ingest.add_argument("--metadata", action="append", default=[], help="Additional key=value metadata.")
    ingest.add_argument("--embedding-provider", choices=["none", "openai"])
    ingest.add_argument("--json", action="store_true")

    search = subparsers.add_parser("search", help="Search previously indexed solicitation documents.")
    search.add_argument("query", help="Question or search phrase.")
    search.add_argument("--mode", choices=["lexical", "semantic", "hybrid"], default="lexical")
    search.add_argument("--notice-id", help="Limit results to a SAM.gov notice ID.")
    search.add_argument("--document-type", help="Limit results to a document type.")
    search.add_argument("--limit", type=int, default=5)
    search.add_argument("--embedding-provider", choices=["none", "openai"])
    search.add_argument("--json", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = Settings.from_env()
    store = ElasticDocumentStore(settings)
    try:
        if args.command == "init":
            command_init(store, args)
        elif args.command == "status":
            command_status(store, args)
        elif args.command == "ingest":
            command_ingest(store, args)
        elif args.command == "search":
            command_search(store, args)
    except DocumentStoreError as exc:
        sys.exit(f"ERROR: {exc}")


if __name__ == "__main__":
    main()
