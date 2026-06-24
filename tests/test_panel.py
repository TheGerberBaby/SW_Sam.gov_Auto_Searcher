"""Tests for the independent opportunity-evaluation panel."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from panel.aggregate import aggregate
from panel.experts import PublicEvidenceError, run_expert
from panel.schema import EvidenceRef, EvidenceSnippet, ExpertVerdict
from panel.service import PanelService
from panel.store import OPPORTUNITY_FIELDS, PanelStore


class FakeMessages:
    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        output = next(self.outputs)
        return SimpleNamespace(
            content=[SimpleNamespace(text=output)],
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )


class FakeClient:
    def __init__(self, outputs):
        self.messages = FakeMessages(outputs)


def evidence_ref() -> EvidenceRef:
    return EvidenceRef(doc_id="public-doc", locator="chunk:1")


def snippet(*, public: bool = True) -> EvidenceSnippet:
    return EvidenceSnippet(
        ref=evidence_ref(),
        text="A company facility clearance is required for prime contract performance.",
        title="Public SOW",
        source="https://example.gov/public-sow.pdf",
        public=public,
    )


def verdict(
    expert: str,
    disposition: str = "assess",
    *,
    score: int = 70,
    hard_veto: bool = False,
    veto_kind: str | None = None,
    confidence: float = 0.8,
    grounded: bool = True,
    rationale: str = "supported rationale",
) -> ExpertVerdict:
    return ExpertVerdict(
        expert=expert,
        verdict=disposition,
        score=score,
        hard_veto=hard_veto,
        veto_kind=veto_kind,
        blockers=[],
        top_reason_no_bid=f"{expert} no-bid reason",
        rationale=rationale,
        evidence_refs=[evidence_ref()] if grounded else [],
        confidence=confidence,
        raw_json="{}",
        tokens_used=5,
    )


class AggregateTests(unittest.TestCase):
    def test_ineligible_hard_veto_forces_reject(self):
        result = aggregate(
            [
                verdict("eligibility", "reject", hard_veto=True, veto_kind="ineligible"),
                verdict("fit_pwin", "assess", score=95),
                verdict("redteam", "assess", score=90),
            ]
        )
        self.assertEqual(result.final_verdict, "reject")

    def test_prime_blocked_teamable_forces_monitor_partner(self):
        result = aggregate(
            [
                verdict(
                    "eligibility",
                    "monitor_partner",
                    hard_veto=True,
                    veto_kind="prime_blocked_teamable",
                ),
                verdict("fit_pwin", "assess", score=95),
                verdict("redteam", "reject", score=10),
            ]
        )
        self.assertEqual(result.final_verdict, "monitor_partner")

    def test_most_conservative_confident_view_wins_and_dissent_is_verbatim(self):
        result = aggregate(
            [
                verdict("eligibility", "assess"),
                verdict("fit_pwin", "assess", rationale="optimistic fit"),
                verdict("redteam", "reject", rationale="fatal delivery risk"),
            ]
        )
        self.assertEqual(result.final_verdict, "reject")
        self.assertTrue(any(item["rationale"] == "optimistic fit" for item in result.dissent))

    def test_ungrounded_claim_is_capped_below_consensus_threshold(self):
        result = aggregate(
            [
                verdict("eligibility", "assess", confidence=0.8),
                verdict("fit_pwin", "assess", confidence=0.9, grounded=False),
                verdict("redteam", "monitor_partner", confidence=0.8),
            ]
        )
        self.assertEqual(result.final_verdict, "monitor_partner")
        self.assertTrue(any("fit_pwin" in warning for warning in result.grounding_warnings))

    def test_unusable_eligibility_output_cannot_fall_through_to_assess(self):
        result = aggregate(
            [
                ExpertVerdict.parse_error("eligibility", "bad", "invalid JSON"),
                verdict("fit_pwin", "assess", score=95),
                verdict("redteam", "assess", score=90),
            ]
        )
        self.assertEqual(result.final_verdict, "reject")


class ExpertTests(unittest.TestCase):
    def test_non_public_evidence_is_refused_before_client_call(self):
        client = FakeClient([])
        with self.assertRaises(PublicEvidenceError):
            asyncio.run(
                run_expert(
                    expert="fit_pwin",
                    facts={"notice_id": "NGA"},
                    operator_facts={},
                    evidence=[snippet(public=False)],
                    client=client,
                )
            )
        self.assertEqual(client.messages.calls, 0)

    def test_parse_failure_retries_once(self):
        valid = json.dumps(
            {
                "expert": "fit_pwin",
                "verdict": "monitor_partner",
                "score": 35,
                "hard_veto": False,
                "veto_kind": None,
                "blockers": ["Facility clearance"],
                "top_reason_no_bid": "Prime path is blocked.",
                "rationale": "Use a cleared prime.",
                "evidence_refs": [{"doc_id": "public-doc", "locator": "chunk:1"}],
                "confidence": 0.9,
            }
        )
        client = FakeClient(["not-json", valid])
        result = asyncio.run(
            run_expert(
                expert="fit_pwin",
                facts={"notice_id": "NGA"},
                operator_facts={},
                evidence=[snippet()],
                client=client,
            )
        )
        self.assertEqual(client.messages.calls, 2)
        self.assertEqual(result.verdict, "monitor_partner")
        self.assertEqual(result.tokens_used, 30)


class PanelServiceTests(unittest.TestCase):
    def make_db(self, path: Path):
        with closing(sqlite3.connect(path)) as connection:
            columns = ", ".join(f"{field} TEXT" for field in OPPORTUNITY_FIELDS)
            connection.execute(f"CREATE TABLE opportunities ({columns}, PRIMARY KEY (notice_id))")
            row = {field: "" for field in OPPORTUNITY_FIELDS}
            row.update(
                {
                    "notice_id": "nga-live-notice-id",
                    "sol_number": "NGA-2026-02",
                    "title": "NGA Industry Day",
                    "department": "DEPT OF DEFENSE",
                    "sub_tier": "NGA",
                    "response_deadline": "2026-06-12T17:00:00-04:00",
                    "naics_code": "541715",
                    "active": "Yes",
                }
            )
            placeholders = ", ".join("?" for _ in OPPORTUNITY_FIELDS)
            connection.execute(
                f"INSERT INTO opportunities ({', '.join(OPPORTUNITY_FIELDS)}) VALUES ({placeholders})",
                [row[field] for field in OPPORTUNITY_FIELDS],
            )
            connection.commit()

    def test_nga_industry_day_acceptance_resolves_monitor_partner(self):
        async def fake_expert_runner(*, expert, **kwargs):
            if expert == "eligibility":
                return verdict(
                    "eligibility",
                    "monitor_partner",
                    score=15,
                    hard_veto=True,
                    veto_kind="prime_blocked_teamable",
                    rationale="The public SOW requires a company FCL; only personal eligibility is confirmed.",
                )
            if expert == "fit_pwin":
                return verdict("fit_pwin", "assess", score=75)
            return verdict("redteam", "reject", score=10)

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "contracts.db"
            self.make_db(db_path)
            store = PanelStore(db_path)
            service = PanelService(
                store=store,
                evidence_loader=lambda notice_id: [snippet()],
                expert_runner=fake_expert_runner,
            )
            result = asyncio.run(service.evaluate("NGA-2026-02"))
            latest = store.latest_for_notice("NGA-2026-02")
            with closing(sqlite3.connect(db_path)) as connection:
                run_count = connection.execute("SELECT COUNT(*) FROM panel_runs").fetchone()[0]
                verdict_count = connection.execute("SELECT COUNT(*) FROM panel_verdicts").fetchone()[0]
        self.assertEqual(result["notice_id"], "nga-live-notice-id")
        self.assertEqual(result["final_verdict"], "monitor_partner")
        self.assertIsNotNone(latest)
        self.assertEqual(latest.final_verdict, "monitor_partner")
        self.assertEqual(run_count, 1)
        self.assertEqual(verdict_count, 3)

    def test_panel_snapshot_restores_history_after_mirror_rebuild(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "contracts.db"
            self.make_db(db_path)
            store = PanelStore(db_path)
            aggregated = aggregate(
                [
                    verdict("eligibility", "assess"),
                    verdict("fit_pwin", "assess"),
                    verdict("redteam", "monitor_partner"),
                ]
            )
            store.save_run(
                notice_id="nga-live-notice-id",
                stage="test",
                aggregate=aggregated,
                verdicts=[
                    verdict("eligibility", "assess"),
                    verdict("fit_pwin", "assess"),
                    verdict("redteam", "monitor_partner"),
                ],
            )
            saved = PanelStore.snapshot_existing(db_path)
            db_path.unlink()
            self.make_db(db_path)
            PanelStore(db_path).restore_snapshot(saved)
            restored = PanelStore(db_path).latest_for_notice("nga-live-notice-id")
        self.assertIsNotNone(restored)
        self.assertEqual(restored.final_verdict, "monitor_partner")


if __name__ == "__main__":
    unittest.main()
