"""Tests for scripts/sap_opportunities.py."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "sap_opportunities.py"
SPEC = importlib.util.spec_from_file_location("sap_opportunities", MODULE_PATH)
sap = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = sap
SPEC.loader.exec_module(sap)


class SapOpportunityTests(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 5, 31)
        self.context = sap.SelectionContext(
            today=self.today,
            minimum_deadline=self.today + timedelta(days=3),
            value_column="award_amount",
            value_source="Award$ fallback",
        )

    def _row(self, **updates):
        row = {
            "notice_id": "notice-1",
            "title": "Small IT support RFQ",
            "sol_number": "SOL-1",
            "department": "Agency",
            "sub_tier": "Sub",
            "office": "Office",
            "posted_date": "2026-05-30",
            "type": "Combined Synopsis/Solicitation",
            "set_aside": "Total Small Business Set-Aside (FAR 19.5)",
            "set_aside_code": "SBA",
            "response_deadline": "2026-06-10T12:00:00-04:00",
            "naics_code": "541512",
            "classification_code": "D399",
            "pop_street": "",
            "pop_city": "Arlington",
            "pop_state": "VA",
            "pop_country": "USA",
            "active": "Yes",
            "link": "https://sam.gov/example",
            "selected_value": "",
        }
        row.update(updates)
        return row

    def _selected(self, *rows):
        selected, counts = sap.select_opportunities(rows, self.context)
        return selected, counts

    def test_null_value_is_retained_and_over_sat_is_excluded(self):
        null_value = self._row(notice_id="null", sol_number="NULL", selected_value="")
        small_value = self._row(notice_id="small", sol_number="SMALL", selected_value="$12,500")
        over_sat = self._row(notice_id="large", sol_number="LARGE", selected_value="350001")
        selected, counts = self._selected(null_value, small_value, over_sat)
        self.assertEqual([row.notice_id for row in selected], ["small", "null"])
        self.assertEqual(counts["over_sat"], 1)

    def test_set_aside_order_precedes_deadline_for_null_values(self):
        unrestricted = self._row(
            notice_id="unrestricted",
            sol_number="U",
            set_aside="",
            set_aside_code="",
            response_deadline="2026-06-05",
        )
        small_business = self._row(
            notice_id="small-business",
            sol_number="SB",
            response_deadline="2026-06-10",
        )
        selected, _ = self._selected(unrestricted, small_business)
        self.assertEqual([row.notice_id for row in selected], ["small-business", "unrestricted"])

    def test_deadline_notice_type_naics_and_restricted_setaside_are_hard_gates(self):
        rows = [
            self._row(notice_id="short", sol_number="1", response_deadline="2026-06-02"),
            self._row(notice_id="source", sol_number="2", type="Sources Sought"),
            self._row(notice_id="naics", sol_number="3", naics_code="561621"),
            self._row(notice_id="8a", sol_number="4", set_aside_code="8A", set_aside="8a Competed"),
        ]
        selected, counts = self._selected(*rows)
        self.assertEqual(selected, [])
        self.assertEqual(counts["inactive_or_short_runway"], 1)
        self.assertEqual(counts["notice_type"], 1)
        self.assertEqual(counts["naics"], 1)
        self.assertEqual(counts["set_aside"], 1)

    def test_psc_rule_allows_d_and_non_excluded_but_rejects_excluded_families(self):
        rows = [
            self._row(notice_id="d", sol_number="D", classification_code="D301"),
            self._row(notice_id="r", sol_number="R", classification_code="R499"),
            self._row(notice_id="c", sol_number="C", classification_code="C211"),
            self._row(notice_id="s", sol_number="S", classification_code="S201"),
            self._row(notice_id="y", sol_number="Y", classification_code="Y1AA"),
            self._row(notice_id="z", sol_number="Z", classification_code="Z2AA"),
        ]
        selected, counts = self._selected(*rows)
        self.assertEqual([row.notice_id for row in selected], ["d", "r"])
        self.assertEqual(counts["psc"], 4)

    def test_pop_rule_accepts_dmv_remote_and_domestic_blank_but_rejects_foreign(self):
        rows = [
            self._row(notice_id="md", sol_number="MD", pop_state="MD"),
            self._row(
                notice_id="remote",
                sol_number="REMOTE",
                pop_city="Remote",
                pop_state="",
                pop_country="",
            ),
            self._row(
                notice_id="blank",
                sol_number="BLANK",
                pop_city="",
                pop_state="",
                pop_country="USA",
            ),
            self._row(
                notice_id="foreign",
                sol_number="FOREIGN",
                pop_city="Oman",
                pop_state="",
                pop_country="OMN",
            ),
        ]
        selected, counts = self._selected(*rows)
        self.assertEqual([row.notice_id for row in selected], ["md", "remote", "blank"])
        self.assertEqual(counts["place_of_performance"], 1)

    def test_latest_amendment_copy_is_retained(self):
        old = self._row(notice_id="old", posted_date="2026-05-20")
        new = self._row(notice_id="new", posted_date="2026-05-30")
        selected, counts = self._selected(old, new)
        self.assertEqual([row.notice_id for row in selected], ["new"])
        self.assertEqual(counts["duplicates_removed"], 1)

    def test_value_column_prefers_true_estimate_then_award_fallback(self):
        self.assertEqual(sap._value_column({"estimated_value", "award_amount"}), ("estimated_value", "estimated_value"))
        self.assertEqual(sap._value_column({"award_amount"}), ("award_amount", "Award$ fallback"))
        self.assertEqual(sap._value_column(set()), (None, "unavailable"))

    def test_json_wrapped_sba_code_is_normalized(self):
        self.assertEqual(sap._normalize_set_aside_code('["SBA"]', ""), "SBA")


if __name__ == "__main__":
    unittest.main()
