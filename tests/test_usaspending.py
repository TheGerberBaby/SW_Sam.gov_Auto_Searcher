"""Tests for scripts/usaspending.py (mocked HTTP)."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "usaspending.py"
SPEC = importlib.util.spec_from_file_location("usaspending", MODULE_PATH)
usaspending = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = usaspending
SPEC.loader.exec_module(usaspending)


class FakeResponse:
    def __init__(self, data: dict):
        self._data = json.dumps(data).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._data


class USAspendingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._orig_cache = usaspending.CACHE_PATH
        usaspending.CACHE_PATH = Path(self.tmp.name) / "cache.json"

    def tearDown(self):
        usaspending.CACHE_PATH = self._orig_cache

    def test_flatten_code_handles_dict_and_str(self):
        self.assertEqual(usaspending._flatten_code({"code": "541512", "description": "X"}), "541512 (X)")
        self.assertEqual(usaspending._flatten_code("541512"), "541512")
        self.assertIsNone(usaspending._flatten_code(None))

    def test_find_incumbents_parses_rows(self):
        fake_body = {
            "results": [
                {
                    "Award ID": "AID-1",
                    "Recipient Name": "ACME CORP",
                    "Recipient UEI": "ABC123",
                    "Award Amount": 250000,
                    "Description": "Elastic services",
                    "NAICS": {"code": "541512", "description": "Computer Systems Design Services"},
                    "PSC": "D399",
                    "Awarding Agency": "DoD",
                    "Awarding Sub Agency": "Army",
                    "Start Date": "2024-01-01",
                    "End Date": "2025-01-01",
                    "Place of Performance State Code": "VA",
                },
            ]
        }
        with patch.object(usaspending.request, "urlopen", return_value=FakeResponse(fake_body)):
            awards = usaspending.find_incumbents(naics="541512", limit=5)
        self.assertEqual(len(awards), 1)
        self.assertEqual(awards[0].recipient_name, "ACME CORP")
        self.assertEqual(awards[0].naics, "541512 (Computer Systems Design Services)")
        self.assertEqual(awards[0].amount, 250000.0)

    def test_award_history_requires_recipient(self):
        with self.assertRaises(ValueError):
            usaspending.award_history()

    def test_cache_round_trip(self):
        fake_body = {"results": []}
        with patch.object(usaspending.request, "urlopen", return_value=FakeResponse(fake_body)) as mock_open:
            usaspending.find_incumbents(naics="541512", limit=5)
            # Second call within TTL should hit the cache (no new urlopen)
            usaspending.find_incumbents(naics="541512", limit=5)
        self.assertEqual(mock_open.call_count, 1)

    def test_http_error_raises_usaspending_error(self):
        from urllib import error
        err = error.HTTPError("https://x", 500, "bad", {}, io.BytesIO(b"server explosion"))
        with patch.object(usaspending.request, "urlopen", side_effect=err):
            with self.assertRaises(usaspending.USAspendingError):
                usaspending.find_incumbents(naics="541512", limit=1)


if __name__ == "__main__":
    unittest.main()
