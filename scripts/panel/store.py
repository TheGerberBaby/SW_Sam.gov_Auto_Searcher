"""SQLite persistence for panel runs and expert verdicts."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing, contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schema import AggregatedVerdict, EvidenceRef, ExpertVerdict, MODEL, PROMPT_VERSION, PanelRun

PROJECT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_DIR / "data" / "contracts.db"
PANEL_TABLES = ("panel_runs", "panel_verdicts")
OPPORTUNITY_FIELDS = (
    "notice_id",
    "title",
    "sol_number",
    "department",
    "sub_tier",
    "office",
    "posted_date",
    "type",
    "base_type",
    "set_aside_code",
    "set_aside",
    "response_deadline",
    "naics_code",
    "classification_code",
    "pop_city",
    "pop_state",
    "pop_country",
    "active",
    "award_number",
    "award_date",
    "award_amount",
    "awardee",
    "link",
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS panel_runs (
    run_id TEXT PRIMARY KEY,
    notice_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    stage TEXT NOT NULL,
    final_verdict TEXT NOT NULL,
    consensus_score INTEGER NOT NULL,
    dissent_json TEXT NOT NULL,
    tokens_used INTEGER NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS panel_verdicts (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    notice_id TEXT NOT NULL,
    expert TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    verdict TEXT NOT NULL,
    score INTEGER NOT NULL,
    hard_veto INTEGER NOT NULL,
    veto_kind TEXT,
    blockers_json TEXT NOT NULL,
    top_reason_no_bid TEXT NOT NULL,
    rationale TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL,
    confidence REAL NOT NULL,
    raw_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES panel_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_panel_runs_notice_created
    ON panel_runs(notice_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_panel_verdicts_run
    ON panel_verdicts(run_id);
"""


class PanelStoreError(RuntimeError):
    """Raised for panel persistence or lookup failures."""


