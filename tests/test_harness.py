"""Tests for scripts/harness.py."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "harness.py"
SPEC = importlib.util.spec_from_file_location("harness", MODULE_PATH)
harness = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = harness
SPEC.loader.exec_module(harness)


class HarnessMetricsTests(unittest.TestCase):
    def test_score_to_label_thresholds(self):
        self.assertEqual(harness.score_to_label(9), "fit")
        self.assertEqual(harness.score_to_label(5), "fit")
        self.assertEqual(harness.score_to_label(4), "monitor")
        self.assertEqual(harness.score_to_label(2), "monitor")
        self.assertEqual(harness.score_to_label(1), "reject")
        self.assertEqual(harness.score_to_label(-3), "reject")

    def test_per_class_perfect_predictions(self):
        preds = [("fit", "fit"), ("monitor", "monitor"), ("reject", "reject"),
                 ("reject", "reject"), ("fit", "fit")]
        per_class = harness._per_class(preds)
        for c in per_class:
            self.assertEqual(c.f1, 1.0 if c.support else 0.0)

    def test_macro_f1_partial(self):
        preds = [("fit", "fit"), ("fit", "monitor"),
                 ("monitor", "monitor"), ("monitor", "monitor"),
                 ("reject", "reject")]
        per_class = harness._per_class(preds)
        macro = harness._macro_f1(per_class)
        self.assertTrue(0.0 < macro < 1.0)

    def test_cohen_kappa_perfect_is_one(self):
        preds = [("fit", "fit"), ("monitor", "monitor"), ("reject", "reject")] * 3
        self.assertAlmostEqual(harness._cohen_kappa(preds), 1.0)

    def test_cohen_kappa_chance_is_zero(self):
        # Chance-level predictions (every truth/pred pair distinct from others)
        preds = [("fit", "monitor"), ("monitor", "reject"), ("reject", "fit")] * 3
        kappa = harness._cohen_kappa(preds)
        self.assertLess(kappa, 0.1)

    def test_confusion_counts_correctly(self):
        preds = [("fit", "fit"), ("fit", "monitor"), ("monitor", "monitor")]
        m = harness._confusion(preds)
        self.assertEqual(m["fit"]["fit"], 1)
        self.assertEqual(m["fit"]["monitor"], 1)
        self.assertEqual(m["monitor"]["monitor"], 1)
        self.assertEqual(m["reject"]["reject"], 0)


class HarnessGoldIOTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._orig_dir = harness.GOLD_DIR
        harness.GOLD_DIR = Path(self.tmp.name)

    def tearDown(self):
        harness.GOLD_DIR = self._orig_dir

    def test_append_and_load_gold(self):
        harness.append_gold("acc", "n-1", "fit", note="real fit")
        harness.append_gold("acc", "n-2", "reject", note="commodity")
        # Re-labeling overwrites in place, doesn't duplicate
        harness.append_gold("acc", "n-1", "monitor", note="moved to monitor")
        rows = harness.load_gold("acc")
        labels = {r.notice_id: r.label for r in rows}
        self.assertEqual(labels, {"n-1": "monitor", "n-2": "reject"})

    def test_append_rejects_bad_label(self):
        with self.assertRaises(ValueError):
            harness.append_gold("acc", "n-x", "bogus-label")


if __name__ == "__main__":
    unittest.main()
