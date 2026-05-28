import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "document_store.py"
SPEC = importlib.util.spec_from_file_location("document_store", MODULE_PATH)
document_store = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = document_store
SPEC.loader.exec_module(document_store)


class DocumentStoreTests(unittest.TestCase):
    def settings(self):
        return document_store.Settings(
            elasticsearch_url="http://localhost:9200",
            index_name="test_documents",
            chunk_chars=3500,
            chunk_overlap=350,
            max_document_bytes=1024 * 1024,
            request_timeout=10,
            embedding_provider="none",
            embedding_model="test",
            embedding_dimensions=3,
            openai_api_key=None,
            elasticsearch_api_key=None,
            elasticsearch_username=None,
            elasticsearch_password=None,
        )

    def test_normalize_text_removes_noise_and_preserves_paragraphs(self):
        value = "one\t two\n\n\n\nthree\x00 four"
        self.assertEqual(document_store.normalize_text(value), "one two\n\nthree four")

    def test_chunk_text_overlaps_long_content(self):
        text = ("Requirement sentence. " * 100).strip()
        chunks = document_store.chunk_text(text, max_chars=300, overlap=40)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(chunk for chunk in chunks))
        self.assertLessEqual(max(len(chunk) for chunk in chunks), 300)

    def test_parse_metadata_rejects_missing_separator(self):
        with self.assertRaises(document_store.DocumentStoreError):
            document_store.parse_metadata(["invalid"])

    def test_reciprocal_rank_fusion_promotes_shared_hits(self):
        lexical = [{"_id": "a"}, {"_id": "b"}]
        semantic = [{"_id": "b"}, {"_id": "c"}]
        fused = document_store.reciprocal_rank_fusion(lexical, semantic)
        self.assertEqual(fused[0]["_id"], "b")

    def test_load_source_accepts_absolute_windows_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "scope.txt"
            path.write_text("door repair requirements", encoding="utf-8")
            data, filename, content_type = document_store.load_source(
                str(path), self.settings()
            )
        self.assertEqual(data, b"door repair requirements")
        self.assertEqual(filename, "scope.txt")
        self.assertEqual(content_type, "text/plain")

    def test_load_source_uses_download_content_disposition_filename(self):
        class Response:
            headers = {
                "Content-Type": "application/octet-stream",
                "Content-Disposition": "attachment; filename=Sta+NOLA+Door+Scope+of+Work.pdf",
            }

            def raise_for_status(self):
                return None

            def iter_content(self, chunk_size):
                return iter([b"%PDF-1.7 content"])

        with patch.object(document_store.requests, "get", return_value=Response()):
            data, filename, content_type = document_store.load_source(
                "https://sam.gov/api/prod/opps/v3/opportunities/id/resources/files/id/download",
                self.settings(),
            )
        self.assertEqual(data, b"%PDF-1.7 content")
        self.assertEqual(filename, "Sta NOLA Door Scope of Work.pdf")
        self.assertEqual(content_type, "application/octet-stream")

    def test_pdf_signature_recognizes_octet_stream_download(self):
        self.assertTrue(
            document_store._is_pdf(
                b"%PDF-1.7 data", "download", "application/octet-stream"
            )
        )


if __name__ == "__main__":
    unittest.main()
