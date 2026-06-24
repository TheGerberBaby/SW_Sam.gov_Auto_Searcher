"""Programmatic Phase-1 panel orchestration."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Awaitable, Callable

from document_store import DocumentStoreError

from .aggregate import aggregate
from .evidence import retrieve_public_evidence
from .experts import PanelExpertError, run_expert
from .schema import MODEL, PHASE1_EXPERTS, PROMPT_VERSION, EvidenceSnippet, ExpertVerdict
from .store import PanelStore, PanelStoreError

PROJECT_DIR = Path(__file__).resolve().parents[2]
OPERATOR_FACTS_PATH = PROJECT_DIR / "criteria" / "PANEL_OPERATOR_FACTS.json"
OPERATOR_FACTS_EXAMPLE_PATH = PROJECT_DIR / "criteria" / "PANEL_OPERATOR_FACTS.example.json"
EvidenceLoader = Callable[[str], list[EvidenceSnippet]]
ExpertRunner = Callable[..., Awaitable[ExpertVerdict]]


class PanelError(RuntimeError):
    """Raised for operator-facing panel failures."""


class PanelService:
    def __init__(
        self,
        *,
        store: PanelStore | None = None,
        evidence_loader: EvidenceLoader = retrieve_public_evidence,
        expert_runner: ExpertRunner = run_expert,
    ) -> None:
        self.store = store or PanelStore()
        self.evidence_loader = evidence_loader
        self.expert_runner = expert_runner

    def operator_facts(self) -> dict[str, Any]:
        facts_path = OPERATOR_FACTS_PATH if OPERATOR_FACTS_PATH.exists() else OPERATOR_FACTS_EXAMPLE_PATH
        try:
            return json.loads(facts_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PanelError(f"Unable to load structured operator facts: {facts_path}") from exc

    async def evaluate(self, identifier: str) -> dict[str, Any]:
        """Run the stateless Phase-1 panel and persist the deterministic verdict."""
        try:
            facts = self.store.resolve_opportunity(identifier)
            evidence = self.evidence_loader(str(facts["notice_id"]))
            verdicts = await asyncio.gather(
                *(
                    self.expert_runner(
                        expert=expert,
                        facts=facts,
                        operator_facts=self.operator_facts(),
                        evidence=evidence,
                        model=MODEL,
                        prompt_version=PROMPT_VERSION,
                    )
                    for expert in PHASE1_EXPERTS
                )
            )
            aggregated = aggregate(list(verdicts))
            run = self.store.save_run(
                notice_id=str(facts["notice_id"]),
                stage="full_panel_phase1",
                aggregate=aggregated,
                verdicts=list(verdicts),
            )
        except (DocumentStoreError, PanelExpertError, PanelStoreError) as exc:
            raise PanelError(str(exc)) from exc
        return {
            **run.to_dict(),
            "requested_identifier": identifier,
            "solicitation_number": facts.get("sol_number"),
            "title": facts.get("title"),
            "top_reason_no_bid": aggregated.top_reason_no_bid,
            "grounding_warnings": aggregated.grounding_warnings,
            "evidence_refs": [snippet.to_payload()["evidence_ref"] for snippet in evidence],
        }
