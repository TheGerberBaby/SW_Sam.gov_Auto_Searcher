"""Tests for scripts/research_scan_publish.py."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

MODULE_PATH = SCRIPTS_DIR / "research_scan_publish.py"
SPEC = importlib.util.spec_from_file_location("research_scan_publish", MODULE_PATH)
publisher = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = publisher
SPEC.loader.exec_module(publisher)

import watchlist  # noqa: E402


class ResearchScanPublishTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "watchlist.db"

    def test_publish_scan_records_workbench_run(self):
        result = publisher.publish_scan(
            summary="Chat-requested handyman scan with one assess-now fit.",
            candidates_scanned=14,
            items=[
                {
                    "notice_id": "CHAT-1",
                    "title": "Small door repair",
                    "disposition": "assess now",
                    "supported_fit": "Small field-maintenance scope.",
                }
            ],
            db_path=self.db_path,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "ai_research")
        self.assertEqual(result["candidates_shown"], 1)

        store = watchlist.Store(self.db_path)
        run = store.get_digest_run(result["scan_id"])
        self.assertEqual(run["source"], "ai_research")
        self.assertEqual(run["candidates_scanned"], 14)
        self.assertIn("Small door repair", run["items_json"])

    def test_publish_scan_requires_title_without_local_mirror(self):
        with self.assertRaisesRegex(ValueError, "needs a title"):
            publisher.publish_scan(
                summary="Bad scan item.",
                items=[{"notice_id": "CHAT-2"}],
                db_path=self.db_path,
            )


if __name__ == "__main__":
    unittest.main()
