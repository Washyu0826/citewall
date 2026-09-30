"""Case summaries — the metadata behind the dashboard and case list.

The gateway keeps no analysis results (drafts live only in the per-user
response cache), so "which of my cases have a deadline next week?" had no
answer. This store records, per (tenant, case), the LAST successful analysis
as metadata only:

    rejection types, affected claim numbers, statutory / internal deadlines,
    jurisdiction, target patent number, model used, degraded flag, who ran it
    and when.

What it deliberately never stores: OA text, examiner arguments, drafts,
citations or anything else derived from privileged content. Every column is
either a public identifier (patent number), a date, an enum or a count — the
same class of data the audit log already holds. That keeps the store outside
the redaction perimeter (invariant #3) and cheap to erase.

Storage: one SQLite file (``config.CASE_SUMMARY_DB_PATH``), upsert per
analysis. Like the case registry this assumes one gateway process; a
multi-replica deployment needs the Postgres twin (same schema).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.shared import config
from backend.shared.models import AnalysisResponse, User

_DDL = """
CREATE TABLE IF NOT EXISTS case_summaries (
    tenant_id              TEXT NOT NULL,
    case_id                TEXT NOT NULL,
    target_patent_no       TEXT,
    jurisdiction           TEXT,
    analyzed_at            TEXT NOT NULL,
    analyzed_by            TEXT NOT NULL,
    statutory_deadline     TEXT,
    recommended_deadline   TEXT,
    rejection_types        TEXT NOT NULL,
    affected_claims        TEXT NOT NULL,
    rejection_count        INTEGER NOT NULL,
    draft_count            INTEGER NOT NULL,
    model_used             TEXT,
    degraded               INTEGER NOT NULL,
    PRIMARY KEY (tenant_id, case_id)
);
"""

_COLS = (
    "case_id, target_patent_no, jurisdiction, analyzed_at, analyzed_by, "
    "statutory_deadline, recommended_deadline, rejection_types, affected_claims, "
    "rejection_count, draft_count, model_used, degraded"
)

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None
_conn_path: Path | None = None


def _connection() -> sqlite3.Connection:
    """Open lazily so tests can redirect ``config.CASE_SUMMARY_DB_PATH``."""
    global _conn, _conn_path
    path = Path(config.CASE_SUMMARY_DB_PATH)
    if _conn is None or _conn_path != path:
        path.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(path, check_same_thread=False, timeout=30.0)
        _conn.executescript(_DDL)
        _conn.commit()
        _conn_path = path
    return _conn


def record_analysis(
    user: User,
    case_id: str,
    target_patent_no: str,
    jurisdiction: str | None,
    response: AnalysisResponse,
) -> None:
    """Upsert the metadata of one successful analysis."""
    rejections = response.oa.rejections
    types = sorted({r.rejection_type.value for r in rejections})
    claims = sorted({c for r in rejections for c in r.affected_claims})
    deadline = response.deadline_summary
    row = (
        user.tenant_id,
        case_id,
        target_patent_no,
        jurisdiction,
        datetime.now(UTC).isoformat(),
        user.user_id,
        deadline.statutory_deadline.isoformat() if deadline else None,
        deadline.recommended_internal_deadline.isoformat() if deadline else None,
        json.dumps(types),
        json.dumps(claims),
        len(rejections),
        len(response.drafts),
        response.cost_meta.model,
        int("-DEGRADED-" in (response.cost_meta.model or "")),
    )
    with _lock:
        conn = _connection()
        conn.execute(
            """
            INSERT INTO case_summaries (
                tenant_id, case_id, target_patent_no, jurisdiction, analyzed_at,
                analyzed_by, statutory_deadline, recommended_deadline,
                rejection_types, affected_claims, rejection_count, draft_count,
                model_used, degraded
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (tenant_id, case_id) DO UPDATE SET
                target_patent_no = excluded.target_patent_no,
                jurisdiction = excluded.jurisdiction,
                analyzed_at = excluded.analyzed_at,
                analyzed_by = excluded.analyzed_by,
                statutory_deadline = excluded.statutory_deadline,
                recommended_deadline = excluded.recommended_deadline,
                rejection_types = excluded.rejection_types,
                affected_claims = excluded.affected_claims,
                rejection_count = excluded.rejection_count,
                draft_count = excluded.draft_count,
                model_used = excluded.model_used,
                degraded = excluded.degraded
            """,
            row,
        )
        conn.commit()


def summaries_for_tenant(tenant_id: str) -> dict[str, dict[str, Any]]:
    """case_id -> summary dict, for one tenant only."""
    with _lock:
        rows = (
            _connection()
            .execute(
                f"SELECT {_COLS} FROM case_summaries WHERE tenant_id = ?",  # noqa: S608
                (tenant_id,),
            )
            .fetchall()
        )
    names = [c.strip() for c in _COLS.split(",")]
    out: dict[str, dict[str, Any]] = {}
    for raw in rows:
        d = dict(zip(names, raw, strict=True))
        d["rejection_types"] = json.loads(d["rejection_types"])
        d["affected_claims"] = json.loads(d["affected_claims"])
        d["degraded"] = bool(d["degraded"])
        out[d.pop("case_id")] = d
    return out


def erase_tenant(tenant_id: str) -> int:
    """Delete every summary of a tenant (tenant off-boarding). Returns rows removed."""
    with _lock:
        conn = _connection()
        cur = conn.execute("DELETE FROM case_summaries WHERE tenant_id = ?", (tenant_id,))
        conn.commit()
        return cur.rowcount
