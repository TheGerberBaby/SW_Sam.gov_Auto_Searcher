"""Tests for scripts/vendor_jobs.py."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import vendor_jobs  # noqa: E402


class VendorJobTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.db_path = root / "contracts.db"
        self.queue_dir = root / "jobs"
        self.reports_dir = root / "reports"
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE opportunities (
                    notice_id TEXT, title TEXT, sol_number TEXT, department TEXT,
                    sub_tier TEXT, posted_date TEXT, type TEXT, set_aside TEXT,
                    set_aside_code TEXT, response_deadline TEXT, naics_code TEXT,
                    pop_city TEXT, pop_state TEXT, active TEXT, link TEXT,
                    description TEXT
                )
                """
            )
            conn.execute(
                """
                INSERT INTO opportunities VALUES (
                    'N-1', 'Kitchen Hoods and Ducts Cleaning', 'FAKE-Q-1',
                    'Department of the Air Force', '', '2026-06-01',
                    'Solicitation', 'Total Small Business', 'SBA', '2026-06-29',
                    '561790', 'Dover AFB', 'DE', 'Yes',
                    'https://sam.gov/notice/N-1', 'Recurring hood and dryer duct cleaning'
                )
                """
            )

    def _create(self) -> dict:
        return vendor_jobs.create_sourcing_job(
            {"notice_id": "N-1"},
            api_key="",
            db_path=self.db_path,
            queue_dir=self.queue_dir,
            reports_dir=self.reports_dir,
        )

    def test_create_job_enriches_from_mirror_and_writes_report(self):
        job = self._create()
        self.assertEqual(job["status"], "queued_for_codex")
        self.assertEqual(job["opportunity"]["sol_number"], "FAKE-Q-1")
        self.assertEqual(job["package"]["place"], "Dover AFB, DE")
        self.assertTrue(job["package"]["discovery_skipped"])
        self.assertIn("GOOGLE_PLACES_API_KEY", job["package"]["discovery_error"])
        report = Path(job["report_path"])
        self.assertTrue(report.is_file())
        text = report.read_text(encoding="utf-8")
        self.assertIn("Contracting-Officer Question Draft", text)
        self.assertIn("Codex Research Handoff", text)
        self.assertTrue((self.queue_dir / f"{job['job_id']}.json").is_file())

    def test_list_get_and_complete_job(self):
        job = self._create()
        listed = vendor_jobs.list_sourcing_jobs(queue_dir=self.queue_dir)
        self.assertEqual([item["job_id"] for item in listed], [job["job_id"]])
        fetched = vendor_jobs.get_sourcing_job(job["job_id"], queue_dir=self.queue_dir)
        self.assertEqual(fetched["opportunity"]["notice_id"], "N-1")
        completed = vendor_jobs.complete_sourcing_job(
            job["job_id"],
            "# Final sourced report\n",
            queue_dir=self.queue_dir,
            reports_dir=self.reports_dir,
        )
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(
            (self.reports_dir / job["report_filename"]).read_text(encoding="utf-8"),
            "# Final sourced report\n",
        )
        self.assertEqual(
            vendor_jobs.list_sourcing_jobs(status="queued_for_codex", queue_dir=self.queue_dir),
            [],
        )

    def test_unknown_naics_uses_opportunity_title_as_service(self):
        job = vendor_jobs.create_sourcing_job(
            {
                "notice_id": "N-2",
                "title": "Tree removal",
                "naics_code": "999999",
                "pop_city": "Accokeek",
                "pop_state": "MD",
            },
            api_key="",
            db_path=self.db_path,
            queue_dir=self.queue_dir,
            reports_dir=self.reports_dir,
        )
        self.assertEqual(job["package"]["service_label"], "Tree removal")
        self.assertEqual(job["package"]["queries"], ["Tree removal near Accokeek, MD"])


if __name__ == "__main__":
    unittest.main()
