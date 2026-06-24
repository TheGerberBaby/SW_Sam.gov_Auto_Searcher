"""Tests for scripts/digest.py rendering (DB-independent paths)."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))


def _import(name: str):
    path = SCRIPT_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


scoring = _import("scoring")
digest = _import("digest")


class DigestRenderTests(unittest.TestCase):
    def setUp(self):
        self.generated_at = datetime(2026, 5, 28, 9, 0, tzinfo=ZoneInfo("America/New_York"))

    def _scored(self):
        opp = {
            "notice_id": "DEMO-1",
            "title": "Security camera and access control installation",
            "description": "Install CCTV cameras, card readers, and Cat6 cabling.",
            "naics_code": "561621",
            "set_aside_code": "SBA",
            "set_aside": "Total Small Business",
            "response_deadline": "2026-06-30",
            "active": "Yes",
            "type": "Solicitation",
            "department": "DoD",
            "sub_tier": "Army",
            "posted_date": "2026-05-27",
            "link": "https://sam.gov/notice/DEMO-1",
        }
        return [scoring.score_opportunity(opp, today=self.generated_at.date())], {opp["notice_id"]: opp}

    def test_markdown_renders_title_and_score(self):
        scored, opps = self._scored()
        md = digest.render_markdown("technical_services", 3, 2, scored, opps, self.generated_at)
        self.assertIn("# SAM.gov Daily Digest", md)
        self.assertIn("Security camera and access control installation", md)
        self.assertIn("DEMO-1", md)
        self.assertIn("Electronic Security / Cameras / Access Control", md)

    def test_html_renders_valid_document(self):
        scored, opps = self._scored()
        html_doc = digest.render_html("technical_services", 3, 2, scored, opps, self.generated_at)
        self.assertTrue(html_doc.startswith("<!DOCTYPE html>"))
        self.assertIn("Security camera and access control installation", html_doc)
        self.assertIn("badge", html_doc)
        self.assertIn("STRONG", html_doc.upper())

    def test_empty_scored_renders_empty_state(self):
        md = digest.render_markdown("technical_services", 3, 5, [], {}, self.generated_at)
        self.assertIn("No opportunities cleared the threshold", md)
        html_doc = digest.render_html("technical_services", 3, 5, [], {}, self.generated_at)
        self.assertIn("No opportunities cleared the threshold", html_doc)


if __name__ == "__main__":
    unittest.main()
