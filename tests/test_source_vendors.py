"""Tests for scripts/source_vendors.py."""

from __future__ import annotations

import importlib.util
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "source_vendors.py"
SPEC = importlib.util.spec_from_file_location("source_vendors", MODULE_PATH)
source_vendors = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = source_vendors
SPEC.loader.exec_module(source_vendors)


class SourceVendorTests(unittest.TestCase):
    def test_resolve_known_profile(self):
        profile = source_vendors.resolve_profile("561621", None)
        self.assertEqual(profile["label"], "security systems / access-control installation")
        self.assertIn("commercial security camera access control installer", profile["terms"])

    def test_free_text_prepends_known_profile_search_term(self):
        profile = source_vendors.resolve_profile("238210", "fiber splicing")
        self.assertEqual(profile["terms"][0], "fiber splicing")
        self.assertIn("structured cabling low voltage contractor", profile["terms"])

    def test_unknown_naics_uses_free_text_generic_profile(self):
        profile = source_vendors.resolve_profile("999999", "tree removal")
        self.assertEqual(profile["label"], "tree removal")
        self.assertEqual(profile["terms"], ["tree removal"])

    def test_call_script_uses_operator_place_due_and_qualifiers(self):
        script = source_vendors.build_call_script(
            "Jeremy",
            "structured cabling",
            "Dover, DE",
            "29 Jun 2026",
            ["install Cat6", "provide test results"],
        )
        self.assertIn("my name's Jeremy", script)
        self.assertIn("structured cabling contract out by Dover, DE due by 29 Jun 2026", script)
        self.assertIn("install Cat6, and provide test results", script)

    def test_email_asks_add_standard_teaming_questions(self):
        asks = source_vendors.build_email_asks({"asks": ["Can you quote the work?"]})
        self.assertEqual(asks[0], "Can you quote the work?")
        self.assertTrue(any("Payment terms" in ask for ask in asks))
        self.assertTrue(any("size standard" in ask for ask in asks))

    def test_search_places_caps_request_and_excludes_closed_businesses(self):
        response = SimpleNamespace(
            status_code=200,
            text="",
            json=lambda: {
                "places": [
                    {
                        "displayName": {"text": "Open Installer"},
                        "nationalPhoneNumber": "555-0100",
                        "businessStatus": "OPERATIONAL",
                    },
                    {
                        "displayName": {"text": "Closed Installer"},
                        "nationalPhoneNumber": "555-0101",
                        "businessStatus": "CLOSED_PERMANENTLY",
                    },
                ]
            },
        )
        with patch.object(source_vendors.requests, "post", return_value=response) as post:
            vendors = source_vendors.search_places("installer near Dover, DE", "key", 100)
        self.assertEqual([vendor["name"] for vendor in vendors], ["Open Installer"])
        self.assertEqual(post.call_args.kwargs["json"]["maxResultCount"], 20)

    def test_search_places_reports_auth_failure(self):
        response = SimpleNamespace(status_code=403, text="denied")
        with patch.object(source_vendors.requests, "post", return_value=response):
            with self.assertRaisesRegex(SystemExit, "check GOOGLE_PLACES_API_KEY"):
                source_vendors.search_places("installer near Dover, DE", "bad-key", 6)

    def test_dedupe_removes_duplicates_and_blank_names(self):
        vendors = [
            {"name": "Installer One", "phone": "555-0100"},
            {"name": " installer one ", "phone": "555-0100"},
            {"name": "", "phone": "555-0101"},
            {"name": "Installer Two", "phone": "555-0102"},
        ]
        result = source_vendors.dedupe(vendors)
        self.assertEqual([vendor["name"] for vendor in result], ["Installer One", "Installer Two"])

    def test_search_places_clamps_minimum_request_size(self):
        response = SimpleNamespace(status_code=200, text="", json=lambda: {"places": []})
        with patch.object(source_vendors.requests, "post", return_value=response) as post:
            source_vendors.search_places("installer near Dover, DE", "key", -5)
        self.assertEqual(post.call_args.kwargs["json"]["maxResultCount"], 1)

    def test_script_only_runs_without_places_key(self):
        argv = [
            "source_vendors.py",
            "--naics",
            "561790",
            "--place",
            "Dover AFB, DE",
            "--script-only",
            "--json",
        ]
        with patch.object(sys, "argv", argv), patch.dict(os.environ, {}, clear=True):
            with redirect_stdout(io.StringIO()) as output:
                source_vendors.main()
        self.assertIn('"discovery_skipped": true', output.getvalue())

    def test_generate_package_returns_fresh_leads_and_scripts(self):
        with patch.object(
            source_vendors,
            "search_places",
            return_value=[{"name": "Dover Hood Co", "phone": "302-555-0100"}],
        ) as search:
            package = source_vendors.generate_vendor_package(
                naics="561790",
                place="Dover AFB, DE",
                due="29 Jun 2026",
                api_key="places-key",
                max_results=5,
            )
        self.assertFalse(package["discovery_skipped"])
        self.assertEqual(package["vendors"][0]["name"], "Dover Hood Co")
        self.assertEqual(search.call_count, 2)
        self.assertIn("my name's Jeremy", package["call_script"])
        self.assertIn("Subcontract quote request", package["email_draft"])

    def test_generate_package_soft_falls_back_to_scripts_without_key(self):
        package = source_vendors.generate_vendor_package(
            naics="561790",
            place="Dover AFB, DE",
            api_key="",
            allow_script_fallback=True,
        )
        self.assertTrue(package["discovery_skipped"])
        self.assertEqual(package["vendors"], [])
        self.assertIn("GOOGLE_PLACES_API_KEY", package["discovery_error"])
        self.assertIn("kitchen hood and exhaust cleaning", package["call_script"])


if __name__ == "__main__":
    unittest.main()
