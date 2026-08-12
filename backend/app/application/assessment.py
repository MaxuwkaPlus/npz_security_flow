"""SAGAT-контрольные точки и анкета NASA-TLX."""

from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.errors import ConflictError, NotFoundError, PreconditionFailedError
from app.domain.nasa_tlx import TlxResponse, validate
from app.domain.sagat import SagatCheckpointSpec, SagatPolicy, score_answers
from app.infrastructure.db.models import (
    NasaTlxResponse,
    ProcessSnapshot,
    SagatAnswer,
    SagatCheckpoint,
    TrainingSession,
)
from app.infrastructure.db.types import utcnow
from app.infrastructure.db.unit_of_work import UnitOfWork

STATUS_OPEN = "open"
STATUS_ANSWERED = "answered"
STATUS_EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class QuestionView:
    code: str
    kind: str
    prompt: str
    options: list[str]


@dataclass(frozen=True, slots=True)
class CheckpointView:
    """Вопросы без эталонов: ответ вычисляется на сервере при проверке."""

    id: str
    checkpoint_code: str
    status: str
    triggered_sim_time_ms: int
    answers_deadline_sim_time_ms: int
    questions: list[QuestionView]


@dataclass(frozen=True, slots=True)
class CheckpointResult:
    id: str
    checkpoint_code: str
    status: str
    scores: dict[str, float]
    earned: float
    maximum: float


async def open_checkpoint(
    uow: UnitOfWork,
    training_session: TrainingSession,
    spec: SagatCheckpointSpec,
    metrics: Mapping[str, float],
    earlier_metrics: Mapping[str, float],
) -> SagatCheckpoint:
    """Контрольная точка запоминает состояние установки на момент вопроса."""

    checkpoint = SagatCheckpoint(
        session_id=training_session.id,
        checkpoint_code=spec.code,
        triggered_sim_time_ms=training_session.sim_time_ms,
        status=STATUS_OPEN,
        answers_deadline_sim_time_ms=training_session.sim_time_ms + spec.answer_deadline_ms,
        metrics_json=dict(metrics),
        earlier_metrics_json=dict(earlier_metrics),
    )
    uow.session.add(checkpoint)
    await uow.flush()
    uow.sessions.append_event(
        training_session,
        "sagat_requested",
        "sagat",
        {"checkpoint_code": spec.code, "question_codes": [q.code for q in spec.questions]},
        aggregate_id=checkpoint.id,
    )
    return checkpoint


async def current_checkpoint(uow: UnitOfWork, session_id: str, policy: SagatPolicy) -> CheckpointView | None:
    """Открытая контрольная точка, на которую оператор ещё не ответил."""

    query = (
        select(SagatCheckpoint)
        .where(SagatCheckpoint.session_id == session_id, SagatCheckpoint.status == STATUS_OPEN)
        .order_by(SagatCheckpoint.triggered_sim_time_ms)
        .limit(1)
    )
    checkpoint = await uow.session.scalar(query)
    if checkpoint is None:
        return None
    spec = policy.checkpoint(checkpoint.checkpoint_code)
    questions = [] if spec is None else spec.questions
    return CheckpointView(
        id=checkpoint.id,
        checkpoint_code=checkpoint.checkpoint_code,
        status=checkpoint.status,
        triggered_sim_time_ms=checkpoint.triggered_sim_time_ms,
        answers_deadline_sim_time_ms=checkpoint.answers_deadline_sim_time_ms,
        questions=[
            QuestionView(code=q.code, kind=q.kind, prompt=q.prompt, options=list(q.options))
            for q in questions
        ],
    )


