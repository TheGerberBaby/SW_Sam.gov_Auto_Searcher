"""DSPy GEPA scaffold for self-evolving fit criteria.

This is Stage 5 from the deep-research report — wired up but NOT
runnable as-is. To use it:

    1. pip install dspy-ai          # adds a Python dep that the rest of
                                      the project does not need
    2. export OPENAI_API_KEY=...    # or another LLM the dspy.LM call
                                      supports
    3. Have at least ~150 labeled examples in harness/gold/<name>.csv
       (see harness/README.md). 6 is not enough — GEPA will overfit.
    4. Run: python harness/dspy_gepa_scaffold.py --gold <name>

The pattern (per the report):

  - The harness/labels are the locked scorer (script + CSV in this repo).
  - The "program" is `signature.instructions` — a natural-language
    description of the fit criteria. GEPA evolves it under your review.
  - Metric returns `dspy.Prediction(score=float, feedback=str)` so GEPA
    can introspect *why* a prediction was wrong, not just that it was.

This file is intentionally small. The hard part is collecting and
maintaining the gold set, not running GEPA.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))


def _import_dspy():
    try:
        import dspy  # type: ignore
    except ImportError as exc:
        raise SystemExit(
            "dspy is not installed. Run: pip install dspy-ai\n"
            "Then re-run this script. See the file header for full instructions."
        ) from exc
    return dspy


def build_program(dspy):
    """Define the DSPy module + signature that GEPA will evolve."""

    class FitClassifier(dspy.Signature):
        """Classify a federal SAM.gov opportunity as fit / monitor / reject
        for Stormwind Contracting.

        Stormwind pursues:
        - Elasticsearch / Elastic Stack / OpenSearch
        - AI search, RAG, vector / semantic retrieval
        - Observability, log analytics, SIEM
        - VTC / unified communications / network engineering services
        - DevSecOps / data engineering / platform services

        Stormwind does NOT pursue:
        - Construction, facility repair, AV install, janitorial
        - Commodity hardware buys, license-only purchases
        - Generic IT staffing without an engineering deliverable

        Service-disabled veteran owned (SDVOSB). Primary NAICS 541512.
        DMV-focused but remote-eligible.
        """
        title: str = dspy.InputField(desc="The opportunity title")
        description: str = dspy.InputField(desc="The opportunity description / SOW excerpt")
        naics: str = dspy.InputField(desc="NAICS code")
        set_aside: str = dspy.InputField(desc="Set-aside code")
        label: str = dspy.OutputField(desc="Exactly one of: fit, monitor, reject")

    return dspy.Predict(FitClassifier)


def metric_factory():
    """Returns a metric function GEPA can use. The score is `1.0` on
    agreement and `0.0` otherwise; the textual feedback explains the
    disagreement so GEPA can revise the signature instructions.
    """
    dspy = _import_dspy()

    def metric(gold, pred, trace=None, pred_name=None, pred_trace=None):
        try:
            truth = gold.label.strip().lower()
            guess = pred.label.strip().lower()
        except AttributeError:
            return dspy.Prediction(score=0.0, feedback="Prediction missing `label` field.")
        if truth == guess:
            return dspy.Prediction(score=1.0, feedback=f"Correct: {truth}.")
        return dspy.Prediction(
            score=0.0,
            feedback=(
                f"Predicted {guess!r}, true label is {truth!r}. "
                f"Title: {getattr(gold, 'title', '')[:120]!r}. "
                f"NAICS: {getattr(gold, 'naics', '')!r}. "
                f"Reconsider the criteria for distinguishing {truth} from {guess}."
            ),
        )

    return metric


def load_examples(dspy, gold_name: str):
    """Pull labeled opportunities from harness/<gold>.csv joined with the
    local SAM mirror via scripts/harness.py.
    """
    import harness as harness_lib
    rows = harness_lib.load_gold(gold_name)
    if len(rows) < 30:
        print(
            f"WARNING: only {len(rows)} labeled examples — GEPA needs ~150+ "
            f"to evolve criteria without overfitting. Continuing for demo only.",
            file=sys.stderr,
        )
    hydrated = harness_lib._hydrate(r.notice_id for r in rows)
    examples = []
    for row in rows:
        opp = hydrated.get(row.notice_id)
        if not opp:
            continue
        examples.append(
            dspy.Example(
                title=opp.get("title") or "",
                description=(opp.get("description") or "")[:6000],
                naics=opp.get("naics_code") or "",
                set_aside=opp.get("set_aside") or "",
                label=row.label,
            ).with_inputs("title", "description", "naics", "set_aside")
        )
    return examples


def main() -> None:
    parser = argparse.ArgumentParser(description="Run DSPy GEPA to evolve fit criteria.")
    parser.add_argument("--gold", default="default")
    parser.add_argument("--model", default="openai/gpt-4o-mini",
                        help="dspy.LM model identifier (e.g., openai/gpt-4o-mini, anthropic/claude-3-5-sonnet).")
    parser.add_argument("--auto", default="medium", choices=["light", "medium", "heavy"])
    parser.add_argument("--max-tokens", dest="max_tokens", type=int, default=4000)
    args = parser.parse_args()

    dspy = _import_dspy()

    # Configure LM. Caller is responsible for the API key env var.
    lm = dspy.LM(model=args.model, max_tokens=args.max_tokens, temperature=1.0)
    dspy.configure(lm=lm)

    program = build_program(dspy)
    metric = metric_factory()
    examples = load_examples(dspy, args.gold)
    if not examples:
        raise SystemExit(f"No usable examples — check harness/gold/{args.gold}.csv and that the SAM mirror has the notices.")

    # Train/val split — keep it simple and reproducible.
    split = max(1, int(len(examples) * 0.8))
    trainset = examples[:split]
    valset = examples[split:]

    optimizer = dspy.GEPA(
        metric=metric,
        reflection_lm=lm,
        auto=args.auto,
    )
    compiled = optimizer.compile(program, trainset=trainset, valset=valset)

    # Show the evolved criteria. Jeremy reviews and decides whether to
    # promote them into criteria/*.md as the next baseline.
    print("\n=== Best candidate signature ===\n")
    try:
        print(compiled.signature.instructions)
    except AttributeError:
        # Older / newer DSPy versions expose this differently
        print(getattr(compiled, "best_candidate", compiled))


if __name__ == "__main__":
    main()
