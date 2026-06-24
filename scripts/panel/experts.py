"""Stateless, role-differentiated Anthropic expert calls."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .schema import EvidenceSnippet, ExpertVerdict, MODEL, PROMPT_VERSION, SchemaError

PROJECT_DIR = Path(__file__).resolve().parents[2]
PROMPT_DIR = PROJECT_DIR / "prompts" / "panel"
load_dotenv(PROJECT_DIR / ".env")


class PanelExpertError(RuntimeError):
    """Raised when an expert call cannot be completed."""


class PublicEvidenceError(PanelExpertError):
    """Raised before API transmission when evidence lacks an explicit public flag."""


def assert_public_evidence(evidence: list[EvidenceSnippet]) -> None:
    blocked = [snippet.ref.doc_id for snippet in evidence if not snippet.public]
    if blocked:
        joined = ", ".join(sorted(set(blocked)))
        raise PublicEvidenceError(
            f"Refusing external API transmission: evidence is not explicitly public: {joined}"
        )


def _prompt_for(expert: str) -> str:
    path = PROMPT_DIR / f"{expert}.md"
    if not path.exists():
        raise PanelExpertError(f"Panel prompt is missing: {path}")
    return path.read_text(encoding="utf-8")


def _default_client() -> Any:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise PanelExpertError("ANTHROPIC_API_KEY is required to run the evaluation panel.")
    try:
        from anthropic import AsyncAnthropic
    except ImportError as exc:
        raise PanelExpertError("Install panel dependencies with: pip install -r requirements.txt") from exc
    return AsyncAnthropic(api_key=api_key)


def _response_text(response: Any) -> str:
    fragments = [str(getattr(block, "text", "")) for block in getattr(response, "content", [])]
    return "".join(fragments).strip()


def _tokens_used(response: Any) -> int:
    usage = getattr(response, "usage", None)
    return int(getattr(usage, "input_tokens", 0) or 0) + int(
        getattr(usage, "output_tokens", 0) or 0
    )


def build_user_payload(
    *,
    expert: str,
    facts: dict[str, Any],
    operator_facts: dict[str, Any],
    evidence: list[EvidenceSnippet],
) -> dict[str, Any]:
    assert_public_evidence(evidence)
    return {
        "expert": expert,
        "prompt_version": PROMPT_VERSION,
        "opportunity_facts_from_sqlite": facts,
        "operator_facts": operator_facts,
        "public_retrieved_evidence": [snippet.to_payload() for snippet in evidence],
        "instructions": (
            "Return exactly one JSON object matching the pinned schema. "
            "Cite evidence_ref objects for every solicitation-specific blocker or fit claim."
        ),
    }


async def run_expert(
    *,
    expert: str,
    facts: dict[str, Any],
    operator_facts: dict[str, Any],
    evidence: list[EvidenceSnippet],
    client: Any | None = None,
    model: str = MODEL,
    prompt_version: str = PROMPT_VERSION,
) -> ExpertVerdict:
    """Run one fresh-message expert call, retrying malformed JSON once."""
    if prompt_version != PROMPT_VERSION:
        raise PanelExpertError(f"Unsupported prompt version: {prompt_version}")
    payload = build_user_payload(
        expert=expert,
        facts=facts,
        operator_facts=operator_facts,
        evidence=evidence,
    )
    client = client or _default_client()
    prompt = _prompt_for(expert)
    raw_attempts: list[str] = []
    parse_detail = ""
    total_tokens = 0
    for attempt in range(2):
        system = prompt
        if attempt:
            system += "\n\nRETRY: Return valid JSON only. Do not include prose or code fences."
        try:
            response = await client.messages.create(
                model=model,
                max_tokens=1800,
                temperature=0.1,
                system=system,
                messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=True)}],
            )
        except Exception as exc:  # SDK exceptions vary by transport and HTTP status.
            raise PanelExpertError(f"{expert} expert API call failed: {exc}") from exc
        raw = _response_text(response)
        raw_attempts.append(raw)
        total_tokens += _tokens_used(response)
        try:
            parsed = json.loads(raw)
            return ExpertVerdict.from_payload(
                parsed,
                expected_expert=expert,
                raw_json=raw,
                tokens_used=total_tokens,
            )
        except (json.JSONDecodeError, SchemaError) as exc:
            parse_detail = str(exc)
    return ExpertVerdict.parse_error(
        expert,
        "\n--- retry ---\n".join(raw_attempts),
        parse_detail,
        tokens_used=total_tokens,
    )
