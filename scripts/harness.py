"""Labeled-gold-set harness for the lead scorer.

This is the autoresearch-pattern harness from the deep-research
report, but pre-Stage-5 (no LLM judging yet). The locked scorer is
`scripts/scoring.py`; the human-edited "program" is
`criteria/*.md` + the weight tables in scoring.py; the metric is
**macro-F1 + Cohen's kappa**.

Gold-set format (CSV at `harness/gold/<name>.csv`):

    notice_id,label,note
    abc123...,fit,"Real Elasticsearch services bid"
    def456...,monitor,"Telemetry RFI worth tracking"
    ghi789...,reject,"BRACKET commodity buy"

Labels: `fit` / `monitor` / `reject`.

The harness loads each labeled notice from the local SAM mirror,
runs the scorer with each profile, and reports macro-F1,
per-class precision/recall, and Cohen's kappa against your labels.

CLI:

    python scripts/harness.py status                # gold-set summary
    python scripts/harness.py run --gold default    # score against default.csv
    python scripts/harness.py compare --profiles technical_services,elastic_only
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from scoring import available_profiles, score_opportunity  # noqa: E402

PROJECT_ROOT = SCRIPT_DIR.parent
DB_PATH = PROJECT_ROOT / "data" / "contracts.db"
GOLD_DIR = PROJECT_ROOT / "harness" / "gold"

LABELS = ("fit", "monitor", "reject")


# ---------------------------------------------------------------------------
# Score → label translation
# ---------------------------------------------------------------------------


def score_to_label(score: int) -> str:
    """The scorer outputs (score, band). We collapse it to a 3-class label
    so we can compare against Jeremy's `fit / monitor / reject` labels.
    """
    if score >= 5:
        return "fit"
    if score >= 2:
        return "monitor"
    return "reject"


# ---------------------------------------------------------------------------
# Gold-set loading
# ---------------------------------------------------------------------------


@dataclass
class GoldRow:
    notice_id: str
    label: str
    note: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_gold(name: str = "default") -> list[GoldRow]:
    path = GOLD_DIR / f"{name}.csv"
    if not path.exists():
        return []
    rows: list[GoldRow] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            label = (row.get("label") or "").strip().lower()
            if label not in LABELS:
                continue
            notice_id = (row.get("notice_id") or "").strip()
            if not notice_id:
                continue
            rows.append(GoldRow(notice_id=notice_id, label=label, note=row.get("note") or ""))
    return rows


def save_gold(name: str, rows: list[GoldRow]) -> Path:
    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    path = GOLD_DIR / f"{name}.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["notice_id", "label", "note"])
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_dict())
    return path


def append_gold(name: str, notice_id: str, label: str, note: str = "") -> Path:
    if label not in LABELS:
        raise ValueError(f"label must be one of {LABELS}; got {label!r}")
    rows = load_gold(name)
    rows = [r for r in rows if r.notice_id != notice_id]
    rows.append(GoldRow(notice_id=notice_id, label=label, note=note))
    return save_gold(name, rows)


# ---------------------------------------------------------------------------
# Hydrate opportunities from the local mirror
# ---------------------------------------------------------------------------


def _hydrate(notice_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    notice_ids = list(notice_ids)
    if not notice_ids or not DB_PATH.exists():
        return {}
    placeholders = ",".join("?" * len(notice_ids))
    sql = f"""
        SELECT notice_id, title, sol_number, department, sub_tier, posted_date,
               type, set_aside, set_aside_code, response_deadline, naics_code,
               pop_city, pop_state, active, link, description
          FROM opportunities
         WHERE notice_id IN ({placeholders})
    """
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, notice_ids).fetchall()
    return {row["notice_id"]: dict(row) for row in rows}


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


@dataclass
class ClassMetrics:
    label: str
    support: int
    precision: float
    recall: float
    f1: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RunResult:
    profile: str
    gold_set: str
    n: int
    n_unhydrated: int
    accuracy: float
    macro_f1: float
    cohen_kappa: float
    per_class: list[ClassMetrics]
    confusion: dict[str, dict[str, int]]   # confusion[truth][predicted] = count

    def to_dict(self) -> dict[str, Any]:
        return {
            **{k: v for k, v in asdict(self).items() if k not in {"per_class"}},
            "per_class": [c.to_dict() for c in self.per_class],
        }


def _per_class(predictions: list[tuple[str, str]]) -> list[ClassMetrics]:
    metrics: list[ClassMetrics] = []
    for label in LABELS:
        tp = sum(1 for y, p in predictions if y == label and p == label)
        fp = sum(1 for y, p in predictions if y != label and p == label)
        fn = sum(1 for y, p in predictions if y == label and p != label)
        support = sum(1 for y, _ in predictions if y == label)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        metrics.append(ClassMetrics(label=label, support=support, precision=precision, recall=recall, f1=f1))
    return metrics


def _macro_f1(per_class: list[ClassMetrics]) -> float:
    return sum(c.f1 for c in per_class) / len(per_class)


def _cohen_kappa(predictions: list[tuple[str, str]]) -> float:
    """Cohen's kappa for two raters with the same label set."""
    if not predictions:
        return 0.0
    n = len(predictions)
    truth_counts = Counter(y for y, _ in predictions)
    pred_counts = Counter(p for _, p in predictions)
    p_o = sum(1 for y, p in predictions if y == p) / n
    p_e = sum((truth_counts[label] / n) * (pred_counts[label] / n) for label in LABELS)
    if p_e == 1.0:
        return 1.0
    return (p_o - p_e) / (1.0 - p_e)


