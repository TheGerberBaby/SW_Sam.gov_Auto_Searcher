import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
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
            pdf_extractor="pymupdf4llm",
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

    def test_pdf_extraction_uses_markdown_without_ocr(self):
        captured = {}

        class FakeDocument:
            def close(self):
                captured["closed"] = True

        def fake_open(**kwargs):
            captured["open"] = kwargs
            return FakeDocument()

        def fake_to_markdown(document, **kwargs):
            captured["to_markdown"] = kwargs
            self.assertIsInstance(document, FakeDocument)
            return "# Scope\n\nInstall card readers."

        with patch.dict(
            sys.modules,
            {
                "pymupdf": SimpleNamespace(open=fake_open),
                "pymupdf4llm": SimpleNamespace(to_markdown=fake_to_markdown),
            },
        ):
            text = document_store.extract_text(
                b"%PDF-1.7 content", "scope.pdf", "application/pdf"
            )

        self.assertEqual(text, "# Scope\n\nInstall card readers.")
        self.assertEqual(captured["open"], {"stream": b"%PDF-1.7 content", "filetype": "pdf"})
        self.assertFalse(captured["to_markdown"]["use_ocr"])
        self.assertFalse(captured["to_markdown"]["write_images"])
        self.assertTrue(captured["closed"])

    def test_markdown_command_writes_output_file(self):
        store = SimpleNamespace(settings=self.settings())
        with tempfile.TemporaryDirectory() as tmp_dir:
            with (
                patch.object(
                    document_store,
                    "load_source",
                    return_value=(b"%PDF-1.7 content", "Access Control Scope.pdf", "application/pdf"),
                ),
                patch.object(document_store, "extract_markdown", return_value="# Access Control"),
                redirect_stdout(io.StringIO()),
            ):
                document_store.command_markdown(
                    store,
                    SimpleNamespace(
                        sources=["https://example.test/access-control.pdf"],
                        output_dir=tmp_dir,
                        output=None,
                        json=True,
                    ),
                )
            output_path = Path(tmp_dir) / "Access-Control-Scope.md"
            self.assertEqual(output_path.read_text(encoding="utf-8"), "# Access Control\n")

    def test_pypdf_extractor_outputs_markdown_with_page_markers(self):
        class Page:
            def __init__(self, text):
                self.text = text

            def extract_text(self):
                return self.text

        class Reader:
            def __init__(self, stream):
                self.pages = [Page("First page"), Page("Second page")]

        with patch.dict(sys.modules, {"pypdf": SimpleNamespace(PdfReader=Reader)}):
            text = document_store.pdf_to_markdown(
                b"%PDF-1.7 content", "scope.pdf", "pypdf"
            )

        self.assertIn("<!-- page: 1 -->\n\nFirst page", text)
        self.assertIn("<!-- page: 2 -->\n\nSecond page", text)

    def test_public_ingest_marks_chunks_for_panel_transmission(self):
        class Store:
            settings = self.settings()

            def __init__(self):
                self.chunks = []

            def replace_document_chunks(self, document_id, chunks):
                self.chunks = chunks

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "public-sow.txt"
            path.write_text("Public scope and clearance requirements.", encoding="utf-8")
            store = Store()
            with redirect_stdout(io.StringIO()):
                document_store.command_ingest(
                    store,
                    SimpleNamespace(
                        sources=[str(path)],
                        document_id=None,
                        notice_id="NOTICE",
                        solicitation_number="SOL",
                        title="Public SOW",
                        document_type="solicitation_attachment",
                        metadata=[],
                        public=True,
                        embedding_provider=None,
                        json=True,
                    ),
                )
        self.assertEqual(store.chunks[0]["metadata"]["public"], "true")


if __name__ == "__main__":
    unittest.main()