class PanelStore:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def connection(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def ensure_schema(self) -> None:
        with self.connection() as connection:
            connection.executescript(SCHEMA_SQL)

    def resolve_opportunity(self, identifier: str) -> dict[str, Any]:
        fields = ", ".join(OPPORTUNITY_FIELDS)
        if not self.db_path.exists():
            raise PanelStoreError(f"Local opportunity database is missing: {self.db_path}")
        with self.connection() as connection:
            row = connection.execute(
                f"SELECT {fields} FROM opportunities WHERE notice_id = ?",
                (identifier,),
            ).fetchone()
            if row is None:
                row = connection.execute(
                    f"""
                    SELECT {fields}
                      FROM opportunities
                     WHERE sol_number = ?
                     ORDER BY posted_date DESC, notice_id DESC
                     LIMIT 1
                    """,
                    (identifier,),
                ).fetchone()
        if row is None:
            raise PanelStoreError(f"Opportunity not found by notice ID or solicitation number: {identifier}")
        return dict(row)

    def save_run(
        self,
        *,
        notice_id: str,
        stage: str,
        aggregate: AggregatedVerdict,
        verdicts: list[ExpertVerdict],
        model: str = MODEL,
        prompt_version: str = PROMPT_VERSION,
    ) -> PanelRun:
        self.ensure_schema()
        run_id = uuid.uuid4().hex
        created_at = datetime.now(timezone.utc).isoformat()
        tokens_used = sum(item.tokens_used for item in verdicts)
        dissent = [*aggregate.dissent]
        dissent.extend(
            {"type": "grounding_warning", "detail": detail}
            for detail in aggregate.grounding_warnings
        )
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO panel_runs (
                    run_id, notice_id, created_at, stage, final_verdict,
                    consensus_score, dissent_json, tokens_used, model, prompt_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    notice_id,
                    created_at,
                    stage,
                    aggregate.final_verdict,
                    aggregate.consensus_score,
                    json.dumps(dissent, ensure_ascii=True),
                    tokens_used,
                    model,
                    prompt_version,
                ),
            )
            for verdict in verdicts:
                connection.execute(
                    """
                    INSERT INTO panel_verdicts (
                        id, run_id, notice_id, expert, model, prompt_version,
                        verdict, score, hard_veto, veto_kind, blockers_json,
                        top_reason_no_bid, rationale, evidence_refs_json,
                        confidence, raw_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        uuid.uuid4().hex,
                        run_id,
                        notice_id,
                        verdict.expert,
                        model,
                        prompt_version,
                        verdict.verdict,
                        verdict.score,
                        int(verdict.hard_veto),
                        verdict.veto_kind,
                        json.dumps(verdict.blockers, ensure_ascii=True),
                        verdict.top_reason_no_bid,
                        verdict.rationale,
                        json.dumps([asdict(ref) for ref in verdict.evidence_refs], ensure_ascii=True),
                        verdict.confidence,
                        verdict.raw_json,
                        created_at,
                    ),
                )
        return PanelRun(
            run_id=run_id,
            notice_id=notice_id,
            created_at=created_at,
            stage=stage,
            final_verdict=aggregate.final_verdict,
            consensus_score=aggregate.consensus_score,
            dissent=dissent,
            tokens_used=tokens_used,
            model=model,
            prompt_version=prompt_version,
            verdicts=verdicts,
        )

    def latest_for_notice(self, identifier: str) -> PanelRun | None:
        self.ensure_schema()
        notice_id = identifier
        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT *
                  FROM panel_runs
                 WHERE notice_id = ?
                 ORDER BY created_at DESC
                 LIMIT 1
                """,
                (notice_id,),
            ).fetchone()
        if row is None:
            try:
                notice_id = str(self.resolve_opportunity(identifier)["notice_id"])
            except PanelStoreError:
                return None
            with self.connection() as connection:
                row = connection.execute(
                    """
                    SELECT *
                      FROM panel_runs
                     WHERE notice_id = ?
                     ORDER BY created_at DESC
                     LIMIT 1
                    """,
                    (notice_id,),
                ).fetchone()
        return self._run_from_row(row) if row else None

    def _run_from_row(self, row: sqlite3.Row) -> PanelRun:
        with self.connection() as connection:
            verdict_rows = connection.execute(
                """
                SELECT *
                  FROM panel_verdicts
                 WHERE run_id = ?
                 ORDER BY CASE expert
                    WHEN 'eligibility' THEN 1
                    WHEN 'fit_pwin' THEN 2
                    WHEN 'pricing' THEN 3
                    WHEN 'redteam' THEN 4
                    ELSE 5 END
                """,
                (row["run_id"],),
            ).fetchall()
        verdicts = [
            ExpertVerdict(
                expert=item["expert"],
                verdict=item["verdict"],
                score=int(item["score"]),
                hard_veto=bool(item["hard_veto"]),
                veto_kind=item["veto_kind"],
                blockers=json.loads(item["blockers_json"]),
                top_reason_no_bid=item["top_reason_no_bid"],
                rationale=item["rationale"],
                evidence_refs=[EvidenceRef.from_dict(ref) for ref in json.loads(item["evidence_refs_json"])],
                confidence=float(item["confidence"]),
                raw_json=item["raw_json"],
            )
            for item in verdict_rows
        ]
        return PanelRun(
            run_id=row["run_id"],
            notice_id=row["notice_id"],
            created_at=row["created_at"],
            stage=row["stage"],
            final_verdict=row["final_verdict"],
            consensus_score=int(row["consensus_score"]),
            dissent=json.loads(row["dissent_json"]),
            tokens_used=int(row["tokens_used"]),
            model=row["model"],
            prompt_version=row["prompt_version"],
            verdicts=verdicts,
        )

    @staticmethod
    def snapshot_existing(db_path: str | Path) -> dict[str, list[dict[str, Any]]]:
        path = Path(db_path)
        if not path.exists():
            return {}
        snapshot: dict[str, list[dict[str, Any]]] = {}
        with closing(sqlite3.connect(path)) as connection:
            connection.row_factory = sqlite3.Row
            existing = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
            for table in PANEL_TABLES:
                if table in existing:
                    snapshot[table] = [dict(row) for row in connection.execute(f"SELECT * FROM {table}")]
        return snapshot

    def restore_snapshot(self, snapshot: dict[str, list[dict[str, Any]]]) -> None:
        self.ensure_schema()
        with self.connection() as connection:
            for table in PANEL_TABLES:
                for row in snapshot.get(table, []):
                    columns = list(row)
                    placeholders = ", ".join("?" for _ in columns)
                    connection.execute(
                        f"INSERT OR REPLACE INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
                        [row[column] for column in columns],
                    )
