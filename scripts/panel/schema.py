"""Data contracts for the independent opportunity-evaluation panel."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

MODEL = "claude-opus-4-8"
PROMPT_VERSION = "panel-v1.0.0"
EXPERTS = ("eligibility", "fit_pwin", "pricing", "redteam")
PHASE1_EXPERTS = ("eligibility", "fit_pwin", "redteam")
VERDICTS = ("reject", "monitor_partner", "assess")
VETO_KINDS = ("ineligible", "prime_blocked_teamable")
EXPERT_OUTPUT_KEYS = {
    "expert",
    "verdict",
    "score",
    "hard_veto",
    "veto_kind",
    "blockers",
    "top_reason_no_bid",
    "rationale",
    "evidence_refs",
    "confidence",
}


class SchemaError(ValueError):
    """Raised when an expert response does not satisfy the pinned contract."""


@dataclass(frozen=True)
class EvidenceRef:
    doc_id: str
    locator: str

    @classmethod
    def from_dict(cls, value: Any) -> "EvidenceRef":
        if not isinstance(value, dict):
            raise SchemaError("each evidence_ref must be an object")
        doc_id = str(value.get("doc_id") or "").strip()
        locator = str(value.get("locator") or "").strip()
        if not doc_id or not locator:
            raise SchemaError("each evidence_ref needs doc_id and locator")
        return cls(doc_id=doc_id, locator=locator)


@dataclass(frozen=True)
class EvidenceSnippet:
    ref: EvidenceRef
    text: str
    title: str
    source: str
    public: bool

    def to_payload(self) -> dict[str, Any]:
        return {
            "evidence_ref": asdict(self.ref),
            "title": self.title,
            "source": self.source,
            "excerpt": self.text,
            "public": self.public,
        }


@dataclass
class ExpertVerdict:
    expert: str
    verdict: str
    score: int
    hard_veto: bool
    veto_kind: str | None
    blockers: list[str]
    top_reason_no_bid: str
    rationale: str
    evidence_refs: list[EvidenceRef]
    confidence: float
    raw_json: str = ""
    tokens_used: int = 0

    @classmethod
    def from_payload(
        cls,
        payload: Any,
        *,
        expected_expert: str,
        raw_json: str,
        tokens_used: int = 0,
    ) -> "ExpertVerdict":
        if not isinstance(payload, dict):
            raise SchemaError("expert response must be a JSON object")
        missing = EXPERT_OUTPUT_KEYS - set(payload)
        extra = set(payload) - EXPERT_OUTPUT_KEYS
        if missing or extra:
            raise SchemaError(
                f"expert response keys must match pinned schema; missing={sorted(missing)}, extra={sorted(extra)}"
            )
        expert = str(payload.get("expert") or "").strip()
        verdict = str(payload.get("verdict") or "").strip()
        if expert != expected_expert or expert not in EXPERTS:
            raise SchemaError(f"expected expert {expected_expert!r}, got {expert!r}")
        if verdict not in VERDICTS:
            raise SchemaError(f"invalid verdict: {verdict!r}")
        score = payload.get("score")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise SchemaError("score must be a number from 0 to 100")
        score = int(score)
        if not 0 <= score <= 100:
            raise SchemaError("score must be a number from 0 to 100")
        hard_veto = payload.get("hard_veto")
        if not isinstance(hard_veto, bool):
            raise SchemaError("hard_veto must be a boolean")
        veto_kind = payload.get("veto_kind")
        if veto_kind is not None:
            veto_kind = str(veto_kind).strip()
        if hard_veto and expert != "eligibility":
            raise SchemaError("only eligibility may set hard_veto")
        if hard_veto and veto_kind not in VETO_KINDS:
            raise SchemaError("hard_veto requires a supported veto_kind")
        if not hard_veto and veto_kind is not None:
            raise SchemaError("veto_kind must be null when hard_veto is false")
        blockers_value = payload.get("blockers")
        if not isinstance(blockers_value, list):
            raise SchemaError("blockers must be a list")
        blockers = [str(item).strip() for item in blockers_value if str(item).strip()]
        refs_value = payload.get("evidence_refs")
        if not isinstance(refs_value, list):
            raise SchemaError("evidence_refs must be a list")
        evidence_refs = [EvidenceRef.from_dict(item) for item in refs_value]
        confidence = payload.get("confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise SchemaError("confidence must be a number from 0 to 1")
        confidence = float(confidence)
        if not 0 <= confidence <= 1:
            raise SchemaError("confidence must be a number from 0 to 1")
        return cls(
            expert=expert,
            verdict=verdict,
            score=score,
            hard_veto=hard_veto,
            veto_kind=veto_kind,
            blockers=blockers,
            top_reason_no_bid=str(payload.get("top_reason_no_bid") or "").strip(),
            rationale=str(payload.get("rationale") or "").strip(),
            evidence_refs=evidence_refs,
            confidence=confidence,
            raw_json=raw_json,
            tokens_used=max(0, int(tokens_used)),
        )

    @classmethod
    def parse_error(
        cls,
        expert: str,
        raw_json: str,
        detail: str,
        *,
        tokens_used: int = 0,
    ) -> "ExpertVerdict":
        return cls(
            expert=expert,
            verdict="reject",
            score=0,
            hard_veto=False,
            veto_kind=None,
            blockers=[f"parse_error: {detail}"],
            top_reason_no_bid="Expert output could not be parsed after one retry.",
            rationale="The expert response failed the pinned JSON schema and cannot support a bid.",
            evidence_refs=[],
            confidence=0.0,
            raw_json=raw_json,
            tokens_used=max(0, int(tokens_used)),
        )

    def to_dict(self, *, include_raw: bool = False) -> dict[str, Any]:
        result = {
            "expert": self.expert,
            "verdict": self.verdict,
            "score": self.score,
            "hard_veto": self.hard_veto,
            "veto_kind": self.veto_kind,
            "blockers": self.blockers,
            "top_reason_no_bid": self.top_reason_no_bid,
            "rationale": self.rationale,
            "evidence_refs": [asdict(ref) for ref in self.evidence_refs],
            "confidence": self.confidence,
        }
        if include_raw:
            result["raw_json"] = self.raw_json
        return result


@dataclass
class AggregatedVerdict:
    final_verdict: str
    consensus_score: int
    dissent: list[dict[str, Any]] = field(default_factory=list)
    top_reason_no_bid: str = ""
    grounding_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PanelRun:
    run_id: str
    notice_id: str
    created_at: str
    stage: str
    final_verdict: str
    consensus_score: int
    dissent: list[dict[str, Any]]
    tokens_used: int
    model: str
    prompt_version: str
    verdicts: list[ExpertVerdict] = field(default_factory=list)

    def to_dict(self, *, include_raw: bool = False) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "notice_id": self.notice_id,
            "created_at": self.created_at,
            "stage": self.stage,
            "final_verdict": self.final_verdict,
            "consensus_score": self.consensus_score,
            "dissent": self.dissent,
            "tokens_used": self.tokens_used,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "verdicts": [verdict.to_dict(include_raw=include_raw) for verdict in self.verdicts],
        }