async def submit_answers(
    uow: UnitOfWork,
    session_id: str,
    checkpoint_id: str,
    answers: Mapping[str, str],
    policy: SagatPolicy,
) -> CheckpointResult:
    """Ответы оцениваются сразу: эталон выводится из состояния на момент вопроса."""

    checkpoint = await _load_checkpoint(uow, session_id, checkpoint_id)
    if checkpoint.status != STATUS_OPEN:
        return _result(checkpoint)

    spec = policy.checkpoint(checkpoint.checkpoint_code)
    if spec is None:
        raise PreconditionFailedError(
            "SAGAT_CHECKPOINT_NOT_CONFIGURED",
            "Контрольная точка отсутствует в версии сценария",
            {"checkpoint_code": checkpoint.checkpoint_code},
        )

    training_session = await uow.sessions.get(session_id)
    assert training_session is not None
    if training_session.sim_time_ms > checkpoint.answers_deadline_sim_time_ms:
        # Просроченная контрольная точка закрывается нулевым результатом.
        checkpoint.status = STATUS_EXPIRED
        return _result(checkpoint)

    scores = score_answers(spec.questions, answers, checkpoint.metrics_json, checkpoint.earlier_metrics_json)
    for question_code, score in scores.items():
        uow.session.add(
            SagatAnswer(
                checkpoint_id=checkpoint.id,
                question_code=question_code,
                answer_json={"answer": answers.get(question_code)},
                score=score,
            )
        )
    checkpoint.status = STATUS_ANSWERED
    uow.sessions.append_event(
        training_session,
        "sagat_answered",
        "sagat",
        {"checkpoint_code": checkpoint.checkpoint_code, "earned": sum(scores.values())},
        aggregate_id=checkpoint.id,
    )
    await uow.flush()
    return CheckpointResult(
        id=checkpoint.id,
        checkpoint_code=checkpoint.checkpoint_code,
        status=checkpoint.status,
        scores=scores,
        earned=round(sum(scores.values()), 2),
        maximum=float(len(scores)),
    )


async def submit_nasa_tlx(uow: UnitOfWork, session_id: str, values: Mapping[str, float]) -> NasaTlxResponse:
    """Анкета заполняется один раз за сессию и не влияет на квалификационную оценку."""

    training_session = await uow.sessions.get(session_id)
    if training_session is None:
        raise NotFoundError("SESSION_NOT_FOUND", "Сессия не найдена")

    error = validate(values)
    if error is not None:
        raise PreconditionFailedError("NASA_TLX_INVALID", error, {})

    existing = await uow.session.scalar(
        select(NasaTlxResponse).where(NasaTlxResponse.session_id == session_id)
    )
    if existing is not None:
        raise ConflictError("NASA_TLX_ALREADY_SUBMITTED", "Анкета уже заполнена", {})

    response = NasaTlxResponse(
        session_id=session_id,
        values_json=dict(values),
        raw_tlx_score=TlxResponse(values).raw_score(),
        submitted_at=utcnow(),
    )
    uow.session.add(response)
    await uow.flush()
    return response


async def snapshot_metrics_before(uow: UnitOfWork, session_id: str, sim_time_ms: int) -> dict[str, float]:
    """Производные значения ближайшего снимка не позже указанного момента."""

    query = (
        select(ProcessSnapshot)
        .where(ProcessSnapshot.session_id == session_id, ProcessSnapshot.sim_time_ms <= sim_time_ms)
        .order_by(ProcessSnapshot.sim_time_ms.desc())
        .limit(1)
    )
    snapshot = await uow.session.scalar(query)
    if snapshot is None:
        return {}
    return {**snapshot.visible_values_json, **snapshot.derived_values_json}


async def _load_checkpoint(uow: UnitOfWork, session_id: str, checkpoint_id: str) -> SagatCheckpoint:
    checkpoint = await uow.session.get(
        SagatCheckpoint, checkpoint_id, options=[selectinload(SagatCheckpoint.answers)]
    )
    if checkpoint is None or checkpoint.session_id != session_id:
        raise NotFoundError("SAGAT_CHECKPOINT_NOT_FOUND", "Контрольная точка не найдена")
    return checkpoint


def _result(checkpoint: SagatCheckpoint) -> CheckpointResult:
    scores = {answer.question_code: answer.score for answer in checkpoint.answers}
    return CheckpointResult(
        id=checkpoint.id,
        checkpoint_code=checkpoint.checkpoint_code,
        status=checkpoint.status,
        scores=scores,
        earned=round(sum(scores.values()), 2),
        maximum=float(len(scores)),
    )
