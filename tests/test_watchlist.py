"""Tests for scripts/watchlist.py."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "watchlist.py"
SPEC = importlib.util.spec_from_file_location("watchlist", MODULE_PATH)
watchlist = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = watchlist
SPEC.loader.exec_module(watchlist)


class WatchlistTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "watchlist.db"
        self.store = watchlist.Store(self.db_path)

    def _opp(self, notice_id="N-1", title="Elastic services") -> dict:
        return {
            "notice_id": notice_id,
            "title": title,
            "sol_number": "SOL-1",
            "department": "DoD",
            "naics_code": "541512",
            "set_aside": "Total Small Business",
            "response_deadline": "2026-06-30",
            "link": "https://sam.gov/notice/N-1",
        }

    def test_add_and_list_watchlist(self):
        entry = self.store.add_to_watchlist(self._opp())
        self.assertEqual(entry.status, "tracking")
        entries = self.store.list_watchlist()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].notice_id, "N-1")

    def test_add_twice_updates_existing(self):
        self.store.add_to_watchlist(self._opp(), status="tracking")
        entry = self.store.add_to_watchlist(self._opp(), status="assessing")
        self.assertEqual(entry.status, "assessing")
        events = self.store.events("N-1")
        self.assertTrue(any(e["event_type"] == "status_changed" for e in events))

    def test_update_status_records_event(self):
        self.store.add_to_watchlist(self._opp())
        entry = self.store.update_status("N-1", "pursuing", note="bid in progress")
        self.assertEqual(entry.status, "pursuing")
        events = self.store.events("N-1")
        self.assertTrue(any("bid in progress" in (e["detail"] or "") for e in events))

    def test_invalid_status_raises(self):
        self.store.add_to_watchlist(self._opp())
        with self.assertRaises(ValueError):
            self.store.update_status("N-1", "bogus-status")

    def test_remove_watchlist_entry(self):
        self.store.add_to_watchlist(self._opp())
        self.assertTrue(self.store.remove_from_watchlist("N-1"))
        self.assertFalse(self.store.remove_from_watchlist("N-1"))
        self.assertEqual(self.store.list_watchlist(), [])

    def test_add_note_appends(self):
        self.store.add_to_watchlist(self._opp())
        self.store.add_note("N-1", "first note")
        self.store.add_note("N-1", "second note")
        entry = self.store.get_entry("N-1")
        self.assertIn("first note", entry.notes or "")
        self.assertIn("second note", entry.notes or "")

    def test_saved_search_roundtrip(self):
        saved = self.store.save_search(
            "elastic-weekly",
            {"keyword": "Elasticsearch", "days": 7},
            description="weekly check",
            profile="elastic_only",
            min_score=3,
        )
        self.assertEqual(saved.profile, "elastic_only")
        self.assertEqual(saved.min_score, 3)
        fetched = self.store.get_saved_search("elastic-weekly")
        self.assertEqual(fetched.filters["keyword"], "Elasticsearch")
        # upsert keeps name unique
        self.store.save_search("elastic-weekly", {"keyword": "Kibana"}, profile="elastic_only")
        again = self.store.get_saved_search("elastic-weekly")
        self.assertEqual(again.filters["keyword"], "Kibana")
        self.assertTrue(self.store.delete_saved_search("elastic-weekly"))

    def test_digest_run_record(self):
        run_id = self.store.record_digest_run(
            profile="technical_services",
            candidates_scanned=100,
            candidates_shown=4,
            report_path="data/digests/x.html",
            summary="ok",
        )
        self.assertIsInstance(run_id, int)
        runs = self.store.list_digest_runs(limit=5)
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["candidates_shown"], 4)


if __name__ == "__main__":
    unittest.main()
