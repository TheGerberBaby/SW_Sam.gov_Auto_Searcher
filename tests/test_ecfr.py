"""Tests for scripts/ecfr.py (mocked HTTP)."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ecfr.py"
SPEC = importlib.util.spec_from_file_location("ecfr", MODULE_PATH)
ecfr = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = ecfr
SPEC.loader.exec_module(ecfr)


class FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._body


class ECFRTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._orig_cache = ecfr.CACHE_PATH
        ecfr.CACHE_PATH = Path(self.tmp.name) / "cache.json"

    def tearDown(self):
        ecfr.CACHE_PATH = self._orig_cache

    def test_strip_tags(self):
        self.assertEqual(ecfr._strip_tags("<strong>X</strong> Y"), "X Y")
        self.assertEqual(ecfr._strip_tags("plain"), "plain")

    def test_search_parses_hits(self):
        payload = {
            "results": [
                {
                    "hierarchy": {"title": "13", "part": "125", "section": "125.11"},
                    "headings": {
                        "section": "What definitions are important in <strong>SDVOSB</strong>?",
                    },
                }
            ]
        }
        with patch.object(ecfr.request, "urlopen",
                          return_value=FakeResponse(json.dumps(payload).encode("utf-8"))):
            hits = ecfr.search("SDVOSB", title=13, limit=5)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].title, "13")
        self.assertEqual(hits[0].part, "125")
        self.assertIn("SDVOSB", hits[0].heading)
        self.assertIn("§ 125.11", hits[0].citation)

    def test_get_section_strips_xml_and_returns_clause(self):
        xml = b"<section><heading>Heading X</heading><para>Body paragraph text.</para></section>"
        with patch.object(ecfr.request, "urlopen", return_value=FakeResponse(xml)):
            clause = ecfr.get_section(title=48, section="52.212-2")
        self.assertEqual(clause.title, 48)
        self.assertEqual(clause.section, "52.212-2")
        self.assertIn("Body paragraph text", clause.text)
        self.assertIn("48 CFR § 52.212-2", clause.citation)

    def test_get_section_raises_on_empty(self):
        with patch.object(ecfr.request, "urlopen", return_value=FakeResponse(b"")):
            with self.assertRaises(ecfr.ECFRError):
                ecfr.get_section(title=48, section="bogus.section")

    def test_http_error_raises(self):
        from urllib import error
        err = error.HTTPError("https://x", 500, "fail", {}, io.BytesIO(b""))
        with patch.object(ecfr.request, "urlopen", side_effect=err):
            with self.assertRaises(ecfr.ECFRError):
                ecfr.search("foo")


if __name__ == "__main__":
    unittest.main()
