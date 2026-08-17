"""Очередь предложений эксперту.

Главное правило ML-части: ничего не применяется само. Любой вывод модели — черновик,
который человек-эксперт утверждает или отклоняет. Поэтому очередь живёт в собственной
базе ML: база тренажёра открыта только на чтение и остаётся неприкосновенной.

Черновик по одной сессии не размножается: рекомендацию по ходу прохождения пересчитывают
многократно, и каждый пересчёт должен обновлять существующую запись, а не добавлять
эксперту ещё одну строку. За это отвечает `dedup_key` и частичный уникальный индекс.
"""

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ml import config

# Что предлагает ML.
KIND_NEXT_SESSION = "next_session"  # профильный сценарий конкретному оператору
KIND_SCENARIO_CHANGE = "scenario_change"  # правка существующего сценария
KIND_NEW_SCENARIO = "new_scenario"  # новый сценарий по результатам всех операторов
KINDS = (KIND_NEXT_SESSION, KIND_SCENARIO_CHANGE, KIND_NEW_SCENARIO)

STATUS_DRAFT = "draft"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"

SCHEMA = """
CREATE TABLE IF NOT EXISTS proposals (
    id             TEXT PRIMARY KEY,
    kind           TEXT NOT NULL,
    status         TEXT NOT NULL,
    dedup_key      TEXT NOT NULL,
    title          TEXT NOT NULL,
    operator_id    TEXT,
    session_id     TEXT,
    payload_json   TEXT NOT NULL,
    evidence_json  TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    reviewed_by    TEXT,
    reviewed_at    TEXT,
    review_comment TEXT
);
CREATE INDEX IF NOT EXISTS ix_proposals_status ON proposals (status, created_at);
-- Незакрытый черновик на одну тему может быть только один. Решённые предложения
-- остаются в истории и под ограничение не попадают.
CREATE UNIQUE INDEX IF NOT EXISTS uq_proposals_open_topic
    ON proposals (kind, dedup_key) WHERE status = 'draft';
"""


class ProposalNotFound(Exception):
    """Предложения с таким идентификатором нет."""


class ProposalAlreadyReviewed(Exception):
    """Решение по предложению уже принято и не переписывается."""


@dataclass(frozen=True, slots=True)
class Proposal:
    id: str
    kind: str
    status: str
    dedup_key: str
    title: str
    operator_id: str | None
    session_id: str | None
    payload: dict[str, Any]
    evidence: list[str]
    created_at: str
    updated_at: str
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    review_comment: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "title": self.title,
            "operator_id": self.operator_id,
            "session_id": self.session_id,
            "payload": self.payload,
            "evidence": self.evidence,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at,
            "review_comment": self.review_comment,
        }


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    """Открывает базу ML и создаёт схему, если её ещё нет."""

    path = db_path or config.ML_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def save_draft(
    conn: sqlite3.Connection,
    *,
    kind: str,
    dedup_key: str,
    title: str,
    payload: dict[str, Any],
    evidence: list[str],
    operator_id: str | None = None,
    session_id: str | None = None,
) -> Proposal:
    """Создаёт черновик или обновляет незакрытый черновик по той же теме."""

    if kind not in KINDS:
        raise ValueError(f"Неизвестный вид предложения: {kind}")

    now = _now()
    conn.execute(
        """
        INSERT INTO proposals (id, kind, status, dedup_key, title, operator_id, session_id,
                               payload_json, evidence_json, created_at, updated_at)
        VALUES (?, ?, 'draft', ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (kind, dedup_key) WHERE status = 'draft' DO UPDATE SET
            title = excluded.title,
            payload_json = excluded.payload_json,
            evidence_json = excluded.evidence_json,
            updated_at = excluded.updated_at
        """,
        (
            str(uuid.uuid4()),
            kind,
            dedup_key,
            title,
            operator_id,
            session_id,
            json.dumps(payload, ensure_ascii=False),
            json.dumps(evidence, ensure_ascii=False),
            now,
            now,
        ),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM proposals WHERE kind = ? AND dedup_key = ? AND status = 'draft'",
        (kind, dedup_key),
    ).fetchone()
    return _to_proposal(row)


def get(conn: sqlite3.Connection, proposal_id: str) -> Proposal:
    row = conn.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
    if row is None:
        raise ProposalNotFound(proposal_id)
    return _to_proposal(row)


def list_proposals(
    conn: sqlite3.Connection,
    status: str | None = None,
    kind: str | None = None,
    limit: int = 50,
) -> list[Proposal]:
    sql = "SELECT * FROM proposals"
    filters: list[str] = []
    params: list[Any] = []
    if status:
        filters.append("status = ?")
        params.append(status)
    if kind:
        filters.append("kind = ?")
        params.append(kind)
    if filters:
        sql += " WHERE " + " AND ".join(filters)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    return [_to_proposal(row) for row in conn.execute(sql, params)]


def review(
    conn: sqlite3.Connection,
    proposal_id: str,
    *,
    status: str,
    expert_id: str,
    comment: str | None = None,
) -> Proposal:
    """Решение эксперта. Принимается один раз и не переписывается задним числом."""

    if status not in (STATUS_APPROVED, STATUS_REJECTED):
        raise ValueError(f"Недопустимое решение: {status}")

    current = get(conn, proposal_id)
    if current.status != STATUS_DRAFT:
        raise ProposalAlreadyReviewed(f"{proposal_id}: {current.status}")

    now = _now()
    conn.execute(
        """
        UPDATE proposals
        SET status = ?, reviewed_by = ?, reviewed_at = ?, review_comment = ?, updated_at = ?
        WHERE id = ?
        """,
        (status, expert_id, now, comment, now, proposal_id),
    )
    conn.commit()
    return get(conn, proposal_id)


def _to_proposal(row: sqlite3.Row) -> Proposal:
    return Proposal(
        id=row["id"],
        kind=row["kind"],
        status=row["status"],
        dedup_key=row["dedup_key"],
        title=row["title"],
        operator_id=row["operator_id"],
        session_id=row["session_id"],
        payload=json.loads(row["payload_json"]),
        evidence=json.loads(row["evidence_json"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        reviewed_by=row["reviewed_by"],
        reviewed_at=row["reviewed_at"],
        review_comment=row["review_comment"],
    )


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
