"""Tests for scripts/scoring.py."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "scoring.py"
SPEC = importlib.util.spec_from_file_location("scoring", MODULE_PATH)
scoring = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = scoring
SPEC.loader.exec_module(scoring)


class ScoringTests(unittest.TestCase):
    def _today(self) -> date:
        return date(2026, 5, 28)

    def _opp(self, **kwargs):
        base = {
            "notice_id": "TEST-1",
            "title": "",
            "description": "",
            "naics_code": "",
            "set_aside_code": "",
            "set_aside": "",
            "type": "Solicitation",
            "response_deadline": "",
            "active": "Yes",
        }
        base.update(kwargs)
        return base

    def test_tier1_keyword_in_title_drives_strong_band(self):
        opp = self._opp(
            title="Security camera and access control installation",
            description="Install CCTV cameras, Cat6 cabling, and card readers.",
            naics_code="561621",
            set_aside_code="SBA",
            response_deadline=(self._today() + timedelta(days=21)).isoformat(),
        )
        result = scoring.score_opportunity(opp, today=self._today())
        self.assertGreaterEqual(result.score, 5)
        self.assertEqual(result.band, "strong")
        self.assertIn("electronic_security", result.lanes)
        self.assertIn("cabling_fiber", result.lanes)
        kinds = [r.kind for r in result.reasons]
        self.assertIn("tier1_keyword", kinds)
        self.assertIn("set_aside", kinds)

    def test_construction_keyword_alone_is_rejected(self):
        opp = self._opp(
            title="Roofing replacement at federal facility",
            description="Construction services required, asphalt and demolition.",
            response_deadline=(self._today() + timedelta(days=21)).isoformat(),
        )
        result = scoring.score_opportunity(opp, profile="elastic_only", today=self._today())
        self.assertEqual(result.band, "reject")
        self.assertTrue(any(r.kind == "exclusion" for r in result.reasons))

    def test_expired_deadline_penalizes_score(self):
        opp = self._opp(
            title="OpenSearch implementation",
            response_deadline=(self._today() - timedelta(days=2)).isoformat(),
        )
        result = scoring.score_opportunity(opp, today=self._today())
        self.assertTrue(any(r.kind == "deadline_expired" for r in result.reasons))

    def test_siem_with_siemens_triggers_false_positive_guard(self):
        opp = self._opp(
            title="SIEM equipment parts catalog",
            description="Siemens-branded controllers and accessories.",
        )
        result = scoring.score_opportunity(opp, profile="elastic_only", today=self._today())
        kinds = [r.kind for r in result.reasons]
        self.assertIn("false_positive_guard", kinds)

    def test_elastic_only_profile_retains_legacy_specialist_lane(self):
        opp = self._opp(
            title="Elasticsearch platform engineering",
            description="Kibana dashboards and Logstash ingestion pipeline configuration.",
            response_deadline=(self._today() + timedelta(days=10)).isoformat(),
        )
        field_default = scoring.score_opportunity(opp, profile="technical_services", today=self._today())
        narrow = scoring.score_opportunity(opp, profile="elastic_only", today=self._today())
        self.assertGreater(narrow.score, field_default.score)
        self.assertIn("elastic_search", narrow.lanes)
        self.assertNotIn("elastic_search", field_default.lanes)

    def test_vtc_keyword_lands_in_network_vtc_lane(self):
        opp = self._opp(
            title="VTC integration and unified communications engineering",
            description="Video teleconference room design and AV over IP.",
            response_deadline=(self._today() + timedelta(days=14)).isoformat(),
        )
        result = scoring.score_opportunity(opp, today=self._today())
        self.assertIn("network_vtc", result.lanes)

    def test_field_keyword_without_execution_scope_is_demoted(self):
        opp = self._opp(
            title="Cybersecurity class vouchers",
            description="Training includes a video surveillance assessment module.",
            set_aside_code="SBA",
        )
        result = scoring.score_opportunity(opp, today=self._today())
        self.assertEqual(result.band, "reject")
        self.assertTrue(any(r.kind == "field_scope_missing" for r in result.reasons))

    def test_sole_source_install_notice_is_rejected(self):
        opp = self._opp(
            title="Sole Source CCTV Install",
            description="Install access control and intrusion detection equipment.",
        )
        result = scoring.score_opportunity(opp, today=self._today())
        self.assertEqual(result.band, "reject")
        self.assertTrue(any(r.kind == "prohibited_notice" for r in result.reasons))

    def test_resell_signal_penalizes(self):
        opp = self._opp(
            title="Software license renewal — brand name only",
            description="Procurement of subscription renewal, manufacturer warranty required.",
            response_deadline=(self._today() + timedelta(days=14)).isoformat(),
        )
        result = scoring.score_opportunity(opp, today=self._today())
        self.assertTrue(any(r.kind == "resell_signal" for r in result.reasons))

    def test_unknown_profile_raises(self):
        with self.assertRaises(ValueError):
            scoring.score_opportunity(self._opp(), profile="bogus")

    def test_bulk_score_returns_list(self):
        opps = [
            self._opp(notice_id="A", title="Structured cabling installation"),
            self._opp(notice_id="B", title="Lawn care"),
        ]
        results = scoring.bulk_score(opps, today=self._today())
        self.assertEqual(len(results), 2)
        self.assertGreater(results[0].score, results[1].score)


if __name__ == "__main__":
    unittest.main()
