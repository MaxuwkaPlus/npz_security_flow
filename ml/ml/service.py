"""HTTP-сервис ML-части.

Отдельное приложение на своём порту: тренажёр работает без него, а его отказ не
влияет на прохождение. Всё, что он умеет, — читать журнал, считать навыки и класть
черновики предложений в очередь эксперта.

Аудитория всех ручек — эксперт и инструктор. Операторскому интерфейсу отсюда ничего
не передаётся: подсказка во время прохождения обесценила бы проверку навыка.
"""

import sqlite3
from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from ml import config, data, llm, mining, proposals, recommend, skills

app = FastAPI(
    title="ЭЛОУ-АВТ: рекомендации по обучению",
    description=(
        "Находит слабые места операторов и предлагает сценарии. "
        "Любое предложение — черновик и вступает в силу только после утверждения экспертом."
    ),
    version="0.1.0",
)


class ReviewRequest(BaseModel):
    expert_id: str = Field(min_length=1, max_length=64, description="Кто принял решение")
    comment: str | None = Field(default=None, max_length=1000)


def get_db() -> Iterator[sqlite3.Connection]:
    """Соединение с базой ML на время запроса."""

    conn = proposals.connect()
    try:
        yield conn
    finally:
        conn.close()


Db = Annotated[sqlite3.Connection, Depends(get_db)]


@app.get("/health", summary="Состояние сервиса")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "llm_available": llm.available(),
        "llm_model": config.LLM_MODEL,
        "backend_db_readable": config.BACKEND_DB.exists(),
    }


@app.get("/ml/v1/sessions/{session_id}/advice", summary="Рекомендация по прохождению")
def session_advice(session_id: str, db: Db, save: bool = True) -> dict[str, Any]:
    """Слабое место оператора и профильный сценарий на следующее прохождение.

    Работает и на незавершённой сессии: рекомендацию можно готовить по ходу, пока
    инструктор наблюдает за прохождением. Результат уходит эксперту в очередь
    предложений, а не оператору.
    """

    facts = data.load_backend_session(session_id)
    if facts is None:
        raise HTTPException(status_code=404, detail=f"Сессия не найдена: {session_id}")

    profile = skills.evaluate(facts)
    recommendation = recommend.build(facts, profile).to_json()
    text = llm.describe_recommendation(recommendation)

    proposal_id = None
    if save:
        proposal = proposals.save_draft(
            db,
            kind=proposals.KIND_NEXT_SESSION,
            dedup_key=session_id,
            title=text["title"],
            payload={"recommendation": recommendation, "text": text},
            evidence=list(recommendation["evidence"]),
            operator_id=facts.operator_id,
            session_id=session_id,
        )
        proposal_id = proposal.id

    return {
        "audience": "expert",
        "session_status": facts.status,
        "skills": profile.to_json(),
        "recommendation": recommendation,
        "text": text,
        "proposal_id": proposal_id,
        "requires_expert_approval": True,
    }


@app.get("/ml/v1/operators/{operator_id}/profile", summary="Профиль навыков оператора")
def operator_profile(operator_id: str) -> dict[str, Any]:
    """Как навыки оператора выглядят по всем его прохождениям."""

    sessions = [facts for facts in data.load_backend_sessions() if facts.operator_id == operator_id]
    if not sessions:
        raise HTTPException(status_code=404, detail=f"Прохождений оператора не найдено: {operator_id}")

    profiles = [skills.evaluate(facts) for facts in sessions]
    return {
        "operator_id": operator_id,
        "sessions": [profile.to_json() for profile in profiles],
        "average_scores": skills.average_scores(profiles),
        "weak_share": skills.weak_share(profiles),
    }


@app.get("/ml/v1/proposals", summary="Очередь предложений эксперту")
def list_proposals(
    db: Db,
    status: Annotated[str | None, Query(description="draft | approved | rejected")] = None,
    kind: Annotated[str | None, Query(description="next_session | scenario_change | new_scenario")] = None,
    limit: int = 50,
) -> dict[str, Any]:
    items = proposals.list_proposals(db, status=status, kind=kind, limit=limit)
    return {"total": len(items), "items": [item.to_json() for item in items]}


@app.get("/ml/v1/proposals/{proposal_id}", summary="Одно предложение")
def get_proposal(proposal_id: str, db: Db) -> dict[str, Any]:
    return _reviewed(lambda: proposals.get(db, proposal_id))


@app.post("/ml/v1/proposals/{proposal_id}/approve", summary="Утвердить предложение")
def approve_proposal(proposal_id: str, request: ReviewRequest, db: Db) -> dict[str, Any]:
    """Решение эксперта. Только после него предложение можно вносить в тренажёр."""

    return _reviewed(
        lambda: proposals.review(
            db,
            proposal_id,
            status=proposals.STATUS_APPROVED,
            expert_id=request.expert_id,
            comment=request.comment,
        )
    )


@app.post("/ml/v1/proposals/{proposal_id}/reject", summary="Отклонить предложение")
def reject_proposal(proposal_id: str, request: ReviewRequest, db: Db) -> dict[str, Any]:
    return _reviewed(
        lambda: proposals.review(
            db,
            proposal_id,
            status=proposals.STATUS_REJECTED,
            expert_id=request.expert_id,
            comment=request.comment,
        )
    )


@app.post("/ml/v1/scenario-proposals/mine", summary="Найти системные проблемы")
def mine_scenarios(
    db: Db,
    source: Annotated[str, Query(description="backend | corpus")] = "backend",
    save: bool = True,
) -> dict[str, Any]:
    """Ищет проблемы, общие для всех операторов, и предлагает новые сценарии.

    Источник `corpus` нужен для демонстрации и калибровки: в нём 36 прохождений с
    известным поведением, тогда как живых сессий на старте эксплуатации мало.
    """

    if source == "corpus":
        sessions = data.load_corpus()
    elif source == "backend":
        sessions = data.load_backend_sessions()
    else:
        raise HTTPException(status_code=400, detail="Источник должен быть backend или corpus")

    findings = mining.mine(sessions)
    items = []
    for finding in findings:
        text = llm.describe_scenario_proposal(finding.to_json())
        proposal_id = None
        if save:
            proposal = proposals.save_draft(
                db,
                kind=proposals.KIND_NEW_SCENARIO,
                dedup_key=finding.key,
                title=text["title"],
                payload={"finding": finding.to_json(), "text": text},
                evidence=[finding.summary],
            )
            proposal_id = proposal.id
        items.append({"finding": finding.to_json(), "text": text, "proposal_id": proposal_id})

    return {
        "source": source,
        "sessions_analysed": len(sessions),
        "min_sessions_required": config.MINING.min_sessions,
        "total": len(items),
        "items": items,
        "requires_expert_approval": True,
    }


def _reviewed(action) -> dict[str, Any]:
    """Ошибки очереди переводятся в понятные коды HTTP в одном месте."""

    try:
        return action().to_json()
    except proposals.ProposalNotFound as error:
        raise HTTPException(status_code=404, detail=f"Предложение не найдено: {error}") from error
    except proposals.ProposalAlreadyReviewed as error:
        raise HTTPException(status_code=409, detail=f"Решение уже принято: {error}") from error
