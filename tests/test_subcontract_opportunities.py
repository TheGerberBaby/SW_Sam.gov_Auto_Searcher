"""Tests for scripts/subcontract_opportunities.py."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import date
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
MODULE_PATH = SCRIPTS_DIR / "subcontract_opportunities.py"
SPEC = importlib.util.spec_from_file_location("subcontract_opportunities", MODULE_PATH)
subs = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = subs
SPEC.loader.exec_module(subs)


class SubcontractOpportunityTests(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 6, 1)

    def _row(self, **updates):
        row = {
            "notice_id": "notice-1",
            "title": "Commercial janitorial cleaning service",
            "sol_number": "SOL-1",
            "department": "Agency",
            "posted_date": "2026-05-31",
            "type": "Combined Synopsis/Solicitation",
            "set_aside": "Total Small Business Set-Aside (FAR 19.5)",
            "set_aside_code": "SBA",
            "response_deadline": "2026-06-15T12:00:00-04:00",
            "naics_code": "561720",
            "pop_city": "Alexandria",
            "pop_state": "VA",
            "pop_country": "USA",
            "active": "Yes",
            "award_number": "",
            "awardee": "",
            "link": "https://sam.gov/example",
            "description": "Recurring custodial cleaning service.",
        }
        row.update(updates)
        return row

    def test_sourceable_small_business_service_is_assess_now(self):
        selected, _ = subs.select_opportunities([self._row()], self.today)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].disposition, "assess now")
        self.assertIn("swcb.py vendors --naics 561720", selected[0].vendor_command)

    def test_restricted_status_set_aside_is_excluded(self):
        selected, counts = subs.select_opportunities(
            [self._row(set_aside_code="SDVOSBC", set_aside="SDVOSB Set Aside")],
            self.today,
        )
        self.assertEqual(selected, [])
        self.assertEqual(counts["restricted_set_aside"], 1)

    def test_disguised_sources_sought_is_excluded(self):
        selected, counts = subs.select_opportunities(
            [self._row(description="This is a sources sought notice for market research.")],
            self.today,
        )
        self.assertEqual(selected, [])
        self.assertEqual(counts["not_direct_buy"], 1)

    def test_foreign_and_awarded_notices_are_excluded(self):
        rows = [
            self._row(notice_id="foreign", sol_number="FOREIGN", pop_country="DEU"),
            self._row(notice_id="award", sol_number="AWARD", award_number="123"),
        ]
        selected, counts = subs.select_opportunities(rows, self.today)
        self.assertEqual(selected, [])
        self.assertEqual(counts["foreign"], 1)
        self.assertEqual(counts["awarded"], 1)

    def test_risk_terms_flag_manual_review(self):
        selected, _ = subs.select_opportunities(
            [
                self._row(
                    title="Fire alarm construction and renovation",
                    naics_code="561621",
                    description="Brand name only Lenel security system with NFPA code compliance.",
                )
            ],
            self.today,
        )
        self.assertEqual(selected[0].disposition, "manual review")
        self.assertIn("life-safety / fire-system review", selected[0].risk_flags)
        self.assertIn("OEM / proprietary-system review", selected[0].risk_flags)

    def test_conditional_installation_lane_requires_manual_review(self):
        selected, _ = subs.select_opportunities(
            [
                self._row(
                    title="Access Control and Video Monitoring Systems",
                    naics_code="561621",
                    description="Install access control and camera system.",
                )
            ],
            self.today,
        )
        self.assertEqual(selected[0].disposition, "manual review")

    def test_latest_amendment_copy_is_retained(self):
        old = self._row(notice_id="old", posted_date="2026-05-20")
        new = self._row(notice_id="new", posted_date="2026-05-31")
        selected, counts = subs.select_opportunities([old, new], self.today)
        self.assertEqual([opportunity.notice_id for opportunity in selected], ["new"])
        self.assertEqual(counts["duplicates_removed"], 1)

    def test_short_runway_and_unknown_naics_are_excluded(self):
        rows = [
            self._row(notice_id="short", sol_number="SHORT", response_deadline="2026-06-03"),
            self._row(notice_id="unknown", sol_number="UNKNOWN", naics_code="999999"),
        ]
        selected, counts = subs.select_opportunities(rows, self.today)
        self.assertEqual(selected, [])
        self.assertEqual(counts["inactive_or_short_runway"], 1)
        self.assertEqual(counts["outside_sourcing_profiles"], 1)

    def test_broad_naics_without_lane_scope_is_excluded(self):
        selected, counts = subs.select_opportunities(
            [
                self._row(
                    title="CO2 Pool Chemicals",
                    naics_code="561790",
                    description="Supply pool chemicals.",
                )
            ],
            self.today,
        )
        self.assertEqual(selected, [])
        self.assertEqual(counts["scope_mismatch"], 1)

    def test_json_wrapped_sba_code_is_normalized(self):
        self.assertEqual(subs._normalize_set_aside_code('["SBA"]', ""), "SBA")


if __name__ == "__main__":
    unittest.main()