def _confusion(predictions: list[tuple[str, str]]) -> dict[str, dict[str, int]]:
    matrix = {y: {p: 0 for p in LABELS} for y in LABELS}
    for y, p in predictions:
        matrix[y][p] += 1
    return matrix


# ---------------------------------------------------------------------------
# Public run / compare
# ---------------------------------------------------------------------------


def run(profile: str, gold_set: str = "default") -> RunResult:
    if profile not in available_profiles():
        raise ValueError(f"unknown profile {profile!r}; available: {available_profiles()}")
    gold = load_gold(gold_set)
    if not gold:
        raise ValueError(f"gold set {gold_set!r} not found or empty at {GOLD_DIR / (gold_set + '.csv')}")

    opportunities = _hydrate(g.notice_id for g in gold)
    predictions: list[tuple[str, str]] = []
    unhydrated = 0
    for row in gold:
        opp = opportunities.get(row.notice_id)
        if not opp:
            unhydrated += 1
            continue
        result = score_opportunity(opp, profile=profile)
        predictions.append((row.label, score_to_label(result.score)))

    n = len(predictions)
    if n == 0:
        raise ValueError("No labeled opportunities were found in the local mirror — refresh sync_bulk.py.")
    accuracy = sum(1 for y, p in predictions if y == p) / n
    pc = _per_class(predictions)
    return RunResult(
        profile=profile,
        gold_set=gold_set,
        n=n,
        n_unhydrated=unhydrated,
        accuracy=accuracy,
        macro_f1=_macro_f1(pc),
        cohen_kappa=_cohen_kappa(predictions),
        per_class=pc,
        confusion=_confusion(predictions),
    )


def compare(profiles: list[str], gold_set: str = "default") -> list[RunResult]:
    return [run(profile=p, gold_set=gold_set) for p in profiles]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_result(result: RunResult) -> None:
    print(f"\n=== profile: {result.profile} · gold: {result.gold_set} ===")
    print(f"  n={result.n}  unhydrated={result.n_unhydrated}")
    print(f"  accuracy   = {result.accuracy:.3f}")
    print(f"  macro F1   = {result.macro_f1:.3f}")
    print(f"  Cohen's κ  = {result.cohen_kappa:.3f}")
    print(f"  {'label':<8}  {'support':>8}  {'P':>6}  {'R':>6}  {'F1':>6}")
    for c in result.per_class:
        print(f"  {c.label:<8}  {c.support:>8}  {c.precision:6.3f}  {c.recall:6.3f}  {c.f1:6.3f}")
    print("  confusion (rows=truth, cols=predicted):")
    print(f"    {'':<10} " + " ".join(f"{l:>10}" for l in LABELS))
    for label in LABELS:
        row = result.confusion[label]
        print(f"    {label:<10} " + " ".join(f"{row[p]:>10}" for p in LABELS))


def _cli() -> None:
    parser = argparse.ArgumentParser(description="Labeled-gold-set harness for the lead scorer.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_status = sub.add_parser("status", help="Summarize available gold sets.")
    p_status.add_argument("--gold", default=None)

    p_run = sub.add_parser("run", help="Run one profile against a gold set.")
    p_run.add_argument("--profile", default="technical_services", choices=available_profiles())
    p_run.add_argument("--gold", default="default")
    p_run.add_argument("--json", action="store_true")

    p_cmp = sub.add_parser("compare", help="Run multiple profiles side by side.")
    p_cmp.add_argument("--profiles", default=",".join(available_profiles()))
    p_cmp.add_argument("--gold", default="default")
    p_cmp.add_argument("--json", action="store_true")

    p_lbl = sub.add_parser("label", help="Append / update a label.")
    p_lbl.add_argument("notice_id")
    p_lbl.add_argument("label", choices=LABELS)
    p_lbl.add_argument("--gold", default="default")
    p_lbl.add_argument("--note", default="")

    args = parser.parse_args()

    if args.cmd == "status":
        if args.gold:
            rows = load_gold(args.gold)
            counts = Counter(r.label for r in rows)
            print(f"\nGold set: {args.gold}  ({GOLD_DIR / (args.gold + '.csv')})")
            print(f"  total: {len(rows)}")
            for lbl in LABELS:
                print(f"  {lbl:<8} {counts.get(lbl, 0)}")
        else:
            if not GOLD_DIR.exists():
                print("(no gold sets — run with --gold <name> after labeling)")
                return
            for path in sorted(GOLD_DIR.glob("*.csv")):
                rows = load_gold(path.stem)
                counts = Counter(r.label for r in rows)
                summary = " ".join(f"{lbl}={counts.get(lbl, 0)}" for lbl in LABELS)
                print(f"  {path.stem:<24} total={len(rows):>4}  {summary}")
    elif args.cmd == "run":
        result = run(profile=args.profile, gold_set=args.gold)
        if args.json:
            print(json.dumps(result.to_dict(), indent=2))
            return
        _print_result(result)
    elif args.cmd == "compare":
        names = [p.strip() for p in args.profiles.split(",") if p.strip()]
        results = compare(profiles=names, gold_set=args.gold)
        if args.json:
            print(json.dumps([r.to_dict() for r in results], indent=2))
            return
        for r in results:
            _print_result(r)
        print("\n=== ranking by macro F1 ===")
        for r in sorted(results, key=lambda x: x.macro_f1, reverse=True):
            print(f"  {r.macro_f1:.3f}  {r.profile}")
    elif args.cmd == "label":
        path = append_gold(args.gold, args.notice_id, args.label, note=args.note)
        rows = load_gold(args.gold)
        print(f"labeled {args.notice_id} -> {args.label}  ({path}, total={len(rows)})")


if __name__ == "__main__":
    _cli()
