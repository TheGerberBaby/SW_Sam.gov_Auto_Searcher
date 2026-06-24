"""Pure deterministic aggregation for panel expert outputs."""

from __future__ import annotations

from statistics import mean

from .schema import AggregatedVerdict, ExpertVerdict

VERDICT_PRIORITY = {"reject": 0, "monitor_partner": 1, "assess": 2}


def _effective_confidence(verdict: ExpertVerdict) -> float:
    """Cap ungrounded narrative claims below the consensus threshold."""
    has_claim = bool(verdict.blockers or verdict.top_reason_no_bid or verdict.rationale)
    if has_claim and not verdict.evidence_refs:
        return min(verdict.confidence, 0.49)
    return verdict.confidence


def _top_reason(verdicts: list[ExpertVerdict]) -> str:
    ordered = sorted(
        verdicts,
        key=lambda item: (
            not item.hard_veto,
            VERDICT_PRIORITY[item.verdict],
            -item.confidence,
            item.expert,
        ),
    )
    for verdict in ordered:
        if verdict.top_reason_no_bid:
            return verdict.top_reason_no_bid
        if verdict.blockers:
            return verdict.blockers[0]
    return ""


def _dissent(verdicts: list[ExpertVerdict], final_verdict: str) -> list[dict[str, object]]:
    dissent = []
    for verdict in verdicts:
        if verdict.verdict == final_verdict:
            continue
        dissent.append(
            {
                "expert": verdict.expert,
                "verdict": verdict.verdict,
                "confidence": verdict.confidence,
                "rationale": verdict.rationale,
                "top_reason_no_bid": verdict.top_reason_no_bid,
            }
        )
    dissent.sort(
        key=lambda item: (
            VERDICT_PRIORITY[str(item["verdict"])],
            -float(item["confidence"]),
            str(item["expert"]),
        )
    )
    return dissent


def aggregate(verdicts: list[ExpertVerdict]) -> AggregatedVerdict:
    """Apply eligibility vetoes and conservative consensus without API calls."""
    if not verdicts:
        raise ValueError("cannot aggregate an empty expert panel")
    eligibility = next((item for item in verdicts if item.expert == "eligibility"), None)
    if eligibility is None:
        raise ValueError("panel requires an eligibility verdict")

    warnings = [
        f"{item.expert}: no evidence_refs supplied; confidence capped below consensus threshold"
        for item in verdicts
        if _effective_confidence(item) < item.confidence
    ]
    score = round(mean(item.score for item in verdicts))

    if eligibility.hard_veto:
        final = "reject" if eligibility.veto_kind == "ineligible" else "monitor_partner"
        return AggregatedVerdict(
            final_verdict=final,
            consensus_score=score,
            dissent=_dissent(verdicts, final),
            top_reason_no_bid=_top_reason(verdicts),
            grounding_warnings=warnings,
        )

    if _effective_confidence(eligibility) < 0.5:
        return AggregatedVerdict(
            final_verdict="reject",
            consensus_score=score,
            dissent=_dissent(verdicts, "reject"),
            top_reason_no_bid=_top_reason(verdicts),
            grounding_warnings=warnings,
        )

    supported = [item for item in verdicts if _effective_confidence(item) >= 0.5]
    final = min(supported, key=lambda item: VERDICT_PRIORITY[item.verdict]).verdict if supported else "reject"
    return AggregatedVerdict(
        final_verdict=final,
        consensus_score=score,
        dissent=_dissent(verdicts, final),
        top_reason_no_bid=_top_reason(verdicts),
        grounding_warnings=warnings,
    )
